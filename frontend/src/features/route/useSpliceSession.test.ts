/**
 * 区間の乗り換え（`useSpliceSession`）——候補を元に、区間を別の候補の道へ差し替えた経路を組み、backendで評価して一覧へ入れる。
 *
 * ここで見ないもの:
 * - 乗り換え先の区間の求め方・経路の継ぎ方 → `routeSplice.ts`
 * - 入力からpayloadを作る規則 → `generationRequest.ts`
 * - 所要時間の並べ方 → `routeTabLabel.ts`
 *
 * 差し替えた部品: 生成の通信（`routeApi.generateRoutes`）と軸カタログ（`useAxisCatalog`）は返す値をテストが決める。
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { axisCatalogFromResponse, CLIENT_TUNING_IDS, type AxisCatalog } from "@/lib/axisCatalog";
import { catalogEntry, catalogResponse } from "@/testing/catalogAxes";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import { buildGenerateRequest, type GenerationInput } from "@/features/route/generationRequest";
import { SPLICED_ROUTE_ID_PREFIX } from "@/features/route/routeTabLabel";
import type { RouteCandidate } from "@/types/route";

const catalog = vi.hoisted(() => ({ current: undefined as unknown }));
vi.mock("@/hooks/useAxisCatalog", () => ({ useAxisCatalog: () => catalog.current }));
vi.mock("@/features/route/routeApi", () => ({ generateRoutes: vi.fn() }));

import { generateRoutes } from "@/features/route/routeApi";
import { useSpliceSession, type SpliceSessionInputs } from "./useSpliceSession";

const catalogWith = (clientTuning: Record<string, number>): AxisCatalog =>
  axisCatalogFromResponse(catalogResponse([catalogEntry({ axis_id: "axis_a" })], { client_tuning: clientTuning }));
const TUNED = catalogWith({ [CLIENT_TUNING_IDS.minStretchKm]: 0.2 });

const INPUT: GenerationInput = {
  origin: { latitude: 35, longitude: 139 },
  distanceKm: null,
  distanceToleranceKm: 5,
  maxRoutes: 3,
  assumedSpeedKmh: 20,
  startTime: new Date("2026-09-25T03:00:00Z"),
  startTimePinned: false,
  hardFilters: {},
  lensAxisId: "axis_a",
  routePreference: null,
  waypoints: [],
  destination: { latitude: 35.1, longitude: 139 },
};

// 3本とも同じ地点（n0〜n5）で交わる。AとCは1つ目の分かれ道だけ、AとBは両方の分かれ道で別の道を通る。
const NODES = ["n0", "n1", "n2", "n3", "n4", "n5"];
const pointsOf = (flat: number[]): GeoJSON.Position[] =>
  Array.from({ length: flat.length / 2 }, (_, i) => [flat[2 * i], flat[2 * i + 1]]);
const lineOf = (flat: number[]) => ({ type: "LineString" as const, coordinates: pointsOf(flat) });
const ROUTE_A = makeRouteCandidate({
  id: "route-0",
  estimated_duration_seconds: 600,
  edge_ids: ["e1", "a1", "e2", "a2", "e3"],
  node_ids: NODES,
  edge_point_offsets: [0, 1, 2, 3, 4, 5],
  geometry: lineOf([0, 0, 1, 0, 2, 0, 3, 0, 4, 0, 5, 0]),
});
const ROUTE_B = makeRouteCandidate({
  id: "route-1",
  estimated_duration_seconds: 900,
  edge_ids: ["e1", "b1", "e2", "b2", "e3"],
  node_ids: NODES,
  edge_point_offsets: [0, 1, 3, 4, 6, 7],
  geometry: lineOf([0, 0, 1, 0, 1.5, 1, 2, 0, 3, 0, 3.5, 1, 4, 0, 5, 0]),
});
const ROUTE_C = makeRouteCandidate({
  id: "route-2",
  estimated_duration_seconds: 1200,
  edge_ids: ["e1", "c1", "e2", "a2", "e3"],
  node_ids: NODES,
  edge_point_offsets: [0, 1, 3, 4, 5, 6],
  geometry: lineOf([0, 0, 1, 0, 1.5, -1, 2, 0, 3, 0, 4, 0, 5, 0]),
});
const ROUTES = [ROUTE_A, ROUTE_B, ROUTE_C];
// Bの1つ目・2つ目の分かれ道、Cの分かれ道を通る点。
const B_FIRST: GeoJSON.Position = [1.5, 1];
const B_SECOND: GeoJSON.Position = [3.5, 1];
const C_FIRST: GeoJSON.Position = [1.5, -1];

const onApplyStart = vi.fn();
const onApplied = vi.fn();
type Props = Omit<SpliceSessionInputs, "onApplyStart" | "onApplied">;
const PROPS: Props = { routes: ROUTES, generatedInput: INPUT, hasSelectedRoute: true };

function render(props: Partial<Props> = {}) {
  return renderHook((current: Props) => useSpliceSession({ ...current, onApplyStart, onApplied }), {
    initialProps: { ...PROPS, ...props },
  });
}
type Rendered = ReturnType<typeof render>;

function startEditing(props: Partial<Props> = {}, routeId = ROUTE_A.id) {
  const hook = render(props);
  act(() => hook.result.current.start(routeId));
  return hook;
}
const through = (hook: Rendered, point: GeoJSON.Position) =>
  hook.result.current.map.spliceStretches.find((stretch) =>
    stretch.coordinates.some(([x, y]) => x === point[0] && y === point[1]),
  );
function choose(hook: Rendered, point: GeoJSON.Position) {
  const found = through(hook, point);
  if (!found) throw new Error(`${point.join(",")}を通る乗り換え先が無い`);
  act(() => hook.result.current.map.onSpliceStretchSelect(found.index));
}
const panel = (hook: Rendered) => {
  const value = hook.result.current.panel;
  if (!value) throw new Error("編集面が無い");
  return value;
};
function evaluated(id: string, edgeIds: string[], seconds = 700): RouteCandidate {
  return makeRouteCandidate({ id, edge_ids: edgeIds, estimated_duration_seconds: seconds });
}
function respond(routes: RouteCandidate[]) {
  vi.mocked(generateRoutes).mockResolvedValueOnce({ routes, conditions: {} as never });
}
function deferred() {
  let resolve!: (value: Awaited<ReturnType<typeof generateRoutes>>) => void;
  const promise = new Promise<Awaited<ReturnType<typeof generateRoutes>>>((done) => (resolve = done));
  return { promise, resolve };
}

beforeEach(() => {
  catalog.current = TUNED;
  vi.mocked(generateRoutes).mockReset();
  onApplyStart.mockReset();
  onApplied.mockReset();
});

describe("入口", () => {
  it("目的地の生成で候補が2本以上あり、候補を選んでいて、区間を割る下限を引けるときだけ始められる", () => {
    expect(render().result.current.canStart).toBe(true);
    expect(render({ generatedInput: { ...INPUT, destination: null } }).result.current.canStart).toBe(false);
    expect(render({ generatedInput: null }).result.current.canStart).toBe(false);
    expect(render({ routes: [ROUTE_A] }).result.current.canStart).toBe(false);
    expect(render({ hasSelectedRoute: false }).result.current.canStart).toBe(false);
    catalog.current = catalogWith({});
    expect(render().result.current.canStart).toBe(false);
  });

  it("始める前は編集面も乗り換え先も無い", () => {
    const { result } = render();
    expect(result.current.editingRoute).toBeNull();
    expect(result.current.panel).toBeNull();
    expect(result.current.map.spliceStretches).toEqual([]);
    expect(result.current.map.splicedRoute).toBeNull();
  });
});

describe("編集", () => {
  it("始めると、元の候補を編集面と地図（いま作っているルート）へ渡し、他の候補が別の道を通る区間を乗り換え先として出す", () => {
    const hook = startEditing();
    expect(hook.result.current.editingRoute).toBe(ROUTE_A);
    expect(panel(hook)).toMatchObject({ displayed: ROUTE_A, appliedCount: 0, hasAlternatives: true, preview: null });
    expect(hook.result.current.map.splicedRoute).toEqual(ROUTE_A.geometry.coordinates);
    for (const point of [B_FIRST, B_SECOND, C_FIRST]) expect(through(hook, point)).toBeDefined();
  });

  it("乗り換え先を選ぶとその道へ乗り換え、乗り換えた経路から次の乗り換え先を出す。1つ戻す・全部戻すで戻る", () => {
    const hook = startEditing();
    choose(hook, B_FIRST);
    expect(panel(hook).appliedCount).toBe(1);
    expect(hook.result.current.map.splicedRoute).toContainEqual(B_FIRST);
    expect(through(hook, B_FIRST)).toBeUndefined();
    expect(through(hook, B_SECOND)).toBeDefined();
    expect(through(hook, C_FIRST)).toBeDefined();

    choose(hook, B_SECOND);
    expect(panel(hook).appliedCount).toBe(2);
    act(() => panel(hook).onUndo());
    expect(panel(hook).appliedCount).toBe(1);
    expect(hook.result.current.map.splicedRoute).not.toContainEqual(B_SECOND);
    act(() => panel(hook).onReset());
    expect(panel(hook).appliedCount).toBe(0);
    expect(hook.result.current.map.splicedRoute).toEqual(ROUTE_A.geometry.coordinates);
  });

  it("地図から知らない位置が届いても何も変えない", () => {
    const hook = startEditing();
    act(() => hook.result.current.map.onSpliceStretchSelect(99_999));
    expect(panel(hook).appliedCount).toBe(0);
  });

  it("区間を割る下限を引けない間は乗り換え先を作らない（較正と別の切り方で出さない）", () => {
    const hook = startEditing();
    catalog.current = catalogWith({});
    hook.rerender(PROPS);
    expect(hook.result.current.map.spliceStretches).toEqual([]);
    expect(panel(hook).hasAlternatives).toBe(false);
  });

  it("線の形を持たない候補（Edge idだけ）では、地図に描けない乗り換え先を出さない", () => {
    const bare = (candidate: RouteCandidate) =>
      makeRouteCandidate({ id: candidate.id, edge_ids: candidate.edge_ids, node_ids: candidate.node_ids });
    const hook = startEditing({ routes: ROUTES.map(bare) });
    expect(hook.result.current.map.spliceStretches).toEqual([]);
    expect(panel(hook).hasAlternatives).toBe(false);
  });

  it("やめると編集面も地図の乗り換え先も消え、次に始めた編集は空から始まる", () => {
    const hook = startEditing();
    choose(hook, B_FIRST);
    act(() => panel(hook).onCancel());
    expect(hook.result.current.panel).toBeNull();
    expect(hook.result.current.map.splicedRoute).toBeNull();
    act(() => hook.result.current.start(ROUTE_A.id));
    expect(panel(hook).appliedCount).toBe(0);
  });

  it("作り直す・消すと（表示中の候補を作った生成が替わると）、候補のidが同じでも編集は終わる", () => {
    const hook = startEditing();
    hook.rerender({ ...PROPS, generatedInput: { ...INPUT } });
    expect(hook.result.current.editingRoute).toBeNull();
    expect(hook.result.current.panel).toBeNull();

    const other = startEditing();
    other.rerender({ ...PROPS, generatedInput: null, routes: [] });
    expect(other.result.current.editingRoute).toBeNull();
  });

  it("編集の元の候補が一覧から消えたら、編集は効かない", () => {
    const hook = startEditing();
    hook.rerender({ ...PROPS, routes: [ROUTE_B, ROUTE_C] });
    expect(hook.result.current.panel).toBeNull();
  });
});

describe("差分を見る", () => {
  it("表示中の候補を作った入力へ、乗り換えた経路のEdge列を載せて評価し、結果を編集面へ渡す。同じ組み合わせは投げ直さない", async () => {
    const hook = startEditing();
    choose(hook, B_FIRST);
    const result = evaluated("x", ["e1", "b1", "e2", "a2", "e3"]);
    respond([result]);
    await act(async () => panel(hook).onPreview());
    expect(generateRoutes).toHaveBeenCalledWith({
      ...buildGenerateRequest(INPUT),
      spliced_edge_ids: ["e1", "b1", "e2", "a2", "e3"],
    });
    expect(panel(hook).preview).toBe(result);

    choose(hook, B_SECOND);
    expect(panel(hook).preview).toBeNull();
    act(() => panel(hook).onUndo());
    expect(panel(hook).preview).toBe(result);
    await act(async () => panel(hook).onPreview());
    expect(generateRoutes).toHaveBeenCalledTimes(1);
  });

  it("乗り換えていない間は評価しない", async () => {
    const hook = startEditing();
    await act(async () => panel(hook).onPreview());
    expect(generateRoutes).not.toHaveBeenCalled();
  });

  it("評価を待っている間は待っていると返し、選び直しても続ける。待っている間に押しても投げ直さない", async () => {
    const hook = startEditing();
    choose(hook, B_FIRST);
    const pending = deferred();
    vi.mocked(generateRoutes).mockReturnValueOnce(pending.promise);
    act(() => {
      void panel(hook).onPreview();
    });
    expect(panel(hook).previewing).toBe(true);
    choose(hook, B_SECOND);
    expect(panel(hook).previewing).toBe(true);
    act(() => {
      void panel(hook).onPreview();
    });
    expect(generateRoutes).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve({ routes: [evaluated("x", ["e1"])], conditions: {} as never }));
    expect(panel(hook).previewing).toBe(false);
  });

  it.each([
    ["評価が空で返る", () => respond([]), "組み合わせたルートを評価できませんでした"],
    [
      "通信が失敗する",
      () => vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混み合っています")),
      "混み合っています",
    ],
    [
      "Error以外で失敗する",
      () => vi.mocked(generateRoutes).mockRejectedValueOnce("壊れた"),
      "組み合わせたルートの評価に失敗しました",
    ],
  ])("%sと、理由を編集面に出す。次に乗り換え先を選ぶと消す", async (_c, arrange, shown) => {
    const hook = startEditing();
    choose(hook, B_FIRST);
    arrange();
    await act(async () => panel(hook).onPreview());
    expect(panel(hook).error).toBe(shown);
    choose(hook, B_SECOND);
    expect(panel(hook).error).toBeNull();
  });

  it("評価を待っている間に編集をやめたら、あとから届いた評価で編集へ戻さず、次の編集へも持ち込まない", async () => {
    const hook = startEditing();
    choose(hook, B_FIRST);
    const pending = deferred();
    vi.mocked(generateRoutes).mockReturnValueOnce(pending.promise);
    act(() => {
      void panel(hook).onPreview();
    });
    act(() => panel(hook).onCancel());
    await act(async () => pending.resolve({ routes: [evaluated("x", ["e1"])], conditions: {} as never }));
    expect(hook.result.current.panel).toBeNull();
    act(() => hook.result.current.start(ROUTE_A.id));
    expect(panel(hook)).toMatchObject({ appliedCount: 0, preview: null, previewing: false });
  });
});

describe("作成", () => {
  it("評価した経路を、合成の印のidで一覧へ所要時間の順に加えて選び、編集を終える。作る直前に知らせる", async () => {
    const hook = startEditing();
    choose(hook, B_FIRST);
    respond([evaluated("backend-id", ["e1", "b1", "e2", "a2", "e3"], 700)]);
    await act(async () => panel(hook).onApply());
    expect(onApplyStart).toHaveBeenCalledTimes(1);
    const created = {
      ...evaluated("backend-id", ["e1", "b1", "e2", "a2", "e3"], 700),
      id: `${SPLICED_ROUTE_ID_PREFIX}-3`,
    };
    expect(onApplied).toHaveBeenCalledWith({
      routes: [ROUTE_A, created, ROUTE_B, ROUTE_C],
      selectedRouteId: created.id,
    });
    expect(hook.result.current.panel).toBeNull();
  });

  it("作った経路が既にある候補と同じ道なら、一覧を変えずにその候補を選ぶ", async () => {
    const hook = startEditing();
    choose(hook, B_FIRST);
    choose(hook, B_SECOND);
    respond([evaluated("backend-id", ROUTE_B.edge_ids)]);
    await act(async () => panel(hook).onApply());
    expect(onApplied).toHaveBeenCalledWith({ routes: ROUTES, selectedRouteId: ROUTE_B.id });
  });

  it("評価済みの組み合わせは作るときに投げ直さない", async () => {
    const hook = startEditing();
    choose(hook, B_FIRST);
    respond([evaluated("x", ["e1", "b1", "e2", "a2", "e3"])]);
    await act(async () => panel(hook).onPreview());
    await act(async () => panel(hook).onApply());
    expect(generateRoutes).toHaveBeenCalledTimes(1);
    expect(onApplied).toHaveBeenCalledTimes(1);
  });

  it("続けて2回押しても1本だけ作る。作っている間は作っていると返す", async () => {
    const hook = startEditing();
    choose(hook, B_FIRST);
    const pending = deferred();
    vi.mocked(generateRoutes).mockReturnValueOnce(pending.promise);
    act(() => {
      void panel(hook).onApply();
      void panel(hook).onApply();
    });
    expect(panel(hook).applying).toBe(true);
    await act(async () =>
      pending.resolve({ routes: [evaluated("x", ["e1", "b1", "e2", "a2", "e3"])], conditions: {} as never }),
    );
    expect(generateRoutes).toHaveBeenCalledTimes(1);
    expect(onApplied).toHaveBeenCalledTimes(1);
  });

  it("失敗したら編集を続けて理由を出し、もう一度押せる", async () => {
    const hook = startEditing();
    choose(hook, B_FIRST);
    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混み合っています"));
    await act(async () => panel(hook).onApply());
    expect(panel(hook)).toMatchObject({ error: "混み合っています", applying: false });
    expect(onApplied).not.toHaveBeenCalled();

    respond([evaluated("x", ["e1", "b1", "e2", "a2", "e3"])]);
    await act(async () => panel(hook).onApply());
    expect(onApplied).toHaveBeenCalledTimes(1);
  });

  it("評価が空で返ったら作らず理由を出す", async () => {
    const hook = startEditing();
    choose(hook, B_FIRST);
    respond([]);
    await act(async () => panel(hook).onApply());
    expect(panel(hook).error).toBe("組み合わせたルートを評価できませんでした");
    expect(onApplied).not.toHaveBeenCalled();
  });

  it("乗り換えていない間は何もしない", async () => {
    const hook = startEditing();
    await act(async () => panel(hook).onApply());
    expect(onApplyStart).not.toHaveBeenCalled();
    expect(generateRoutes).not.toHaveBeenCalled();
  });
});
