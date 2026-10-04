/**
 * `features/route/RouteOutcome/RouteOutcome.tsx`——「ルート結果」の中身。
 *
 * 見るもの:
 * - 候補が無い間の案内（生成中の進み方・直近の案内・生成前）と、候補がある間の作り直しの失敗・条件のずれ・
 *   既定の配分で作ったこと・目的地の補正の知らせ（作り直しの失敗を出している間は条件のずれを重ねない）
 * - 候補の一覧: 見出しを分けるのは経由地の無い目的地ルートの生成と編集で作ったルートがあるときで、行に出す名前・
 *   距離・最速の印と所要時間・ほかの候補の余計にかかる時間・総合難易度（無ければ「—」）と負荷の帯の高さ、選ばれて
 *   いるタブ（選んだ候補・無ければ先頭・比較を見ている間は比較）と、タブを押したときに上がる操作
 * - 選んだ候補の中身: 合成（始められるときだけ）・GPXの操作、編集で作ったルートの「元との違い」へ渡す元と名前、
 *   道のりのグラフへ渡す値（区間がある候補だけ）、区間を押している間の地点・到達予想・解除・区間の風と内訳
 *   （チップから開く軸の詳細を含む）と研究モードの材料の値、押していない間の内訳へ渡す値、編集中は編集面だけを出すこと
 * - 研究モードの比較タブと、比較表へ渡す軸（どれかの回で重みが0より大きかった軸）
 *
 * ここで見ないもの: 一覧の見出し・名前・最速の決め方 → `features/route/routeTabLabel.ts`。帯の高さの求め方 →
 * `features/route/difficultyLoadBar.ts`。結果の状態の移り変わり → `features/route/useRouteResults.ts`。
 *
 * 差し替えたもの: 子の部品（比較表・道のりのグラフ・内訳・寄与の帯・元との違い・区間の風・編集面）は受け取った値と
 * 上げる操作だけを見る（表示は各部品のテストが見る）。軸カタログの通信（`services/axisCatalogApi.ts: getAxisCatalog`）と
 * GPXのファイルを落とす関数（`features/route/gpxExport.ts: downloadGpx`）。
 *
 * 軸は架空のもの（`axis_a`等）を`src/testing/catalogAxes.ts`の雛形から作る。
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type AxisContributionBar from "@/components/AxisContributionBar/AxisContributionBar";
import type ComparisonPanel from "@/features/route/ComparisonPanel/ComparisonPanel";
import type DifficultyProfile from "@/features/route/DifficultyProfile/DifficultyProfile";
import type EditDifference from "@/features/route/EditDifference/EditDifference";
import type RouteAxisProfile from "@/features/route/RouteAxisProfile/RouteAxisProfile";
import type RouteSplicePanel from "@/features/route/RouteSplicePanel/RouteSplicePanel";
import type SegmentWind from "@/features/route/SegmentWind/SegmentWind";
import { downloadGpx, MAX_GPX_TRACK_POINTS } from "@/features/route/gpxExport";
import type { GenerationInput } from "@/features/route/generationRequest";
import { SPLICED_ROUTE_ID_PREFIX } from "@/features/route/routeTabLabel";
import { COMPARISON_TAB, type EditedRoute, type RouteResults } from "@/features/route/useRouteResults";
import { MATERIAL_CATALOG } from "@/lib/axisMaterialsCatalog";
import { catalogAxisFromEntry } from "@/lib/catalogAxis";
import { setResearchEnabled } from "@/lib/researchMode";
import { getAxisCatalog } from "@/services/axisCatalogApi";
import { catalogEntry, catalogOf, catalogResponse } from "@/testing/catalogAxes";
import { makeGenerationConditions, makeRouteCandidate, makeRouteSegment } from "@/testing/routeFixtures";
import type { ExperimentSlot } from "@/types/experimentSlot";
import type { RouteCandidate, RouteSegmentDetail, SelectedRouteSegment } from "@/types/route";
import RouteOutcome from "./RouteOutcome";

const { stubModule, stubProps, isStubMounted } = await vi.hoisted(() => import("@/testing/componentStubs"));
vi.mock("@/features/route/ComparisonPanel/ComparisonPanel", stubModule("ComparisonPanel"));
vi.mock("@/features/route/DifficultyProfile/DifficultyProfile", stubModule("DifficultyProfile"));
vi.mock("@/features/route/RouteAxisProfile/RouteAxisProfile", stubModule("RouteAxisProfile"));
vi.mock("@/components/AxisContributionBar/AxisContributionBar", stubModule("AxisContributionBar"));
vi.mock("@/features/route/EditDifference/EditDifference", stubModule("EditDifference"));
vi.mock("@/features/route/SegmentWind/SegmentWind", stubModule("SegmentWind"));
vi.mock("@/features/route/RouteSplicePanel/RouteSplicePanel", stubModule("RouteSplicePanel"));
vi.mock("@/features/route/gpxExport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/route/gpxExport")>()),
  downloadGpx: vi.fn(),
}));
vi.mock("@/services/axisCatalogApi", () => ({ getAxisCatalog: vi.fn() }));

const ENTRIES = [
  catalogEntry({ axis_id: "axis_a", label: "軸A" }),
  catalogEntry({ axis_id: "axis_b", label: "軸B" }),
  catalogEntry({ axis_id: "axis_c", label: "軸C" }),
];
const CATALOG = catalogOf(ENTRIES);

beforeEach(() => {
  vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(ENTRIES));
});

afterEach(() => {
  setResearchEnabled(false);
  vi.clearAllMocks();
});

function route(id: string, overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return makeRouteCandidate({ id, direction_label: id, ...overrides });
}

const FAST = route("fast", {
  distance_km: 10,
  estimated_duration_seconds: 1800,
  overall_difficulty: { average: 41.6, load: 416 },
});
const SLOW = route("slow", { distance_km: 20, estimated_duration_seconds: 2520, overall_difficulty: null });

function resultsOf(
  state: Partial<
    Pick<RouteResults, "generated" | "edits" | "selectedRouteId" | "comparisonTabActive" | "selectedRouteSegment">
  > = {},
): RouteResults {
  const generated = state.generated ?? [];
  const edits = state.edits ?? [];
  const routes = [...generated, ...edits.map((edit) => edit.route)];
  const selectedRouteId = state.selectedRouteId ?? null;
  const selectedCandidate = routes.find((candidate) => candidate.id === selectedRouteId) ?? null;
  const edit = edits.find((item) => item.route.id === selectedRouteId);
  return {
    routes,
    generated,
    edits,
    selectedRouteId,
    selectedCandidate,
    selectedEdit: edit ? { ...edit, origin: routes.find((candidate) => candidate.id === edit.originId) ?? null } : null,
    hasDetail: (selectedCandidate?.segments.length ?? 0) > 0,
    selectedRouteSegment: state.selectedRouteSegment ?? null,
    selectSegment: vi.fn(),
    comparisonTabActive: state.comparisonTabActive ?? false,
    usedWeights: null,
    replaceWithGenerated: vi.fn(),
    addEdit: vi.fn(),
    clear: vi.fn(),
    selectTab: vi.fn(),
  };
}

type Generation = ComponentProps<typeof RouteOutcome>["generation"];

function generationOf(overrides: Partial<Generation> = {}): Generation {
  return {
    running: false,
    progressLabel: undefined,
    lastMessage: undefined,
    failure: null,
    conditionsDirty: false,
    weightsNotApplied: false,
    destinationCorrected: false,
    experimentSlots: [],
    generatedInput: null,
    ...overrides,
  };
}

/** 生成に使った入力。経由地・目的地だけを変える。 */
function inputOf(overrides: Pick<GenerationInput, "destination" | "waypoints">): GenerationInput {
  return {
    origin: { latitude: 35, longitude: 139 },
    distanceKm: null,
    distanceToleranceKm: 0,
    maxRoutes: 3,
    assumedSpeedKmh: 20,
    startTime: new Date(0),
    hardFilters: {},
    lensAxisId: null,
    routePreference: null,
    startTimePinned: false,
    ...overrides,
  };
}
const DESTINATION_INPUT = inputOf({ destination: { latitude: 35.1, longitude: 139.1 }, waypoints: [] });

