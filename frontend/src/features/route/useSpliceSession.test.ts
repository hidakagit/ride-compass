/**
 * 区間の乗り換えの編集（`useSpliceSession.ts`）——目的地の生成で候補が2本以上あり、候補を選んでいて、区間を割る下限を
 * 引けるときだけ始められる。始めると元の候補を編集面と地図（いま作っているルート）へ渡し、他の候補が別の道を通る
 * 区間を乗り換え先として地図へ出す。乗り換え・1つ戻す・全部戻す・やめるができ、組み合わせた経路は表示中の候補を
 * 作った生成の入力でbackendに評価させ（同じ組み合わせは投げ直さない）、「作成」で作った経路か同じ道の既存の候補を
 * 渡して編集を終える。編集は始めたときの生成に結びつき、抜けると中身ごと消える。
 *
 * ここで見ないもの:
 * - 乗り換え先の求め方の細部（区間の割り方・下限・折り返しを出さない・重なる代替のまとめ方・形の継ぎ方） →
 *   `routeSplice.test.ts`。ここでは分かれ道が1つずつの網で、出る・乗り換えた経路から次が出ることを見る
 * - 編集面の表示（差・戻す操作・失敗の出し方） → `RouteSplicePanel/RouteSplicePanel.test.tsx`
 * - 地図の帯の描き方とタップ → `features/map/scene/groups/routes.test.ts`
 * - 作った経路を結果へ足す・既存の候補を選ぶ → `useRouteResults.test.ts`・`app/page.test.tsx`
 *
 * 差し替えたもの: 評価（生成のジョブ）と軸カタログの応答（網の層。`testing/generationJobs.ts`）。評価はジョブを作り
 * backendの回数制限に数えられるので、出した要求の数と中身を確かめる。
 *
 * 通さない分岐（どれも入口から作れない）:
 * - 生成の入力が無いときの`start`: 始められるのは目的地の生成があるときだけで、入口（`canStart`）が出ない
 * - 帯の相手が一覧に無い・帯の座標が2点未満: 相手は同じ一覧から引き、範囲は少なくとも1本のEdgeを持つ
 * - 1グループの選択肢の上限: 候補数の上限（`route-generate-config.json: max_routes`）より多くは並ばない
 * - 評価の入口の前提（編集・乗り換え・形が無い）と、編集が無いときの乗り換え: 呼ぶ側が先に同じ前提で止め、
 *   編集していない間は乗り換え先が出ない
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GenerationInput } from "@/features/route/generationRequest";
import { CLIENT_TUNING_IDS } from "@/lib/axisCatalog";
import { heldReplies, serveAxisCatalog } from "@/testing/backendServer";
import { catalogEntry, catalogResponse } from "@/testing/catalogAxes";
import { serveGenerationJobs } from "@/testing/generationJobs";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import type { GenerationConditions, RouteCandidate } from "@/types/route";

import { useSpliceSession } from "./useSpliceSession";

const CATALOG = catalogResponse([catalogEntry({ axis_id: "axis_a", default_weight: 1 })], {
  client_tuning: { [CLIENT_TUNING_IDS.minStretchKm]: 0.1 },
});
const CATALOG_WITHOUT_MIN_STRETCH = catalogResponse([catalogEntry({ axis_id: "axis_a", default_weight: 1 })]);

// 地点（[経度, 緯度]）。P0→P1→P2→P3が元の道で、P1とP2の間を、QかRを通る別の道が結ぶ。
const P0 = [139.7, 35.6];
const P1 = [139.71, 35.6];
const P2 = [139.72, 35.6];
const P3 = [139.73, 35.6];
const Q = [139.715, 35.61];
const R = [139.715, 35.605];

/** Edge 1本ごとに地点1つずつ進む候補。`stops`は通る地点の名前と位置（最後は終点）。 */
function routeThrough(id: string, edgeIds: string[], stops: [string, number[]][]): RouteCandidate {
  return makeRouteCandidate({
    id,
    edge_ids: edgeIds,
    node_ids: stops.map(([node]) => node),
    edge_point_offsets: stops.map((_, index) => index),
    geometry: { type: "LineString", coordinates: stops.map(([, position]) => position) },
  });
}

