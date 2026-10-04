/**
 * ルート生成（`useRouteGeneration.ts`）——押した「生成」を検証して、いまの条件からbackendへ要求を送り、実行中の進み方・
 * 直近の案内（候補0件の理由・失敗の文言・入力の誤り）・表示中の候補を作った条件といまの条件のずれ・研究モードの実験
 * スロットを返す。結果は所要時間の短い順に並べて渡し、押した1回の結果の種類（新しい結果か失敗か）を知らせる。
 *
 * ここで見ないもの:
 * - 検証の文言の中身と、目的地モードで地点が無いときの検証 → `RouteForm/useRouteFormSubmit.test.ts`
 * - 条件の値の持ち方（保存・地点の置き方・重みの揃え方） → `useGenerationConditions.test.ts`
 * - 入力から要求の形を組む細部（どの項目を比べないか・キーの並びに依らない比較） → `generationRequest.test.ts`
 * - 所要時間の並べ方の細部（時間の無い候補の位置） → `routeTabLabel.test.ts`
 * - 要求の投げ方と見回り（ジョブの問い合わせ・打ち切り） → `routeApi.test.ts`
 * - 結果を一覧へ入れる・知らせを画面に出す → `useRouteResults.test.ts`・`app/page.test.tsx`
 *
 * 差し替えたもの: 生成のジョブと軸カタログの応答（網の層）。条件は
 * 本物の`useGenerationConditions`を同じ描画で通して作る（呼び出し側と同じく、補正した目的地はそこへ書き戻る）。
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import { LENS_DIFFICULTY_ID, LENS_NONE_ID } from "@/lib/mapDisplay/routeStyleModes";
import { setResearchEnabled } from "@/lib/researchMode";
import { heldReplies, onBackend } from "@/testing/backendServer";
import { catalogEntry, catalogResponse } from "@/testing/catalogAxes";
import { serveGenerationJobs } from "@/testing/generationJobs";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import { EXPERIMENT_SLOT_COLORS, MAX_EXPERIMENT_SLOTS } from "@/types/experimentSlot";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { Coordinates, GenerationConditions, RouteCandidate } from "@/types/route";

import { useGenerationConditions } from "./useGenerationConditions";
import { useRouteGeneration } from "./useRouteGeneration";

const ORIGIN: Coordinates = { latitude: 35.68, longitude: 139.76 };
const A: Coordinates = { latitude: 35.7, longitude: 139.8 };
const B: Coordinates = { latitude: 35.71, longitude: 139.81 };
const T1 = new Date("2026-10-04T09:00:00Z");
const T2 = new Date("2026-10-04T09:05:00Z");
const NO_ROUTES_MESSAGE = "条件に合うルート候補が見つかりませんでした。条件を変えて試してください。";

const CATALOG = catalogResponse([
  catalogEntry({ axis_id: "axis_a", default_weight: 0.4 }),
  catalogEntry({ axis_id: "axis_b", default_weight: 0.6 }),
]);

interface Props {
  originKnown: boolean;
  departure: { at: Date; pinned: boolean };
  assumedSpeedKmh: number;
  hasRoutes: boolean;
}

const PROPS: Props = { originKnown: true, departure: { at: T1, pinned: false }, assumedSpeedKmh: 20, hasRoutes: true };

function renderGeneration(props: Partial<Props> = {}) {
  const onGenerated = vi.fn();
  const onOutcome = vi.fn();
  const rendered = renderHook(
    (p: Props) => {
      const conditions = useGenerationConditions({ onOriginPlace: () => {} });
      const generation = useRouteGeneration({ conditions, origin: ORIGIN, ...p, onGenerated, onOutcome });
      return { conditions, generation };
    },
    { initialProps: { ...PROPS, ...props } },
  );
  return { ...rendered, onGenerated, onOutcome };
}

type Rendered = ReturnType<typeof renderGeneration>;

async function submit({ result }: Rendered, lens: string = LENS_NONE_ID) {
  await act(() => result.current.generation.submit(lens));
}

function route(id: string, seconds: number | null = null): RouteCandidate {
  return makeRouteCandidate({ id, estimated_duration_seconds: seconds });
}

/** backendが返す生成の条件（`conditions`）。 */
function used(overrides: Partial<GenerationConditions> = {}): GenerationConditions {
  return {
    latitude: ORIGIN.latitude,
    longitude: ORIGIN.longitude,
    distance_km: 30,
    distance_tolerance_km: routeGenerateConfig.default_distance_tolerance_km,
    route_preference: { axis_a: 0.5, axis_b: 0.5 },
    penalty_strength: 1,
    max_average_grade_percent: null,
    hard_filters: DEFAULT_HARD_FILTERS,
    max_routes: routeGenerateConfig.default_max_routes,
    start_time: T1.toISOString(),
    assumed_speed_kmh: 20,
    waypoints: null,
    destination: null,
    corrected_destination: null,
    generated_at: "2026-10-04T09:00:30Z",
    ...overrides,
  };
}

