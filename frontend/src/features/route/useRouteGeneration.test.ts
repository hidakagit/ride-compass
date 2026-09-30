/**
 * ルート生成（`useRouteGeneration`）——いまの条件から入力を組み立てて送り、進み方・直近の案内・条件のずれ・実験スロットを返す。
 * 生成の条件は本物の`useGenerationConditions`を通して与える（入力の持ち主はそちらで、ここは読むだけ）。
 *
 * ここで見ないもの:
 * - 入力からpayloadと比較キーを作る規則そのもの → `generationRequest.ts`
 * - 入力の検証の文言 → `RouteForm/useRouteFormSubmit.ts`
 * - 生成のジョブの通信・ポーリング・失敗の文言 → `routeApi.ts`
 * - 所要時間の並べ方 → `routeTabLabel.ts`
 *
 * 差し替えた部品: 生成の通信（`routeApi.generateRoutes`）は返す値をテストが決める。軸カタログ（`useAxisCatalog`）も同じ。
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { axisCatalogFromResponse, EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";
import { catalogEntry } from "@/lib/mapDisplay/__fixtures__/catalogAxes";
import { LENS_DIFFICULTY_ID, LENS_NONE_ID } from "@/lib/mapDisplay/routeStyleModes";
import { setResearchEnabled } from "@/lib/researchMode";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import { EXPERIMENT_SLOT_COLORS, MAX_EXPERIMENT_SLOTS } from "@/types/experimentSlot";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { Coordinates, GenerationConditions, RouteCandidate } from "@/types/route";

const catalog = vi.hoisted(() => ({ current: undefined as unknown }));
vi.mock("@/hooks/useAxisCatalog", () => ({ useAxisCatalog: () => catalog.current }));
vi.mock("@/features/route/routeApi", () => ({ generateRoutes: vi.fn() }));

import { generateRoutes, type GenerationProgress } from "@/features/route/routeApi";
import { useGenerationConditions } from "./useGenerationConditions";
import { useRouteGeneration } from "./useRouteGeneration";

const HERE: Coordinates = { latitude: 35, longitude: 139 };
const NEAR: Coordinates = { latitude: 35.1, longitude: 139 };
const CORRECTED: Coordinates = { latitude: 35.1001, longitude: 139.0005 };
const AT = new Date("2026-09-25T03:00:00Z");
const LATER = new Date("2026-09-25T03:05:00Z");
const CATALOG: AxisCatalog = axisCatalogFromResponse(
  [catalogEntry({ axis_id: "axis_a", default_weight: 1 })],
  {},
  {},
  [],
);

interface Props {
  originKnown: boolean;
  departure: { at: Date; pinned: boolean };
  assumedSpeedKmh: number;
  lens: string;
  hasRoutes: boolean;
}
const PROPS: Props = {
  originKnown: true,
  departure: { at: AT, pinned: false },
  assumedSpeedKmh: 18,
  lens: LENS_DIFFICULTY_ID,
  hasRoutes: false,
};

const onGenerated = vi.fn();
const onOutcome = vi.fn();

function render(props: Partial<Props> = {}) {
  return renderHook(
    (current: Props) => {
      const conditions = useGenerationConditions({ onOriginPlace: () => {} });
      const generation = useRouteGeneration({ conditions, origin: HERE, ...current, onGenerated, onOutcome });
      return { conditions, generation };
    },
    { initialProps: { ...PROPS, ...props } },
  );
}
type Rendered = ReturnType<typeof render>;

function conditionsOf(overrides: Partial<GenerationConditions> = {}): GenerationConditions {
  return {
    latitude: 0,
    longitude: 0,
    distance_km: 0,
    distance_tolerance_km: 0,
    route_preference: {},
    penalty_strength: 0,
    max_average_grade_percent: null,
    hard_filters: {},
    max_routes: 0,
    start_time: "",
    assumed_speed_kmh: 0,
    waypoints: null,
    destination: null,
    corrected_destination: null,
    generated_at: "",
    ...overrides,
  };
}
function respond(routes: RouteCandidate[], conditions: Partial<GenerationConditions> = {}, reason?: string) {
  vi.mocked(generateRoutes).mockResolvedValueOnce({
    routes,
    conditions: conditionsOf(conditions),
    noCandidatesReason: reason,
  });
}
const route = (id: string, seconds: number | null = null) =>
  makeRouteCandidate({ id, estimated_duration_seconds: seconds });

async function submit(hook: Rendered) {
  await act(async () => hook.result.current.generation.submit());
}
function lastRequest() {
  const call = vi.mocked(generateRoutes).mock.lastCall;
  if (!call) throw new Error("生成を呼んでいない");
  return call[0];
}

beforeEach(() => {
  localStorage.clear();
  catalog.current = CATALOG;
  vi.mocked(generateRoutes).mockReset();
  onGenerated.mockReset();
  onOutcome.mockReset();
  setResearchEnabled(false);
});
afterEach(() => setResearchEnabled(false));

describe("送る入力", () => {
  it("周回は、いまの位置・入力した距離と候補数・走行条件・除外を送り、地点・重み・塗る軸は送らない", async () => {
    const hook = render();
    act(() => hook.result.current.conditions.setDistanceInput("42"));
    act(() => hook.result.current.conditions.setMaxRoutesInput("4"));
    respond([route("r")]);
    await submit(hook);
    expect(lastRequest()).toEqual({
      latitude: HERE.latitude,
      longitude: HERE.longitude,
      distance_km: 42,
      distance_tolerance_km: routeGenerateConfig.default_distance_tolerance_km,
      route_type: "loop",
      hard_filters: DEFAULT_HARD_FILTERS,
      max_routes: 4,
      assumed_speed_kmh: PROPS.assumedSpeedKmh,
      start_time: AT.toISOString(),
    });
  });

  it("周回の間は、置いてある経由地・目的地を送らない", async () => {
    const hook = render();
    act(() => hook.result.current.conditions.placePin("waypoint", NEAR));
    act(() => hook.result.current.conditions.placePin("destination", NEAR));
    respond([route("r")]);
    await submit(hook);
    expect(lastRequest()).not.toHaveProperty("waypoints");
    expect(lastRequest()).not.toHaveProperty("destination");
    expect(lastRequest()).toHaveProperty("distance_km", 30);
  });

  it("目的地は距離を送らず（探索の範囲はbackendが点から決める）、入力した候補数を送る", async () => {
    const hook = render();
    act(() => hook.result.current.conditions.changeRouteMode("destination"));
    act(() => hook.result.current.conditions.placePin("destination", NEAR));
    act(() => hook.result.current.conditions.setMaxRoutesInput("5"));
    respond([route("r")]);
    await submit(hook);
    expect(lastRequest()).not.toHaveProperty("distance_km");
    expect(lastRequest()).toMatchObject({ destination: NEAR, max_routes: 5 });
    expect(lastRequest()).not.toHaveProperty("waypoints");
  });

  it("経由地があると、候補数の入力に関わらず決まった数を送る（経由地は置いた順）", async () => {
    const hook = render();
    act(() => hook.result.current.conditions.changeRouteMode("destination"));
    act(() => hook.result.current.conditions.placePin("waypoint", NEAR));
    act(() => hook.result.current.conditions.placePin("waypoint", HERE));
    respond([route("r")]);
    await submit(hook);
    expect(lastRequest()).toMatchObject({
      waypoints: [NEAR, HERE],
      max_routes: routeGenerateConfig.routes_with_waypoints,
    });
    expect(lastRequest()).not.toHaveProperty("distance_km");
    expect(lastRequest()).not.toHaveProperty("destination");
  });

  it("レンズが軸を指し、軸カタログが届いているときだけ塗る軸を送る", async () => {
    const hook = render({ lens: "axis_a" });
    respond([route("r")]);
    await submit(hook);
    expect(lastRequest()).toHaveProperty("lens_axis_id", "axis_a");

    for (const lens of [LENS_NONE_ID, LENS_DIFFICULTY_ID]) {
      hook.rerender({ ...PROPS, lens });
      respond([route("r")]);
      await submit(hook);
      expect(lastRequest()).not.toHaveProperty("lens_axis_id");
    }

    catalog.current = EMPTY_CATALOG;
    hook.rerender({ ...PROPS, lens: "axis_a" });
    respond([route("r")]);
    await submit(hook);
    expect(lastRequest()).not.toHaveProperty("lens_axis_id");
  });

  it("重みは上書きを有効にした後だけ送る", async () => {
    const hook = render();
    act(() => hook.result.current.conditions.setWeightOverrideEnabled(true));
    respond([route("r")]);
    await submit(hook);
    expect(lastRequest()).toHaveProperty("route_preference", { axis_a: 1 });
  });
});

describe("入力の誤り", () => {
  it("出発地が仮の地点のままなら生成せず、理由を案内に出して失敗として知らせる", async () => {
    const hook = render({ originKnown: false });
    await submit(hook);
    expect(generateRoutes).not.toHaveBeenCalled();
    expect(hook.result.current.generation.failure).toContain("現在地が分かりません");
    expect(hook.result.current.generation.lastMessage).toBe(hook.result.current.generation.failure);
    expect(onOutcome).toHaveBeenCalledWith("failed");
  });

  it("入力の誤りは直前の生成の案内より先に出す", async () => {
    const hook = render();
    respond([], {}, "直前の理由");
    await submit(hook);
    act(() => hook.result.current.conditions.changeRouteMode("destination"));
    await submit(hook);
    expect(hook.result.current.generation.lastMessage).toContain("目的地か経由地");
  });
});

describe("進み方", () => {
  it("実行中は進み方を文言で返し、順番待ちかを見分けられる。終わると実行中でなくなる", async () => {
    let report: ((progress: GenerationProgress) => void) | undefined;
    let resolve!: (value: Awaited<ReturnType<typeof generateRoutes>>) => void;
    vi.mocked(generateRoutes).mockImplementationOnce((_request, onProgress) => {
      report = onProgress;
      return new Promise((done) => (resolve = done));
    });
    const hook = render();
    act(() => hook.result.current.generation.submit());
    expect(hook.result.current.generation.running).toBe(true);
    expect(hook.result.current.generation.progressLabel).toBeUndefined();

    act(() => report?.({ status: "queued", elapsedMs: 0 }));
    expect(hook.result.current.generation.queued).toBe(true);
    expect(hook.result.current.generation.progressLabel).toBe("順番待ち...");
    act(() => report?.({ status: "running", elapsedMs: 1500 }));
    expect(hook.result.current.generation.queued).toBe(false);
    expect(hook.result.current.generation.progressLabel).toBe("生成中...(2秒経過)");

    await act(async () => resolve({ routes: [route("r")], conditions: conditionsOf() }));
    expect(hook.result.current.generation.running).toBe(false);
  });
});

describe("生成の結果", () => {
  it("候補を所要時間の短い順に並べ、生成に使われた重みと一緒に渡す。候補があれば案内も失敗の知らせも出さない", async () => {
    const hook = render();
    respond([route("slow", 900), route("fast", 600), route("none")], { route_preference: { axis_a: 0.5 } });
    await submit(hook);
    expect(onGenerated).toHaveBeenCalledWith({
      routes: [route("fast", 600), route("slow", 900), route("none")],
      routePreference: { axis_a: 0.5 },
    });
    expect(onOutcome).not.toHaveBeenCalled();
    expect(hook.result.current.generation.lastMessage).toBeUndefined();
    expect(hook.result.current.generation.failure).toBeNull();
  });

  it.each([
    ["届いた", "対象の道が見つかりません", "対象の道が見つかりません"],
    ["届かない", undefined, "条件に合うルート候補が見つかりませんでした。距離を変えて試してください。"],
  ])(
    "候補0件は、理由が%sときその理由を案内に出して新しい結果として知らせ、失敗とは扱わない",
    async (_c, reason, shown) => {
      const hook = render();
      respond([], {}, reason);
      await submit(hook);
      expect(onGenerated).toHaveBeenCalledWith({ routes: [], routePreference: {} });
      expect(onOutcome).toHaveBeenCalledWith("fresh");
      expect(hook.result.current.generation.lastMessage).toBe(shown);
      expect(hook.result.current.generation.failure).toBeNull();
    },
  );

  it.each([
    ["Error", new Error("混み合っています"), "混み合っています"],
    ["Error以外", "壊れた応答", "不明なエラーが発生しました"],
  ])("生成が%sで失敗したら失敗として返して知らせ、次の生成で消す", async (_c, thrown, shown) => {
    const hook = render();
    vi.mocked(generateRoutes).mockRejectedValueOnce(thrown);
    await submit(hook);
    expect(hook.result.current.generation.failure).toBe(shown);
    expect(onOutcome).toHaveBeenCalledWith("failed");
    expect(onGenerated).not.toHaveBeenCalled();

    respond([route("r")]);
    await submit(hook);
    expect(hook.result.current.generation.failure).toBeNull();
  });

  it("backendが目的地を補正したら、置いた目的地を補正後の地点へ動かして知らせ、条件が変わったとは扱わない", async () => {
    const hook = render({ hasRoutes: true });
    act(() => hook.result.current.conditions.changeRouteMode("destination"));
    act(() => hook.result.current.conditions.placePin("destination", NEAR));
    respond([route("r")], { corrected_destination: CORRECTED });
    await submit(hook);
    expect(hook.result.current.conditions.destination).toEqual(CORRECTED);
    expect(hook.result.current.generation.destinationCorrected).toBe(true);
    expect(hook.result.current.generation.conditionsDirty).toBe(false);
    expect(hook.result.current.generation.generatedInput?.destination).toEqual(CORRECTED);
  });

  it("重みを上書きしていたのに軸カタログが無く送れなかったときだけ、既定の配分で作ったと返す", async () => {
    catalog.current = EMPTY_CATALOG;
    const hook = render();
    respond([route("r")]);
    await submit(hook);
    expect(hook.result.current.generation.weightsNotApplied).toBe(false);

    act(() => hook.result.current.conditions.setWeightOverrideEnabled(true));
    respond([route("r")]);
    await submit(hook);
    expect(hook.result.current.generation.weightsNotApplied).toBe(true);
  });

  it("作った入力（塗る軸を含む）を、乗り換えの評価に使えるよう返す", async () => {
    const hook = render({ lens: "axis_a" });
    expect(hook.result.current.generation.generatedInput).toBeNull();
    respond([route("r")]);
    await submit(hook);
    expect(hook.result.current.generation.generatedInput).toMatchObject({ lensAxisId: "axis_a", origin: HERE });
  });
});

describe("条件のずれ", () => {
  it("作った後に条件を変えると、候補がある間だけずれていると返し、作り直すと消える", async () => {
    const hook = render({ hasRoutes: true });
    expect(hook.result.current.generation.conditionsDirty).toBe(false);
    respond([route("r")]);
    await submit(hook);
    act(() => hook.result.current.conditions.setDistanceInput("45"));
    expect(hook.result.current.generation.conditionsDirty).toBe(true);

    hook.rerender({ ...PROPS, hasRoutes: false });
    expect(hook.result.current.generation.conditionsDirty).toBe(false);

    hook.rerender({ ...PROPS, hasRoutes: true });
    respond([route("r")]);
    await submit(hook);
    expect(hook.result.current.generation.conditionsDirty).toBe(false);
  });

  it("出発時刻は選んだときだけ比べ（「今」への追従では変わったとしない）、塗る軸は比べない", async () => {
    const hook = render({ hasRoutes: true });
    respond([route("r")]);
    await submit(hook);
    hook.rerender({ ...PROPS, hasRoutes: true, departure: { at: LATER, pinned: false }, lens: "axis_a" });
    expect(hook.result.current.generation.conditionsDirty).toBe(false);
    hook.rerender({ ...PROPS, hasRoutes: true, departure: { at: LATER, pinned: true } });
    expect(hook.result.current.generation.conditionsDirty).toBe(true);
  });
});

describe("実験スロット", () => {
  it("研究モードの生成だけを新しい順に残し、上限で切って並びの位置で色を振り直す。代表はbackendの並びの先頭", async () => {
    const hook = render();
    respond([route("off")]);
    await submit(hook);
    expect(hook.result.current.generation.experimentSlots).toEqual([]);

    setResearchEnabled(true);
    hook.rerender({ ...PROPS });
    for (let i = 0; i < MAX_EXPERIMENT_SLOTS + 1; i++) {
      respond([route(`easy-${i}`, 900), route(`fast-${i}`, 60)], { generated_at: `g${i}` });
      await submit(hook);
    }
    const slots = hook.result.current.generation.experimentSlots;
    expect(slots.map((slot) => slot.conditions.generated_at)).toEqual(
      Array.from({ length: MAX_EXPERIMENT_SLOTS }, (_, i) => `g${MAX_EXPERIMENT_SLOTS - i}`),
    );
    expect(slots.map((slot) => slot.color)).toEqual(
      slots.map((_, i) => EXPERIMENT_SLOT_COLORS[i % EXPERIMENT_SLOT_COLORS.length]),
    );
    expect(slots[0].topCandidate.id).toBe(`easy-${MAX_EXPERIMENT_SLOTS}`);
  });

  it("候補0件の生成は残さない", async () => {
    setResearchEnabled(true);
    const hook = render();
    respond([]);
    await submit(hook);
    expect(hook.result.current.generation.experimentSlots).toEqual([]);
  });
});

describe("消す", () => {
  it("作った条件・実験スロット・失敗の案内を消す（条件のずれも作った入力も無くなる）", async () => {
    setResearchEnabled(true);
    const hook = render({ hasRoutes: true });
    respond([route("r")]);
    await submit(hook);
    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混み合っています"));
    await submit(hook);
    act(() => hook.result.current.conditions.setDistanceInput("45"));

    act(() => hook.result.current.generation.clear());
    expect(hook.result.current.generation.generatedInput).toBeNull();
    expect(hook.result.current.generation.experimentSlots).toEqual([]);
    expect(hook.result.current.generation.failure).toBeNull();
    expect(hook.result.current.generation.conditionsDirty).toBe(false);
  });

  it("案内だけを消すのは、実行中でないときだけ（実行中の進み方は残す）", async () => {
    const hook = render();
    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混み合っています"));
    await submit(hook);
    act(() => hook.result.current.generation.clearNotice());
    expect(hook.result.current.generation.failure).toBeNull();

    vi.mocked(generateRoutes).mockImplementationOnce(() => new Promise(() => {}));
    act(() => hook.result.current.generation.submit());
    act(() => hook.result.current.generation.clearNotice());
    expect(hook.result.current.generation.running).toBe(true);
  });
});