// 元: P1→P2を1本（e2）で進む。
const BASE = routeThrough(
  "base",
  ["e1", "e2", "e3"],
  [
    ["n0", P0],
    ["n1", P1],
    ["n2", P2],
    ["n3", P3],
  ],
);
// 別の道: P1→Q→P2（q1・q2）。
const VIA_Q = routeThrough(
  "via-q",
  ["e1", "q1", "q2", "e3"],
  [
    ["n0", P0],
    ["n1", P1],
    ["nq", Q],
    ["n2", P2],
    ["n3", P3],
  ],
);
// Qまでは同じで、Q→P2をRを通って進む（r1・r2）。Qの道へ乗り換えた後に、次の分かれ道になる。
const VIA_Q_R = routeThrough(
  "via-q-r",
  ["e1", "q1", "r1", "r2", "e3"],
  [
    ["n0", P0],
    ["n1", P1],
    ["nq", Q],
    ["nr", R],
    ["n2", P2],
    ["n3", P3],
  ],
);

const BASIS: GenerationInput = {
  origin: { latitude: 35.6, longitude: 139.7 },
  distanceKm: null,
  distanceToleranceKm: 5,
  maxRoutes: 4,
  assumedSpeedKmh: 22,
  startTime: new Date("2026-10-04T09:00:00Z"),
  startTimePinned: true,
  hardFilters: { motorway: true },
  lensAxisId: null,
  routePreference: { axis_a: 1 },
  waypoints: [],
  destination: { latitude: 35.6, longitude: 139.73 },
};

// 評価の応答に付く生成の条件（乗り換えは読まない）。
const CONDITIONS: GenerationConditions = {
  latitude: BASIS.origin.latitude,
  longitude: BASIS.origin.longitude,
  distance_km: 0,
  distance_tolerance_km: BASIS.distanceToleranceKm,
  route_preference: { axis_a: 1 },
  penalty_strength: 1,
  max_average_grade_percent: null,
  hard_filters: BASIS.hardFilters,
  max_routes: BASIS.maxRoutes,
  start_time: BASIS.startTime.toISOString(),
  assumed_speed_kmh: BASIS.assumedSpeedKmh,
  waypoints: null,
  destination: BASIS.destination,
  corrected_destination: null,
  generated_at: "2026-10-04T09:00:30Z",
};

type Props = Pick<Parameters<typeof useSpliceSession>[0], "routes" | "generatedInput" | "hasSelectedRoute">;

const PROPS: Props = { routes: [BASE, VIA_Q], generatedInput: BASIS, hasSelectedRoute: true };

function renderSplice(props: Partial<Props> = {}) {
  const onApplyStart = vi.fn();
  const onApplied = vi.fn();
  const rendered = renderHook((p: Props) => useSpliceSession({ ...p, onApplyStart, onApplied }), {
    initialProps: { ...PROPS, ...props },
  });
  return { ...rendered, onApplyStart, onApplied };
}

type Rendered = ReturnType<typeof renderSplice>;

/** 編集を始め、軸カタログ（区間を割る下限）が届いて編集面へ軸が渡るまで待つ。 */
async function startWithCatalog(rendered: Rendered, routeId = "base") {
  act(() => rendered.result.current.start(routeId));
  await waitFor(() => expect(rendered.result.current.panel?.axes).toHaveLength(1));
}

/** 編集を始め、乗り換え先が地図へ出るまで待つ。 */
async function startEditing(rendered: Rendered, routeId = "base") {
  act(() => rendered.result.current.start(routeId));
  await waitFor(() => expect(rendered.result.current.map.spliceStretches.length).toBeGreaterThan(0));
}

/** 地図に出ているn番目の乗り換え先をタップする。 */
function tapStretch(rendered: Rendered, n = 0) {
  const { index } = rendered.result.current.map.spliceStretches[n];
  act(() => rendered.result.current.map.onSpliceStretchSelect(index));
}

function evaluated(edgeIds: string[], id = "spliced"): RouteCandidate {
  return makeRouteCandidate({ id, edge_ids: edgeIds, distance_km: 12.3 });
}

let jobs: ReturnType<typeof serveGenerationJobs>;

/** 決着させるまで待つ評価。 */
function deferredEvaluation() {
  const job = heldReplies();
  jobs.answerWith(job.reply);
  return {
    resolve: (routes: RouteCandidate[]) =>
      job.answer(0, Response.json({ status: "done", result: { routes, conditions: CONDITIONS } })),
  };
}

function respond(routes: RouteCandidate[]) {
  jobs.respond(routes, CONDITIONS);
}

const failRequest = () => jobs.fail("リクエストに失敗しました");

/** 編集面の操作を押し、終わるまで待つ（編集面の型は戻り値を持たないが、実体は評価を待つ）。 */
async function press(action: (() => unknown) | undefined) {
  await act(async () => {
    await action?.();
  });
}