let jobs: ReturnType<typeof serveGenerationJobs>;

function respond(routes: RouteCandidate[], conditions: GenerationConditions = used(), noCandidatesReason?: string) {
  jobs.respond(routes, conditions, noCandidatesReason);
}

function sentRequest() {
  return jobs.submitted.at(-1)?.body;
}

let catalog: ReturnType<typeof heldReplies>;

/** 描画のときに投げた軸カタログの取得を届ける。 */
async function loadCatalog(rendered: Rendered) {
  await act(() => catalog.answer(0, Response.json(CATALOG)));
  await waitFor(() => expect(rendered.result.current.conditions.routePreference).toEqual({ axis_a: 0.4, axis_b: 0.6 }));
}

beforeEach(() => {
  window.localStorage.clear();
  jobs = serveGenerationJobs();
  // 既定は届かないまま（カタログを見るテストだけが`loadCatalog`で届ける）。
  catalog = heldReplies();
  onBackend("GET", "/api/axis-catalog", catalog.reply);
});

afterEach(() => {
  setResearchEnabled(false);
  vi.useRealTimers();
});

describe("送る要求", () => {
  it("周回は、いまの位置・入力した距離と候補数・走行条件・除外を送り、置いてある地点・重み・塗る軸は送らない", async () => {
    const rendered = renderGeneration();
    const { conditions } = rendered.result.current;
    act(() => conditions.setDistanceInput("42"));
    act(() => rendered.result.current.conditions.setMaxRoutesInput("3"));
    act(() => rendered.result.current.conditions.setDestination(A));
    act(() => rendered.result.current.conditions.placePin("waypoint", B));
    respond([route("r1")]);

    await submit(rendered, "axis_a");

    expect(sentRequest()).toEqual({
      latitude: ORIGIN.latitude,
      longitude: ORIGIN.longitude,
      distance_km: 42,
      distance_tolerance_km: routeGenerateConfig.default_distance_tolerance_km,
      route_type: "loop",
      hard_filters: DEFAULT_HARD_FILTERS,
      max_routes: 3,
      assumed_speed_kmh: 20,
      start_time: T1.toISOString(),
    });
  });

  it("目的地は距離を送らず（探索の範囲はbackendが点から決める）、入力した候補数を送る", async () => {
    const rendered = renderGeneration();
    act(() => rendered.result.current.conditions.changeRouteMode("destination"));
    act(() => rendered.result.current.conditions.setMaxRoutesInput("4"));
    act(() => rendered.result.current.conditions.placePin("destination", A));
    respond([route("r1")]);

    await submit(rendered);

    expect(sentRequest()).not.toHaveProperty("distance_km");
    expect(sentRequest()).toMatchObject({ max_routes: 4, destination: A });
    expect(sentRequest()).not.toHaveProperty("waypoints");
  });

  it("経由地があると、候補数の入力に関わらず決まった数を送り、経由地は置いた順に送る。目的地が無ければ経由地だけを送る", async () => {
    const rendered = renderGeneration();
    act(() => rendered.result.current.conditions.changeRouteMode("destination"));
    act(() => rendered.result.current.conditions.setMaxRoutesInput("4"));
    act(() => rendered.result.current.conditions.placePin("waypoint", B));
    act(() => rendered.result.current.conditions.placePin("waypoint", A));
    respond([route("r1")]);

    await submit(rendered);

    expect(sentRequest()).toMatchObject({ max_routes: routeGenerateConfig.routes_with_waypoints, waypoints: [B, A] });
    expect(sentRequest()).not.toHaveProperty("destination");
    expect(sentRequest()).not.toHaveProperty("distance_km");
  });

  it("塗る軸は、軸カタログが届いていてレンズが軸を指すときだけ送る", async () => {
    const rendered = renderGeneration();
    respond([route("r1")]);
    await submit(rendered, "axis_a");
    expect(sentRequest()).not.toHaveProperty("lens_axis_id");

    await loadCatalog(rendered);
    for (const lens of [LENS_NONE_ID, LENS_DIFFICULTY_ID]) {
      respond([route("r1")]);
      await submit(rendered, lens);
      expect(sentRequest()).not.toHaveProperty("lens_axis_id");
    }

    respond([route("r1")]);
    await submit(rendered, "axis_a");
    expect(sentRequest()).toMatchObject({ lens_axis_id: "axis_a" });
  });

  it("重みは上書きを有効にし、軸カタログが届いた後だけ送る", async () => {
    const rendered = renderGeneration();
    await loadCatalog(rendered);
    respond([route("r1")]);
    await submit(rendered);
    expect(sentRequest()).not.toHaveProperty("route_preference");

    act(() => rendered.result.current.conditions.setWeightOverrideEnabled(true));
    respond([route("r1")]);
    await submit(rendered);

    expect(sentRequest()).toMatchObject({ route_preference: { axis_a: 0.4, axis_b: 0.6 } });
  });
});