type Splice = ComponentProps<typeof RouteOutcome>["splice"];

function renderOutcome({
  results = resultsOf(),
  generation = generationOf(),
  splice = { canStart: false, start: vi.fn(), panel: null },
  routeWeights = { axis_a: 1 },
}: {
  results?: RouteResults;
  generation?: Generation;
  splice?: Splice;
  routeWeights?: Record<string, number>;
} = {}) {
  render(<RouteOutcome results={results} generation={generation} splice={splice} routeWeights={routeWeights} />);
  return { results, splice };
}

/** 一覧の行を、上から行の文で（見出しを含む）。 */
function listTexts(): string[] {
  const list = screen.getByRole("tablist", { name: "ルート結果" });
  return Array.from(list.children).map((child) => child.textContent ?? "");
}

/** 一覧の行の、負荷の帯の高さの倍率。 */
function loadBarRatio(tab: HTMLElement): string {
  const bar = Array.from(tab.querySelectorAll<HTMLElement>("span")).find((span) =>
    span.style.getPropertyValue("--load-bar-height-ratio"),
  );
  return bar?.style.getPropertyValue("--load-bar-height-ratio") ?? "";
}

function segmentSelection(overrides: Partial<RouteSegmentDetail> = {}): SelectedRouteSegment {
  return {
    segment: makeRouteSegment({
      cumulative_distance_km: 3.25,
      estimated_arrival_time: "2026-10-04T00:42:00Z",
      axis_contributions: { axis_a: 12 },
      wind: { speed_ms: 3, direction_deg: 90, forecast_at: null, extended: false },
      ...overrides,
    }),
    latitude: 35,
    longitude: 139,
  };
}