beforeEach(() => {
  jobs = serveGenerationJobs();
  serveAxisCatalog(CATALOG);
});

describe("入口", () => {
  it("目的地の生成で候補が2本以上あり、候補を選んでいて、区間を割る下限を引けるときだけ始められる", async () => {
    const rendered = renderSplice();
    await waitFor(() => expect(rendered.result.current.canStart).toBe(true));

    const blocked: Partial<Props>[] = [
      { generatedInput: { ...BASIS, destination: null } },
      { routes: [BASE] },
      { hasSelectedRoute: false },
    ];
    for (const props of blocked) {
      rendered.rerender({ ...PROPS, ...props });
      expect(rendered.result.current.canStart).toBe(false);
    }
  });

  it("区間を割る下限を引けない間は始められず、始めても乗り換え先を作らない（較正と別の切り方で出さない）", async () => {
    serveAxisCatalog(CATALOG_WITHOUT_MIN_STRETCH);
    const rendered = renderSplice();

    await startWithCatalog(rendered);

    expect(rendered.result.current.canStart).toBe(false);
    expect(rendered.result.current.editingRoute).toEqual(BASE);
    expect(rendered.result.current.map.spliceStretches).toEqual([]);
    expect(rendered.result.current.panel?.hasAlternatives).toBe(false);
  });
});

describe("編集", () => {
  it("始めると元の候補を編集面と地図へ渡し、他の候補が別の道を通る区間を乗り換え先として出す", async () => {
    const rendered = renderSplice();

    await startEditing(rendered);

    const { result } = rendered;
    expect(result.current.editingRoute).toEqual(BASE);
    expect(result.current.panel).toMatchObject({
      displayed: BASE,
      appliedCount: 0,
      hasAlternatives: true,
      preview: null,
    });
    expect(result.current.map.splicedRoute).toEqual([P0, P1, P2, P3]);
    expect(result.current.map.spliceStretches.map((stretch) => stretch.coordinates)).toEqual([[P1, Q, P2]]);
  });

  it("乗り換え先を選ぶとその道へ乗り換え、乗り換えた経路から次の乗り換え先を出す。1つ戻す・全部戻すで戻る", async () => {
    const rendered = renderSplice({ routes: [BASE, VIA_Q, VIA_Q_R] });
    await startEditing(rendered);
    const viaQ = rendered.result.current.map.spliceStretches.findIndex(
      (stretch) => JSON.stringify(stretch.coordinates) === JSON.stringify([P1, Q, P2]),
    );

    tapStretch(rendered, viaQ);
    expect(rendered.result.current.panel?.appliedCount).toBe(1);
    expect(rendered.result.current.map.splicedRoute).toEqual([P0, P1, Q, P2, P3]);
    expect(rendered.result.current.map.spliceStretches.map((stretch) => stretch.coordinates)).toEqual([[Q, R, P2]]);

    tapStretch(rendered);
    expect(rendered.result.current.panel?.appliedCount).toBe(2);
    expect(rendered.result.current.map.splicedRoute).toEqual([P0, P1, Q, R, P2, P3]);

    act(() => rendered.result.current.panel?.onUndo());
    expect(rendered.result.current.panel?.appliedCount).toBe(1);
    expect(rendered.result.current.map.splicedRoute).toEqual([P0, P1, Q, P2, P3]);

    act(() => rendered.result.current.panel?.onReset());
    expect(rendered.result.current.panel?.appliedCount).toBe(0);
    expect(rendered.result.current.map.splicedRoute).toEqual([P0, P1, P2, P3]);
  });

  it("地図から知らない乗り換え先が届いても何も変えない", async () => {
    const rendered = renderSplice();
    await startEditing(rendered);

    act(() => rendered.result.current.map.onSpliceStretchSelect(9999));

    expect(rendered.result.current.panel?.appliedCount).toBe(0);
  });

  it("線の形を持たない候補（Edge idだけ）では、地図に描けない乗り換え先を出さない", async () => {
    const edgesOnly = (route: RouteCandidate) =>
      makeRouteCandidate({ id: route.id, edge_ids: route.edge_ids, node_ids: route.node_ids });
    const rendered = renderSplice({ routes: [edgesOnly(BASE), edgesOnly(VIA_Q)] });

    await startWithCatalog(rendered);

    expect(rendered.result.current.canStart).toBe(true);
    expect(rendered.result.current.map.spliceStretches).toEqual([]);
  });

  it("やめると編集面も地図の乗り換え先も消え、次に始めた編集は空から始まる", async () => {
    const rendered = renderSplice();
    await startEditing(rendered);
    tapStretch(rendered);

    act(() => rendered.result.current.panel?.onCancel());
    expect(rendered.result.current.editingRoute).toBeNull();
    expect(rendered.result.current.panel).toBeNull();
    expect(rendered.result.current.map.spliceStretches).toEqual([]);
    expect(rendered.result.current.map.splicedRoute).toBeNull();

    act(() => rendered.result.current.start("base"));
    expect(rendered.result.current.panel?.appliedCount).toBe(0);
  });

  it("作り直すと（表示中の候補を作った生成が替わると）、候補のidが同じでも編集は終わる", async () => {
    const rendered = renderSplice();
    await startEditing(rendered);

    rendered.rerender({ ...PROPS, generatedInput: { ...BASIS } });

    expect(rendered.result.current.editingRoute).toBeNull();
  });

  it("編集の元の候補が一覧から消えたら、編集は効かない", async () => {
    const rendered = renderSplice();
    await startEditing(rendered);

    rendered.rerender({ ...PROPS, routes: [VIA_Q] });

    expect(rendered.result.current.editingRoute).toBeNull();
  });
});