describe("入力の誤り", () => {
  it("出発地が仮の地点のままなら送らず、理由を案内に出して、押すたびに失敗として知らせる", async () => {
    const rendered = renderGeneration({ originKnown: false });

    await submit(rendered);
    await submit(rendered);

    const { generation } = rendered.result.current;
    expect(jobs.submitted).toEqual([]);
    expect(generation.inputError).toMatch(/現在地が分かりません/);
    expect(generation.failure).toBe(generation.inputError);
    expect(generation.lastMessage).toBe(generation.inputError);
    expect(rendered.onOutcome.mock.calls).toEqual([["failed"], ["failed"]]);
  });

  it("入力の誤りは、直前の生成の失敗の文言より先に出す", async () => {
    const rendered = renderGeneration();
    jobs.fail("リクエストに失敗しました");
    await submit(rendered);

    rendered.rerender({ ...PROPS, originKnown: false });
    await submit(rendered);

    expect(rendered.result.current.generation.failure).toMatch(/現在地が分かりません/);
    expect(rendered.result.current.generation.lastMessage).toMatch(/現在地が分かりません/);
  });
});

describe("進み方", () => {
  it("実行中は進み方を文言で返し、順番待ちかを見分けられる。終わると実行中でなくなる", async () => {
    // 問い合わせの間隔と経過時間は時計で進める。
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
    const rendered = renderGeneration();
    const job = heldReplies();
    jobs.answerWith(job.reply);
    const flush = () => act(() => vi.advanceTimersByTimeAsync(0));
    let done: Promise<void> = Promise.resolve();
    act(() => {
      done = rendered.result.current.generation.submit(LENS_NONE_ID);
    });
    expect(rendered.result.current.generation.running).toBe(true);
    expect(rendered.result.current.generation.progressLabel).toBeUndefined();

    await job.answer(0, Response.json({ status: "queued" }));
    await flush();
    expect(rendered.result.current.generation.progressLabel).toBe("順番待ち...");
    expect(rendered.result.current.generation.queued).toBe(true);

    await act(() => vi.advanceTimersByTimeAsync(2600));
    await job.answer(1, Response.json({ status: "running" }));
    await flush();
    expect(rendered.result.current.generation.progressLabel).toBe("生成中...(3秒経過)");
    expect(rendered.result.current.generation.queued).toBe(false);

    await act(() => vi.advanceTimersByTimeAsync(1500));
    await job.answer(
      2,
      Response.json({
        status: "done",
        result: { routes: [route("r1")], conditions: used(), no_candidates_reason: null },
      }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
      await done;
    });
    expect(rendered.result.current.generation.running).toBe(false);
    expect(rendered.result.current.generation.progressLabel).toBeUndefined();
  });
});