describe("候補が無い間", () => {
  it("生成中は進み方を出す", () => {
    renderOutcome({ generation: generationOf({ running: true, progressLabel: "順番待ち..." }) });
    expect(screen.getByText("順番待ち...")).toBeInTheDocument();
  });

  it("進み方の届く前の生成中は「生成中...」で、直近の案内より先に出す", () => {
    renderOutcome({ generation: generationOf({ running: true, lastMessage: "前回の失敗" }) });
    expect(screen.getByText("生成中...")).toBeInTheDocument();
    expect(screen.queryByText("前回の失敗")).not.toBeInTheDocument();
  });

  it("生成していない間は、直近の案内（失敗・候補0件の理由）をエラーとして出す", () => {
    renderOutcome({ generation: generationOf({ lastMessage: "候補が見つかりませんでした" }) });
    expect(screen.getByRole("alert")).toHaveTextContent("候補が見つかりませんでした");
  });

  it("案内が無ければ、生成を押すと候補が並ぶことを案内する", () => {
    renderOutcome();
    expect(screen.getByText("「ルート設定」の「ルート生成」を押すと候補がここに並びます")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
});

describe("候補の上の知らせ", () => {
  it("作り直しの失敗は前の候補の上にエラーとして出し、その間は条件が変わった旨を重ねない", () => {
    renderOutcome({
      results: resultsOf({ generated: [FAST] }),
      generation: generationOf({ failure: "時間切れ", conditionsDirty: true }),
    });
    expect(screen.getByRole("alert")).toHaveTextContent("作り直せませんでした。時間切れ");
    expect(screen.queryByText("生成条件が変更されています")).not.toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "ルート結果" })).toBeInTheDocument();
  });

  it("条件のずれ・既定の配分で作ったこと・目的地の補正を、それぞれの間だけ知らせる", () => {
    renderOutcome({
      results: resultsOf({ generated: [FAST] }),
      generation: generationOf({ conditionsDirty: true, weightsNotApplied: true, destinationCorrected: true }),
    });
    expect(screen.getByText("生成条件が変更されています")).toBeInTheDocument();
    expect(screen.getByText("重み配分を反映できず、既定の配分で作りました。")).toBeInTheDocument();
    expect(screen.getByText(/近くのアクセス可能な地点へ補正しました/)).toBeInTheDocument();
  });

  it("どれにも当たらなければ知らせを出さない", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST] }) });
    expect(screen.queryByText("生成条件が変更されています")).not.toBeInTheDocument();
    expect(screen.queryByText(/既定の配分/)).not.toBeInTheDocument();
    expect(screen.queryByText(/補正しました/)).not.toBeInTheDocument();
  });
});