describe("差分を見る", () => {
  it("表示中の候補を作った入力へ、乗り換えた経路のEdge列を載せて評価し、結果を編集面へ渡す。同じ組み合わせは投げ直さない", async () => {
    const rendered = renderSplice();
    await startEditing(rendered);
    tapStretch(rendered);
    const result = evaluated(["e1", "q1", "q2", "e3"]);
    respond([result]);

    await press(rendered.result.current.panel?.onPreview);

    expect(jobs.submitted).toHaveLength(1);
    expect(jobs.submitted[0].body).toMatchObject({
      latitude: BASIS.origin.latitude,
      longitude: BASIS.origin.longitude,
      max_routes: BASIS.maxRoutes,
      assumed_speed_kmh: BASIS.assumedSpeedKmh,
      route_preference: BASIS.routePreference,
      destination: { ...BASIS.destination },
      spliced_edge_ids: ["e1", "q1", "q2", "e3"],
    });
    expect(rendered.result.current.panel?.preview).toEqual(result);

    // 戻して選び直しても、覚えた評価を出して投げ直さない。
    act(() => rendered.result.current.panel?.onUndo());
    expect(rendered.result.current.panel?.preview).toBeNull();
    tapStretch(rendered);
    expect(rendered.result.current.panel?.preview).toEqual(result);
    await press(rendered.result.current.panel?.onPreview);
    expect(jobs.submitted).toHaveLength(1);
  });

  it("乗り換えていない間は評価しない", async () => {
    const rendered = renderSplice();
    await startEditing(rendered);

    await press(rendered.result.current.panel?.onPreview);

    expect(jobs.submitted).toEqual([]);
  });

  it("評価を待っている間は待っていると返し、選び直しても続ける。待っている間に押しても投げ直さない", async () => {
    const rendered = renderSplice({ routes: [BASE, VIA_Q, VIA_Q_R] });
    await startEditing(rendered);
    tapStretch(rendered);
    const pending = deferredEvaluation();
    let first: unknown;
    act(() => {
      first = rendered.result.current.panel?.onPreview();
    });
    expect(rendered.result.current.panel?.previewing).toBe(true);

    await press(rendered.result.current.panel?.onPreview);
    tapStretch(rendered);
    expect(rendered.result.current.panel?.previewing).toBe(true);
    expect(jobs.submitted).toHaveLength(1);

    await act(async () => {
      await pending.resolve([evaluated(["e1", "q1", "q2", "e3"])]);
      await first;
    });
    expect(rendered.result.current.panel?.previewing).toBe(false);
  });

  it.each([
    { label: "評価が空で返る", outcome: () => respond([]), message: "組み合わせたルートを評価できませんでした" },
    { label: "評価に失敗する", outcome: failRequest, message: "リクエストに失敗しました" },
  ])("「$label」と、理由を編集面に出す。次に乗り換え先を選ぶ・戻すと消す", async ({ outcome, message }) => {
    const rendered = renderSplice({ routes: [BASE, VIA_Q, VIA_Q_R] });
    await startEditing(rendered);
    tapStretch(rendered);

    for (const clear of [() => tapStretch(rendered), () => act(() => rendered.result.current.panel?.onUndo())]) {
      outcome();
      await press(rendered.result.current.panel?.onPreview);
      expect(rendered.result.current.panel?.error).toBe(message);
      expect(rendered.result.current.panel?.preview).toBeNull();

      clear();
      expect(rendered.result.current.panel?.error).toBeNull();
    }

    outcome();
    await press(rendered.result.current.panel?.onPreview);
    act(() => rendered.result.current.panel?.onReset());
    expect(rendered.result.current.panel?.error).toBeNull();
  });

  it("評価を待っている間に編集をやめたら、あとから届いた評価で編集へ戻さず、次の編集へも持ち込まない", async () => {
    const rendered = renderSplice();
    await startEditing(rendered);
    tapStretch(rendered);
    const pending = deferredEvaluation();
    let first: unknown;
    act(() => {
      first = rendered.result.current.panel?.onPreview();
    });

    act(() => rendered.result.current.panel?.onCancel());
    await act(async () => {
      await pending.resolve([evaluated(["e1", "q1", "q2", "e3"])]);
      await first;
    });
    expect(rendered.result.current.editingRoute).toBeNull();

    await startEditing(rendered);
    tapStretch(rendered);
    expect(rendered.result.current.panel?.preview).toBeNull();
    expect(rendered.result.current.panel?.previewing).toBe(false);
  });
});