describe("生成の結果", () => {
  it("候補を所要時間の短い順に並べ、生成に使われた重みと一緒に渡して新しい結果として知らせる。案内は出さない", async () => {
    const rendered = renderGeneration();
    respond([route("slow", 3600), route("fast", 1800)], used({ route_preference: { axis_a: 1 } }));

    await submit(rendered);

    expect(rendered.onGenerated).toHaveBeenCalledWith([route("fast", 1800), route("slow", 3600)], { axis_a: 1 });
    expect(rendered.onOutcome).toHaveBeenCalledWith("fresh");
    expect(rendered.result.current.generation.failure).toBeNull();
    expect(rendered.result.current.generation.lastMessage).toBeUndefined();
  });

  it.each([
    {
      label: "理由が届いたらその理由",
      reason: "目的地へ行ける道が見つかりませんでした",
      message: "目的地へ行ける道が見つかりませんでした",
    },
    { label: "理由が届かなければ決まった文言", reason: undefined, message: NO_ROUTES_MESSAGE },
  ])("候補0件は、「$label」を案内に出して新しい結果として知らせ、失敗とは扱わない", async ({ reason, message }) => {
    const rendered = renderGeneration();
    respond([], used(), reason);

    await submit(rendered);

    expect(rendered.onGenerated).toHaveBeenCalledWith([], used().route_preference);
    expect(rendered.onOutcome).toHaveBeenCalledWith("fresh");
    expect(rendered.result.current.generation.lastMessage).toBe(message);
    expect(rendered.result.current.generation.failure).toBeNull();
  });

  it("生成が失敗したら文言を失敗として返して知らせ、結果は渡さない。次の生成で消す", async () => {
    const message = "ルート生成がタイムアウトしました";
    const rendered = renderGeneration();
    jobs.fail(message);

    await submit(rendered);

    expect(rendered.result.current.generation.failure).toBe(message);
    expect(rendered.result.current.generation.lastMessage).toBe(message);
    expect(rendered.onOutcome).toHaveBeenCalledWith("failed");
    expect(rendered.onGenerated).not.toHaveBeenCalled();

    jobs.keepRunning();
    act(() => {
      void rendered.result.current.generation.submit(LENS_NONE_ID);
    });
    expect(rendered.result.current.generation.failure).toBeNull();
  });

  it("backendが目的地を補正したら、置いた目的地を補正後の地点へ動かして知らせ、条件が変わったとは扱わない", async () => {
    const rendered = renderGeneration();
    act(() => rendered.result.current.conditions.changeRouteMode("destination"));
    act(() => rendered.result.current.conditions.placePin("destination", A));
    respond([route("r1")], used({ destination: A, corrected_destination: B }));

    await submit(rendered);

    const { conditions, generation } = rendered.result.current;
    expect(conditions.destination).toEqual(B);
    expect(generation.destinationCorrected).toBe(true);
    expect(generation.conditionsDirty).toBe(false);
    expect(generation.generatedInput?.destination).toEqual(B);
  });

  it("目的地を補正しなかった生成は、補正したと返さない", async () => {
    const rendered = renderGeneration();
    respond([route("r1")]);

    await submit(rendered);

    expect(rendered.result.current.generation.destinationCorrected).toBe(false);
  });

  it("重みを上書きしていたのに軸カタログが無く送れなかったときだけ、既定の配分で作ったと返す", async () => {
    const rendered = renderGeneration();
    respond([route("r1")]);
    await submit(rendered);
    expect(rendered.result.current.generation.weightsNotApplied).toBe(false);

    act(() => rendered.result.current.conditions.setWeightOverrideEnabled(true));
    respond([route("r1")]);
    await submit(rendered);
    expect(rendered.result.current.generation.weightsNotApplied).toBe(true);

    await loadCatalog(rendered);
    respond([route("r1")]);
    await submit(rendered);
    expect(rendered.result.current.generation.weightsNotApplied).toBe(false);
  });

  it("作った入力（塗る軸を含む）を返す。生成する前は無い", async () => {
    const rendered = renderGeneration();
    expect(rendered.result.current.generation.generatedInput).toBeNull();
    await loadCatalog(rendered);
    respond([route("r1")]);

    await submit(rendered, "axis_a");

    expect(rendered.result.current.generation.generatedInput).toMatchObject({
      origin: ORIGIN,
      distanceKm: 30,
      lensAxisId: "axis_a",
      startTime: T1,
    });
  });
});