describe("候補の一覧", () => {
  it("見出しを分けない生成では、候補に1から番号を振り、距離・最速の印と所要時間・余計にかかる時間・総合難易度を並べる", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST, SLOW] }) });
    expect(listTexts()).toEqual(["1 10.0km30分42", "2 20.0km+12分—"]);
    expect(within(screen.getByRole("tab", { name: /^1 / })).getByRole("img", { name: "最速" })).toBeInTheDocument();
  });

  it("候補が1件なら比べる相手が無いので、最速の印も余計にかかる時間も付けない", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST] }) });
    expect(listTexts()).toEqual(["1 10.0km42"]);
    expect(screen.queryByRole("img", { name: "最速" })).not.toBeInTheDocument();
  });

  it("余計にかかる時間が丸めて1分未満の候補には何も添えない", () => {
    renderOutcome({
      results: resultsOf({ generated: [FAST, route("near", { distance_km: 11, estimated_duration_seconds: 1820 })] }),
    });
    expect(listTexts()[1]).toBe("2 11.0km—");
  });

  it("経由地の無い目的地ルートでは、最速の候補を名前なしで「採用ルート」の先頭に置き、残りを「生成した候補」に番号で並べる", () => {
    renderOutcome({
      results: resultsOf({ generated: [SLOW, FAST] }),
      generation: generationOf({ generatedInput: DESTINATION_INPUT }),
    });
    expect(listTexts()).toEqual(["採用ルート", "10.0km30分42", "生成した候補", "1 20.0km+12分—"]);
  });

  it("経由地を伴う目的地ルートは見出しを分けない", () => {
    renderOutcome({
      results: resultsOf({ generated: [FAST, SLOW] }),
      generation: generationOf({
        generatedInput: inputOf({
          destination: { latitude: 35.1, longitude: 139.1 },
          waypoints: [{ latitude: 35, longitude: 139.05 }],
        }),
      }),
    });
    expect(listTexts()).not.toContain("採用ルート");
  });

  it("編集で作ったルートは「採用ルート」に「編集N」の名前で並ぶ", () => {
    const edit: EditedRoute = {
      route: route(`${SPLICED_ROUTE_ID_PREFIX}-1`, { distance_km: 12 }),
      originId: "fast",
      number: 1,
    };
    renderOutcome({ results: resultsOf({ generated: [FAST, SLOW], edits: [edit] }) });
    expect(listTexts()).toEqual(["採用ルート", "編集1 12.0km—", "生成した候補", "1 10.0km30分42", "2 20.0km+12分—"]);
  });

  it("総合難易度の帯は長さが総合難易度で、算出できなかった候補は塗らない", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST, SLOW] }) });
    const fill = (tab: HTMLElement) =>
      Array.from(tab.querySelectorAll<HTMLElement>("span")).find((span) => span.style.width !== "");
    const [first, second] = screen.getAllByRole("tab");
    expect(fill(first)?.style.width).toBe("41.6%");
    expect(fill(second)).toBeUndefined();
  });

  it("負荷の帯の高さは、一覧の中で最も短い候補を1とした距離の比", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST, route("long", { distance_km: 15 })] }) });
    const [first, second] = screen.getAllByRole("tab");
    expect(loadBarRatio(first)).toBe("1");
    expect(loadBarRatio(second)).toBe("1.5");
  });

  it("選んだ候補のタブが選ばれている", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST, SLOW], selectedRouteId: "slow" }) });
    expect(screen.getByRole("tab", { name: /^2 / })).toHaveAttribute("aria-selected", "true");
  });

  it("選んだ候補が無ければ先頭の候補が選ばれている", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST, SLOW] }) });
    expect(screen.getByRole("tab", { name: /^1 / })).toHaveAttribute("aria-selected", "true");
  });

  it("タブを押すと、その候補のidでタブの選択を上げる", async () => {
    const { results } = renderOutcome({ results: resultsOf({ generated: [FAST, SLOW] }) });
    await userEvent.click(screen.getByRole("tab", { name: /^2 / }));
    expect(results.selectTab).toHaveBeenCalledWith("slow");
  });
});