describe("作成", () => {
  it("作る直前に知らせ、評価した経路を元の候補と一緒に渡して編集を終える", async () => {
    const rendered = renderSplice();
    await startEditing(rendered);
    tapStretch(rendered);
    const created = evaluated(["e1", "q1", "x", "e3"]);
    const pending = deferredEvaluation();
    let applying: unknown;
    act(() => {
      applying = rendered.result.current.panel?.onApply();
    });
    expect(rendered.onApplyStart).toHaveBeenCalledTimes(1);
    expect(rendered.onApplied).not.toHaveBeenCalled();
    expect(rendered.result.current.panel?.applying).toBe(true);

    await act(async () => {
      await pending.resolve([created]);
      await applying;
    });

    expect(rendered.onApplied).toHaveBeenCalledWith({ created, originId: "base" });
    expect(rendered.result.current.editingRoute).toBeNull();
  });

  it("作った経路が既にある候補と同じ道なら、作らずにその候補を渡す", async () => {
    const rendered = renderSplice();
    await startEditing(rendered);
    tapStretch(rendered);
    respond([evaluated(VIA_Q.edge_ids)]);

    await press(rendered.result.current.panel?.onApply);

    expect(rendered.onApplied).toHaveBeenCalledWith({ existingRouteId: "via-q" });
  });

  it("連打しても投げるのは1回で、渡すのも1回", async () => {
    const rendered = renderSplice();
    await startEditing(rendered);
    tapStretch(rendered);
    respond([evaluated(["e1", "q1", "x", "e3"])]);

    await act(async () => {
      const apply = rendered.result.current.panel?.onApply;
      await Promise.all([apply?.(), apply?.()]);
    });

    expect(jobs.submitted).toHaveLength(1);
    expect(rendered.onApplyStart).toHaveBeenCalledTimes(1);
    expect(rendered.onApplied).toHaveBeenCalledTimes(1);
  });

  it("乗り換えていない間は作らず、知らせもしない", async () => {
    const rendered = renderSplice();
    await startEditing(rendered);

    await press(rendered.result.current.panel?.onApply);

    expect(rendered.onApplyStart).not.toHaveBeenCalled();
    expect(jobs.submitted).toEqual([]);
  });

  it.each([
    { label: "評価が空で返る", outcome: () => respond([]), message: "組み合わせたルートを評価できませんでした" },
    { label: "評価に失敗する", outcome: failRequest, message: "リクエストに失敗しました" },
  ])("「$label」と、編集を続けたまま理由を出し、もう一度作れる", async ({ outcome, message }) => {
    const rendered = renderSplice();
    await startEditing(rendered);
    tapStretch(rendered);
    outcome();

    await press(rendered.result.current.panel?.onApply);

    expect(rendered.onApplied).not.toHaveBeenCalled();
    expect(rendered.result.current.panel?.error).toBe(message);
    expect(rendered.result.current.panel?.applying).toBe(false);

    respond([evaluated(["e1", "q1", "x", "e3"])]);
    await press(rendered.result.current.panel?.onApply);
    expect(rendered.onApplied).toHaveBeenCalledTimes(1);
  });
});