describe("条件のずれ", () => {
  it("作った後に条件を変えると、候補がある間だけずれていると返し、作り直すと消える", async () => {
    const rendered = renderGeneration();
    expect(rendered.result.current.generation.conditionsDirty).toBe(false);
    respond([route("r1")]);
    await submit(rendered);
    expect(rendered.result.current.generation.conditionsDirty).toBe(false);

    act(() => rendered.result.current.conditions.setDistanceInput("50"));
    expect(rendered.result.current.generation.conditionsDirty).toBe(true);

    rendered.rerender({ ...PROPS, hasRoutes: false });
    expect(rendered.result.current.generation.conditionsDirty).toBe(false);

    rendered.rerender(PROPS);
    respond([route("r1")]);
    await submit(rendered);
    expect(rendered.result.current.generation.conditionsDirty).toBe(false);
  });

  it("出発時刻は選んだときだけ比べ（「今」への追従では変わったとしない）、塗る軸は比べない", async () => {
    const rendered = renderGeneration();
    await loadCatalog(rendered);
    respond([route("r1")]);
    await submit(rendered, "axis_a");
    expect(rendered.result.current.generation.conditionsDirty).toBe(false);

    rendered.rerender({ ...PROPS, departure: { at: T2, pinned: false } });
    expect(rendered.result.current.generation.conditionsDirty).toBe(false);

    respond([route("r1")]);
    rendered.rerender({ ...PROPS, departure: { at: T1, pinned: true } });
    await submit(rendered);
    rendered.rerender({ ...PROPS, departure: { at: T2, pinned: true } });
    expect(rendered.result.current.generation.conditionsDirty).toBe(true);
  });
});

describe("実験スロット", () => {
  it("研究モードでなければ残さない", async () => {
    const rendered = renderGeneration();
    respond([route("r1")]);

    await submit(rendered);

    expect(rendered.result.current.generation.experimentSlots).toEqual([]);
  });

  it("研究モードの生成を新しい順に上限まで残し、代表はbackendの並びの先頭、色は並びの位置で決める。候補0件は残さない", async () => {
    setResearchEnabled(true);
    const rendered = renderGeneration();
    const runs = Array.from({ length: MAX_EXPERIMENT_SLOTS + 1 }, (_, i) => ({
      conditions: used({ generated_at: `2026-10-04T09:0${i}:00Z` }),
      // backendの並び（難易度の低い順）の先頭を、所要時間では後ろになる候補にする。
      top: route(`top-${i}`, 3600),
    }));
    for (const run of runs) {
      respond([run.top, route("fast", 1800)], run.conditions);
      await submit(rendered);
    }
    respond([], used());
    await submit(rendered);

    const slots = rendered.result.current.generation.experimentSlots;
    expect(slots.map((slot) => slot.topCandidate.id)).toEqual(
      runs
        .slice(-MAX_EXPERIMENT_SLOTS)
        .reverse()
        .map((run) => run.top.id),
    );
    expect(slots[0].conditions).toEqual(runs.at(-1)?.conditions);
    expect(slots.map((slot) => slot.color)).toEqual(EXPERIMENT_SLOT_COLORS.slice(0, MAX_EXPERIMENT_SLOTS));
    expect(new Set(slots.map((slot) => slot.id)).size).toBe(MAX_EXPERIMENT_SLOTS);
  });
});

describe("消す", () => {
  it("案内を消す。実行中は何もしない", async () => {
    const rendered = renderGeneration();
    jobs.fail("リクエストに失敗しました");
    await submit(rendered);

    act(() => rendered.result.current.generation.clearNotice());
    expect(rendered.result.current.generation.failure).toBeNull();
    expect(rendered.result.current.generation.lastMessage).toBeUndefined();

    jobs.keepRunning();
    act(() => {
      void rendered.result.current.generation.submit(LENS_NONE_ID);
    });
    act(() => rendered.result.current.generation.clearNotice());
    expect(rendered.result.current.generation.running).toBe(true);
  });

  it("生成の結果（作った条件・ずれ・補正・既定の配分・実験スロット・案内）を消す", async () => {
    setResearchEnabled(true);
    const rendered = renderGeneration();
    act(() => rendered.result.current.conditions.setWeightOverrideEnabled(true));
    act(() => rendered.result.current.conditions.changeRouteMode("destination"));
    act(() => rendered.result.current.conditions.placePin("destination", A));
    respond([route("r1")], used({ corrected_destination: B }));
    await submit(rendered);
    jobs.fail("リクエストに失敗しました");
    act(() => rendered.result.current.conditions.setMaxRoutesInput("2"));
    await submit(rendered);

    act(() => rendered.result.current.generation.clear());

    const { generation } = rendered.result.current;
    expect(generation.generatedInput).toBeNull();
    expect(generation.conditionsDirty).toBe(false);
    expect(generation.destinationCorrected).toBe(false);
    expect(generation.weightsNotApplied).toBe(false);
    expect(generation.experimentSlots).toEqual([]);
    expect(generation.failure).toBeNull();
  });
});