describe("選んだ候補の中身", () => {
  it("合成は始められるときだけ出し、押すとその候補で編集を始めて押していた区間を外す", async () => {
    const { results, splice } = renderOutcome({
      results: resultsOf({ generated: [FAST, SLOW] }),
      splice: { canStart: true, start: vi.fn(), panel: null },
    });
    await userEvent.click(screen.getByRole("button", { name: "ルートを合成" }));
    expect(splice.start).toHaveBeenCalledWith("fast");
    expect(results.selectSegment).toHaveBeenCalledWith(null);
  });

  it("編集を始められない生成では合成を出さない", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST] }) });
    expect(screen.queryByRole("button", { name: "ルートを合成" })).not.toBeInTheDocument();
  });

  it("GPX出力はその候補を書き出す", async () => {
    renderOutcome({ results: resultsOf({ generated: [FAST, SLOW], selectedRouteId: "slow" }) });
    await userEvent.click(screen.getByRole("button", { name: "GPX出力" }));
    expect(downloadGpx).toHaveBeenCalledWith(SLOW);
  });

  it("GPX出力の使い方に、書き出す点の上限まで間引くことを書く", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST] }) });
    expect(screen.getByRole("button", { name: "GPX出力" }).dataset.usage).toContain(
      `${MAX_GPX_TRACK_POINTS}点に収まるように間引きます`,
    );
  });

  it("編集で作ったルートには、元とその一覧での名前を「元との違い」へ渡し、「元を見る」で元のタブを選ぶ", () => {
    const edited = route(`${SPLICED_ROUTE_ID_PREFIX}-1`, { distance_km: 12 });
    const { results } = renderOutcome({
      results: resultsOf({
        generated: [FAST, SLOW],
        edits: [{ route: edited, originId: "slow", number: 1 }],
        selectedRouteId: edited.id,
      }),
    });
    const props = stubProps<ComponentProps<typeof EditDifference>>("EditDifference");
    expect(props).toMatchObject({ originName: "2", origin: SLOW, edited });
    props.onShowOrigin();
    expect(results.selectTab).toHaveBeenCalledWith("slow");
  });

  it("生成した候補・元が一覧に無い編集には「元との違い」を出さない", () => {
    const orphan = route(`${SPLICED_ROUTE_ID_PREFIX}-1`);
    renderOutcome({
      results: resultsOf({
        generated: [FAST],
        edits: [{ route: orphan, originId: "gone", number: 1 }],
        selectedRouteId: orphan.id,
      }),
    });
    expect(isStubMounted("EditDifference")).toBe(false);
  });

  it("区間のある候補だけに道のりのグラフを出し、横軸は一覧で最も長い候補の距離、押した区間と選ぶ操作を渡す", async () => {
    const segment = makeRouteSegment({ distance_km: 1 });
    const withSegments = route("fast", {
      distance_km: 10,
      segments: [segment],
      overall_difficulty: { average: 30, load: 300 },
    });
    const selected = segmentSelection();
    const { results } = renderOutcome({
      results: resultsOf({ generated: [withSegments, SLOW], selectedRouteSegment: selected }),
    });
    await waitFor(() =>
      expect(stubProps<ComponentProps<typeof DifficultyProfile>>("DifficultyProfile").axisOrder).toHaveLength(3),
    );
    const props = stubProps<ComponentProps<typeof DifficultyProfile>>("DifficultyProfile");
    expect(props).toMatchObject({
      segments: [segment],
      overallDifficulty: 30,
      axisOrder: ["axis_a", "axis_b", "axis_c"],
      axisColors: CATALOG.axisColors,
      scaleKm: 20,
      selected,
    });
    props.onSelect(selected);
    expect(results.selectSegment).toHaveBeenCalledWith(selected);
  });

  it("区間の無い候補には道のりのグラフを出さない", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST] }) });
    expect(isStubMounted("DifficultyProfile")).toBe(false);
  });

  it("区間を押していない間は、候補の値と軸を分ける重みを内訳へ渡す", async () => {
    const candidate = route("fast", {
      distance_km: 10,
      overall_difficulty: { average: 30, load: 300 },
      estimated_duration_seconds: 1800,
      axis_difficulties: { axis_a: 20 },
      axis_contributions: { axis_a: 30 },
      axis_raw_values: { axis_a: 0.5 },
      material_values: { m: 1 },
      material_category_shares: { c: { x: 1 } },
      wind_unavailable: true,
      missing_travel_data_share: 0.1,
    });
    renderOutcome({ results: resultsOf({ generated: [candidate] }), routeWeights: { axis_a: 0.7 } });
    await waitFor(() =>
      expect(stubProps<ComponentProps<typeof RouteAxisProfile>>("RouteAxisProfile").axes).toHaveLength(3),
    );
    expect(stubProps<ComponentProps<typeof RouteAxisProfile>>("RouteAxisProfile")).toMatchObject({
      axes: CATALOG.axes,
      weights: { axis_a: 0.7 },
      axisDifficulties: { axis_a: 20 },
      axisContributions: { axis_a: 30 },
      axisRawValues: { axis_a: 0.5 },
      materialValues: { m: 1 },
      materialCategoryShares: { c: { x: 1 } },
      distanceKm: 10,
      overallDifficulty: { average: 30, load: 300 },
      estimatedDurationSeconds: 1800,
      windUnavailable: true,
      missingTravelDataShare: 0.1,
      axisColors: CATALOG.axisColors,
    });
    expect(isStubMounted("SegmentWind")).toBe(false);
  });

  it("区間を押している間は、内訳の代わりに区間の地点・到達予想（日本時間）・風・寄与を出す", async () => {
    const selected = segmentSelection();
    renderOutcome({ results: resultsOf({ generated: [FAST], selectedRouteSegment: selected }) });
    expect(screen.getByText("3.3 km地点")).toBeInTheDocument();
    expect(screen.getByText("到達予想 09:42")).toBeInTheDocument();
    expect(isStubMounted("RouteAxisProfile")).toBe(false);
    expect(stubProps<ComponentProps<typeof SegmentWind>>("SegmentWind").wind).toBe(selected.segment.wind);
    await waitFor(() =>
      expect(stubProps<ComponentProps<typeof AxisContributionBar>>("AxisContributionBar").axes).toHaveLength(3),
    );
    expect(stubProps<ComponentProps<typeof AxisContributionBar>>("AxisContributionBar")).toMatchObject({
      axes: CATALOG.axes,
      contributions: { axis_a: 12 },
      axisColors: CATALOG.axisColors,
    });
  });

  it("区間の内訳のチップから開く詳細は、軸の名前・候補全体ではなくその区間の軸別難易度・説明を出す", async () => {
    const candidate = route("fast", { axis_difficulties: { axis_a: 20, axis_b: 30 } });
    const selected = segmentSelection({ axis_difficulties: { axis_a: 72.4 } });
    renderOutcome({ results: resultsOf({ generated: [candidate], selectedRouteSegment: selected }) });
    await waitFor(() =>
      expect(stubProps<ComponentProps<typeof AxisContributionBar>>("AxisContributionBar").axes).toHaveLength(3),
    );
    const { renderDetail } = stubProps<ComponentProps<typeof AxisContributionBar>>("AxisContributionBar");
    const detailOf = (entry: Parameters<typeof catalogEntry>[0]) =>
      render(<>{renderDetail?.(catalogAxisFromEntry(catalogEntry(entry)))}</>).container.textContent;
    expect(detailOf({ axis_id: "axis_a", label: "軸A", description: "軸Aの説明" })).toBe(
      "軸A軸別難易度 72/100軸Aの説明",
    );
    expect(detailOf({ axis_id: "axis_b", label: "軸B" })).toBe("軸Bデータなし");
  });

  it.each([
    ["到達予想が無い", null],
    ["到達予想が時刻として読めない", "not-a-time"],
  ])("%s区間は、到達予想を「不明」と出す", (_, arrival) => {
    renderOutcome({
      results: resultsOf({
        generated: [FAST],
        selectedRouteSegment: segmentSelection({ estimated_arrival_time: arrival }),
      }),
    });
    expect(screen.getByText("到達予想 不明")).toBeInTheDocument();
  });

  it("区間の選択の解除を押すと、押していた区間を外す", async () => {
    const { results } = renderOutcome({
      results: resultsOf({ generated: [FAST], selectedRouteSegment: segmentSelection() }),
    });
    await userEvent.click(screen.getByRole("button", { name: "区間の選択を解除" }));
    expect(results.selectSegment).toHaveBeenCalledWith(null);
  });

  it("研究モードの間だけ、区間の材料の値を名前を引けるものだけ並べる", () => {
    const known = MATERIAL_CATALOG[0];
    const selected = segmentSelection({ material_values: { [known.id]: 1.5, not_a_material: 2 } });
    const { unmount } = render(
      <RouteOutcome
        results={resultsOf({ generated: [FAST], selectedRouteSegment: selected })}
        generation={generationOf()}
        splice={{ canStart: false, start: vi.fn(), panel: null }}
        routeWeights={{}}
      />,
    );
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    unmount();

    setResearchEnabled(true);
    renderOutcome({ results: resultsOf({ generated: [FAST], selectedRouteSegment: selected }) });
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(items[0].textContent?.startsWith(`${known.name}: 1.5`)).toBe(true);
  });

  it("編集している間は、一覧の代わりに編集面だけを出す", () => {
    const panel: ComponentProps<typeof RouteSplicePanel> = {
      displayed: FAST,
      appliedCount: 0,
      hasAlternatives: true,
      onUndo: vi.fn(),
      onReset: vi.fn(),
      preview: null,
      previewing: false,
      onPreview: vi.fn(),
      onApply: vi.fn(),
      applying: false,
      error: null,
      onCancel: vi.fn(),
      axes: CATALOG.axes,
      axisColors: CATALOG.axisColors,
    };
    renderOutcome({
      results: resultsOf({ generated: [FAST, SLOW] }),
      splice: { canStart: true, start: vi.fn(), panel },
    });
    expect(stubProps("RouteSplicePanel")).toEqual(panel);
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
});

describe("研究モードの比較", () => {
  function slot(id: string, routePreference: Record<string, number>): ExperimentSlot {
    return {
      id,
      color: "",
      conditions: makeGenerationConditions({ route_preference: routePreference }),
      topCandidate: route(id),
    };
  }

  it("研究モードでなければ比較タブを出さない", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST] }) });
    expect(screen.queryByRole("tab", { name: "比較" })).not.toBeInTheDocument();
    expect(isStubMounted("ComparisonPanel")).toBe(false);
  });

  it("比較タブを末尾に出し、開いていない間も比較表を描いておく", () => {
    setResearchEnabled(true);
    renderOutcome({ results: resultsOf({ generated: [FAST] }) });
    const tabs = screen.getAllByRole("tab");
    expect(tabs.at(-1)).toHaveTextContent("比較");
    expect(tabs.at(-1)).toHaveAttribute("aria-selected", "false");
    expect(isStubMounted("ComparisonPanel")).toBe(true);
  });

  it("比較を見ている間は、選んだ候補ではなく比較タブが選ばれている", () => {
    setResearchEnabled(true);
    renderOutcome({ results: resultsOf({ generated: [FAST], selectedRouteId: "fast", comparisonTabActive: true }) });
    expect(screen.getByRole("tab", { name: "比較" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /^1 / })).toHaveAttribute("aria-selected", "false");
  });

  it("比較タブを押すと、比較タブの選択を上げる", async () => {
    setResearchEnabled(true);
    const { results } = renderOutcome({ results: resultsOf({ generated: [FAST] }) });
    await userEvent.click(screen.getByRole("tab", { name: "比較" }));
    expect(results.selectTab).toHaveBeenCalledWith(COMPARISON_TAB);
  });

  it("比較表へは、どれかの回で重みが0より大きかった軸と、回・軸の名前・材料の一覧を渡す", async () => {
    setResearchEnabled(true);
    const slots = [slot("one", { axis_a: 0.5, axis_b: 0 }), slot("two", { axis_c: 0.2 })];
    renderOutcome({ results: resultsOf({ generated: [FAST] }), generation: generationOf({ experimentSlots: slots }) });
    await waitFor(() =>
      expect(stubProps<ComponentProps<typeof ComparisonPanel>>("ComparisonPanel").axes).toHaveLength(2),
    );
    const props = stubProps<ComponentProps<typeof ComparisonPanel>>("ComparisonPanel");
    expect(props.axes.map((axis) => axis.axisId)).toEqual(["axis_a", "axis_c"]);
    expect(props).toMatchObject({ slots, axisLabels: CATALOG.axisLabels, materials: MATERIAL_CATALOG });
  });
});
