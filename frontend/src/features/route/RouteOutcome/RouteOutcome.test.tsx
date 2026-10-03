/**
 * 「ルート結果」の中身（`RouteOutcome`）——空の状態・案内・候補の一覧の行・候補の操作・選んだ候補の中身と区間の詳細・比較・
 * 編集面を、結果（本物の`useRouteResults`）・生成・乗り換えの値から描き、上がった操作を結果へ返す。
 *
 * ここで見ないもの:
 * - 最速の印・「+N分」・見出しの分け方と名前・負荷の帯の高さの決め方 → `routeTabLabel.ts`・`difficultyLoadBar.ts`
 * - 生成の案内・条件のずれの決め方 → `useRouteGeneration.ts`、乗り換えの状態 → `useSpliceSession.ts`
 *
 * 差し替えた部品と、それで見えなくなるもの:
 * - 候補の中身（`RouteAxisProfile`）・道のりのグラフ（`DifficultyProfile`）・区間の内訳の帯（`AxisContributionBar`）・
 *   区間の風（`SegmentWind`）・比較表（`ComparisonPanel`）・編集面（`RouteSplicePanel`）・元との違い（`EditDifference`）:
 *   渡す値と、上がる操作だけを見る。
 *   部品自身の表示は各部品のテストが見る。
 * - 軸カタログ（`useAxisCatalog`）: 返す値をテストが決める。GPXの書き出し（`gpxExport.downloadGpx`）: ファイルを落とす境界。
 */
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLayoutEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { axisCatalogFromResponse, type AxisCatalog } from "@/lib/axisCatalog";
import { MATERIAL_CATALOG } from "@/lib/axisMaterialsCatalog";
import { catalogEntry, catalogResponse } from "@/testing/catalogAxes";
import { setResearchEnabled } from "@/lib/researchMode";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import { useRouteResults, type RouteResults } from "@/features/route/useRouteResults";
import type { ExperimentSlot } from "@/types/experimentSlot";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { GenerationConditions, RouteCandidate, RouteSegmentDetail } from "@/types/route";

const { isStubMounted, stubModule, stubProps } = await vi.hoisted(() => import("@/testing/componentStubs"));
const stubs = vi.hoisted(() => ({ catalog: undefined as unknown }));
vi.mock("@/features/route/RouteAxisProfile/RouteAxisProfile", stubModule("RouteAxisProfile"));
vi.mock("@/features/route/DifficultyProfile/DifficultyProfile", stubModule("DifficultyProfile"));
vi.mock("@/components/AxisContributionBar/AxisContributionBar", stubModule("AxisContributionBar"));
vi.mock("@/features/route/SegmentWind/SegmentWind", stubModule("SegmentWind"));
vi.mock("@/features/route/ComparisonPanel/ComparisonPanel", stubModule("ComparisonPanel"));
vi.mock("@/features/route/RouteSplicePanel/RouteSplicePanel", stubModule("RouteSplicePanel"));
vi.mock("@/features/route/EditDifference/EditDifference", stubModule("EditDifference"));
vi.mock("@/hooks/useAxisCatalog", () => ({ useAxisCatalog: () => stubs.catalog }));
vi.mock("@/features/route/gpxExport", () => ({ downloadGpx: vi.fn() }));

import { downloadGpx } from "@/features/route/gpxExport";
import RouteOutcome from "./RouteOutcome";

const CATALOG: AxisCatalog = axisCatalogFromResponse(
  catalogResponse([
    catalogEntry({ axis_id: "axis_a" }),
    catalogEntry({ axis_id: "axis_b" }),
    catalogEntry({ axis_id: "axis_c" }),
  ]),
);

type Props = Omit<Parameters<typeof RouteOutcome>[0], "results">;
const GENERATION: Props["generation"] = {
  running: false,
  progressLabel: undefined,
  lastMessage: undefined,
  failure: null,
  conditionsDirty: false,
  weightsNotApplied: false,
  destinationCorrected: false,
  experimentSlots: [],
  generatedInput: null,
};
// 経由地の無い目的地ルートの生成（所要時間だけで選んだ1本を必ず含む）。
const DESTINATION_INPUT: Props["generation"]["generatedInput"] = {
  origin: { latitude: 35, longitude: 139 },
  distanceKm: null,
  distanceToleranceKm: 5,
  maxRoutes: 3,
  assumedSpeedKmh: 20,
  startTime: new Date("2026-09-25T03:00:00Z"),
  startTimePinned: false,
  hardFilters: {},
  lensAxisId: null,
  routePreference: null,
  waypoints: [],
  destination: { latitude: 35.1, longitude: 139 },
};
const SPLICE: Props["splice"] = { canStart: false, start: vi.fn(), panel: null };
const ROUTE_WEIGHTS = { axis_a: 0.2 };

const resultsRef = { current: undefined as unknown as RouteResults };
function Harness(props: Props) {
  const results = useRouteResults();
  useLayoutEffect(() => {
    resultsRef.current = results;
  });
  return <RouteOutcome results={results} {...props} />;
}
function renderOutcome(
  overrides: { generation?: Partial<Props["generation"]>; splice?: Partial<Props["splice"]> } = {},
) {
  const props: Props = {
    generation: { ...GENERATION, ...overrides.generation },
    splice: { ...SPLICE, ...overrides.splice },
    routeWeights: ROUTE_WEIGHTS,
  };
  const view = render(<Harness {...props} />);
  return { ...view, props };
}
function withRoutes(routes: RouteCandidate[], usedWeights = { axis_b: 1 }) {
  act(() => resultsRef.current.replaceWithGenerated(routes, usedWeights));
}
const rows = () => within(screen.getByRole("tablist", { name: "ルート結果" })).getAllByRole("tab");
const row = (name: RegExp | string) =>
  within(screen.getByRole("tablist", { name: "ルート結果" })).getByRole("tab", { name });

function segment(overrides: Partial<RouteSegmentDetail> = {}): RouteSegmentDetail {
  return {
    geometry: null,
    start_latitude: 0,
    start_longitude: 0,
    end_latitude: 0,
    end_longitude: 0,
    cumulative_distance_km: 0,
    distance_km: 0,
    estimated_arrival_time: null,
    axis_difficulties: {},
    axis_contributions: {},
    material_values: {},
    axis_raw_values: {},
    difficulty: null,
    wind: null,
    ...overrides,
  };
}
const route = (id: string, overrides: Partial<RouteCandidate> = {}) => makeRouteCandidate({ id, ...overrides });

beforeEach(() => {
  stubs.catalog = CATALOG;
  vi.mocked(downloadGpx).mockReset();
  setResearchEnabled(false);
});
afterEach(() => setResearchEnabled(false));

describe("候補が無い間", () => {
  it("生成前は、押せば候補が並ぶことを案内する", () => {
    renderOutcome();
    expect(screen.getByText("「ルート設定」の「生成」を押すと候補がここに並びます")).toBeInTheDocument();
  });

  it("生成中は進み方を出し、進み方がまだ無ければ「生成中...」を出す", () => {
    const { rerender, props } = renderOutcome({ generation: { running: true } });
    expect(screen.getByText("生成中...")).toBeInTheDocument();
    rerender(<Harness {...props} generation={{ ...props.generation, progressLabel: "順番待ち..." }} />);
    expect(screen.getByText("順番待ち...")).toBeInTheDocument();
  });

  it("直近の案内（失敗・候補0件の理由）はエラーとして出す", () => {
    renderOutcome({ generation: { lastMessage: "対象の道が見つかりません" } });
    expect(screen.getByRole("alert")).toHaveTextContent("対象の道が見つかりません");
  });
});

describe("候補の上の案内", () => {
  it("作り直しの失敗は前の候補の上に出し、その間は条件が変わった旨を重ねない", () => {
    renderOutcome({ generation: { failure: "混み合っています", conditionsDirty: true } });
    withRoutes([route("a")]);
    expect(screen.getByRole("alert")).toHaveTextContent("作り直せませんでした。混み合っています");
    expect(screen.queryByText("生成条件が変更されています")).not.toBeInTheDocument();
    expect(rows()).toHaveLength(1);
  });

  it("条件のずれ・既定の配分で作ったこと・目的地の補正を、それぞれの間だけ知らせる", () => {
    const { rerender, props } = renderOutcome();
    withRoutes([route("a")]);
    expect(screen.queryByText("生成条件が変更されています")).not.toBeInTheDocument();
    rerender(
      <Harness
        {...props}
        generation={{ ...props.generation, conditionsDirty: true, weightsNotApplied: true, destinationCorrected: true }}
      />,
    );
    expect(screen.getByText("生成条件が変更されています")).toBeInTheDocument();
    expect(screen.getByText("重み配分を反映できず、既定の配分で作りました。")).toBeInTheDocument();
    expect(
      screen.getByText("指定した地点は自転車で行けない場所だったため、近くのアクセス可能な地点へ補正しました。"),
    ).toBeInTheDocument();
  });
});

describe("候補の一覧の行", () => {
  it("並びどおりの順位と距離を出し、最も早く着く候補にその所要時間と「最速」の印、他の候補に余計にかかる時間を添える", () => {
    renderOutcome();
    withRoutes([
      route("fast", { distance_km: 12.34, estimated_duration_seconds: 3600 }),
      route("slow", { distance_km: 9, estimated_duration_seconds: 3600 + 12 * 60 }),
      route("unknown", { distance_km: 8 }),
    ]);
    const [fast, slow, unknown] = rows();
    expect(fast).toHaveTextContent(/^1 12\.3km/);
    expect(within(fast).getByRole("img", { name: "最速" })).toBeInTheDocument();
    expect(fast).toHaveTextContent("60分");
    expect(slow).toHaveTextContent(/^2 9\.0km/);
    expect(slow).toHaveTextContent("+12分");
    expect(within(slow).queryByRole("img", { name: "最速" })).not.toBeInTheDocument();
    expect(unknown).toHaveTextContent(/^3 8\.0km—$/);
  });

  it("候補が1件なら比べる相手が無いので最速の印を付けない", () => {
    renderOutcome();
    withRoutes([route("only", { estimated_duration_seconds: 600 })]);
    expect(screen.queryByRole("img", { name: "最速" })).not.toBeInTheDocument();
  });

  it("経由地を通るルートは順位の代わりに名前を出す", () => {
    renderOutcome();
    withRoutes([route(routeGenerateConfig.waypoints_route_id, { direction_label: "経由地ルート", distance_km: 5 })]);
    expect(rows()[0]).toHaveTextContent(/^経由地ルート 5\.0km/);
  });

  it("経由地の無い目的地ルートでは、最速を「採用ルート」の先頭に、編集で作ったルートをその後に、残りを「生成した候補」に並べる", () => {
    renderOutcome({ generation: { generatedInput: DESTINATION_INPUT } });
    withRoutes([
      route("fast", { distance_km: 14.2, estimated_duration_seconds: 2880 }),
      route("slow", { distance_km: 15.1, estimated_duration_seconds: 2880 + 4 * 60 }),
    ]);
    act(() =>
      resultsRef.current.addEdit(route("made", { distance_km: 15.6, estimated_duration_seconds: 3180 }), "slow"),
    );
    const list = screen.getByRole("tablist", { name: "ルート結果" });
    expect(list).toHaveTextContent(/^採用ルート14\.2km48分.*編集1 15\.6km\+5分.*生成した候補1 15\.1km\+4分/);
    expect(within(rows()[0]).getByRole("img", { name: "最速" })).toBeInTheDocument();
    expect(rows().map((tab) => tab.getAttribute("aria-selected"))).toEqual(["false", "true", "false"]);
  });

  it("周回の生成では見出しを分けない", () => {
    renderOutcome();
    withRoutes([route("a", { estimated_duration_seconds: 600 }), route("b", { estimated_duration_seconds: 700 })]);
    expect(screen.queryByText("採用ルート")).not.toBeInTheDocument();
    expect(screen.queryByText("生成した候補")).not.toBeInTheDocument();
  });

  it("総合難易度は丸めた数値と帯の長さで出し、算出できなかった候補は「—」だけで帯を塗らない", () => {
    renderOutcome();
    withRoutes([route("scored", { overall_difficulty: { average: 42.6, load: 426 } }), route("missing")]);
    const [scored, missing] = rows();
    expect(scored).toHaveTextContent(/43$/);
    expect(scored.querySelector('[style*="width: 42.6%"]')).not.toBeNull();
    expect(missing).toHaveTextContent(/—$/);
    expect(missing.querySelector('[style*="width"]')).toBeNull();
  });

  it("負荷の帯の高さは、一覧の最短の候補を基準にした距離の倍率", () => {
    renderOutcome();
    withRoutes([route("short", { distance_km: 10 }), route("long", { distance_km: 15 })]);
    const [short, long] = rows();
    expect(short.querySelector('[style*="--load-bar-height-ratio: 1;"]')).not.toBeNull();
    expect(long.querySelector('[style*="--load-bar-height-ratio: 1.5"]')).not.toBeNull();
  });

  it("選んでいる候補の行が選ばれて見え、行を押すとその候補を選ぶ", async () => {
    const user = userEvent.setup();
    renderOutcome();
    withRoutes([route("a", { distance_km: 1 }), route("b", { distance_km: 2 })]);
    expect(row(/^1 /)).toHaveAttribute("aria-selected", "true");
    await user.click(row(/^2 /));
    expect(resultsRef.current.selectedRouteId).toBe("b");
    expect(row(/^2 /)).toHaveAttribute("aria-selected", "true");
  });
});

describe("候補の中身", () => {
  it("区間を押していない間は、候補の値と「未使用」を分ける重みを中身へ渡す", () => {
    renderOutcome();
    const candidate = route("a", {
      distance_km: 12,
      overall_difficulty: { average: 30, load: 360 },
      estimated_duration_seconds: 2400,
      wind_unavailable: true,
      missing_travel_data_share: 0.1,
      axis_difficulties: { axis_a: 10 },
      axis_contributions: { axis_a: 5 },
      axis_raw_values: { axis_a: 1 },
      material_values: { m: 2 },
      material_category_shares: { m: { x: 1 } },
    });
    withRoutes([candidate], { axis_b: 1 });
    expect(stubProps("RouteAxisProfile")).toEqual({
      axes: CATALOG.axes,
      weights: ROUTE_WEIGHTS,
      axisDifficulties: candidate.axis_difficulties,
      axisContributions: candidate.axis_contributions,
      axisRawValues: candidate.axis_raw_values,
      materialValues: candidate.material_values,
      materialCategoryShares: candidate.material_category_shares,
      distanceKm: 12,
      overallDifficulty: { average: 30, load: 360 },
      estimatedDurationSeconds: 2400,
      windUnavailable: true,
      missingTravelDataShare: 0.1,
      axisColors: CATALOG.axisColors,
    });
  });

  it("道のりのグラフは区間を持つ候補にだけ出し、横軸は一覧で最も長い候補の距離にする。グラフで選んだ区間は結果へ入る", () => {
    renderOutcome();
    const segments = [segment({ cumulative_distance_km: 1 })];
    withRoutes([
      route("a", { distance_km: 10, segments, overall_difficulty: { average: 20, load: 200 } }),
      route("b", { distance_km: 25 }),
    ]);
    const graph = stubProps<{
      segments: unknown;
      scaleKm: number;
      axisOrder: string[];
      overallDifficulty: number;
      onSelect: (value: unknown) => void;
    }>("DifficultyProfile");
    expect(graph).toMatchObject({
      segments,
      scaleKm: 25,
      axisOrder: ["axis_a", "axis_b", "axis_c"],
      overallDifficulty: 20,
      selected: null,
    });
    const selection = { segment: segments[0], latitude: 35, longitude: 139 };
    act(() => graph.onSelect(selection));
    expect(resultsRef.current.selectedRouteSegment).toBe(selection);
  });

  it("区間を持たない候補にはグラフを出さない", () => {
    renderOutcome();
    withRoutes([route("a", { segments: [] })]);
    expect(isStubMounted("DifficultyProfile")).toBe(false);
  });
});

describe("押した区間の詳細", () => {
  const WIND = { direction_deg: 90, speed_ms: 3, forecast_at: null, extended: false } as RouteSegmentDetail["wind"];

  it("地点・到着予想（日本時間）・風・内訳を中身の代わりに出し、×で候補の中身へ戻す", async () => {
    const user = userEvent.setup();
    renderOutcome();
    withRoutes([route("a")]);
    const detail = segment({
      cumulative_distance_km: 12.34,
      estimated_arrival_time: "2026-09-25T03:40:00Z",
      wind: WIND,
      axis_contributions: { axis_a: 4 },
    });
    act(() => resultsRef.current.selectSegment({ segment: detail, latitude: 35, longitude: 139 }));
    expect(screen.getByText(/12\.3 km地点/)).toBeInTheDocument();
    expect(screen.getByText("到達予想 12:40")).toBeInTheDocument();
    expect(stubProps("SegmentWind")).toEqual({ wind: WIND });
    expect(stubProps("AxisContributionBar")).toEqual({
      axes: CATALOG.axes,
      contributions: { axis_a: 4 },
      axisColors: CATALOG.axisColors,
    });
    expect(isStubMounted("RouteAxisProfile")).toBe(false);

    await user.click(screen.getByRole("button", { name: "区間の選択を解除" }));
    expect(resultsRef.current.selectedRouteSegment).toBeNull();
    expect(isStubMounted("RouteAxisProfile")).toBe(true);
  });

  it.each([
    ["無い", null],
    ["読めない", "not-a-time"],
  ])("到着予想が%sときは「不明」と出す", (_c, arrival) => {
    renderOutcome();
    withRoutes([route("a")]);
    act(() =>
      resultsRef.current.selectSegment({
        segment: segment({ estimated_arrival_time: arrival }),
        latitude: 0,
        longitude: 0,
      }),
    );
    expect(screen.getByText("到達予想 不明")).toBeInTheDocument();
  });

  it("研究モードの間だけ区間の材料の値を名前付きで並べ、名前を引けない材料は出さない", () => {
    const [known] = MATERIAL_CATALOG;
    const detail = segment({ material_values: { [known.id]: 1, not_a_material: 2 } });
    renderOutcome();
    withRoutes([route("a")]);
    act(() => resultsRef.current.selectSegment({ segment: detail, latitude: 0, longitude: 0 }));
    expect(screen.queryByRole("list")).not.toBeInTheDocument();

    act(() => setResearchEnabled(true));
    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent(`${known.name}: `);
  });
});

describe("候補の操作", () => {
  it("「GPX」はその候補を書き出す", async () => {
    const user = userEvent.setup();
    renderOutcome();
    const candidate = route("a");
    withRoutes([candidate]);
    await user.click(screen.getByRole("button", { name: "GPX出力" }));
    expect(downloadGpx).toHaveBeenCalledWith(candidate);
  });

  it("「合成」は始められるときだけ出し、押すとその候補から編集を始めて押していた区間を外す", async () => {
    const user = userEvent.setup();
    const start = vi.fn();
    const { rerender, props } = renderOutcome();
    withRoutes([route("a"), route("b")]);
    expect(screen.queryByRole("button", { name: "ルートを合成" })).not.toBeInTheDocument();

    rerender(<Harness {...props} splice={{ ...props.splice, canStart: true, start }} />);
    act(() => resultsRef.current.selectSegment({ segment: segment(), latitude: 0, longitude: 0 }));
    await user.click(screen.getByRole("button", { name: "ルートを合成" }));
    expect(start).toHaveBeenCalledWith("a");
    expect(resultsRef.current.selectedRouteSegment).toBeNull();
  });

  it("編集で作ったルートの中身の先頭に、元の名前と元・編集後を渡して元との違いを出し、「元を見る」で元を選ぶ", () => {
    renderOutcome({ generation: { generatedInput: DESTINATION_INPUT } });
    const generated = [
      route("fast", { estimated_duration_seconds: 600 }),
      route("slow", { estimated_duration_seconds: 700 }),
    ];
    withRoutes(generated);
    expect(isStubMounted("EditDifference")).toBe(false);
    const made = route("made", { estimated_duration_seconds: 650 });
    act(() => resultsRef.current.addEdit(made, "slow"));
    const shown = stubProps<{
      originName: string;
      origin: RouteCandidate;
      edited: RouteCandidate;
      onShowOrigin: () => void;
    }>("EditDifference");
    expect(shown).toMatchObject({
      originName: "1",
      origin: generated[1],
      edited: { ...made, id: resultsRef.current.selectedRouteId },
    });
    act(() => shown.onShowOrigin());
    expect(resultsRef.current.selectedRouteId).toBe("slow");
    expect(isStubMounted("EditDifference")).toBe(false);
  });

  it("編集中は一覧の代わりに編集面を出し、編集面の値をそのまま渡す（作り直しの失敗は上に残す）", () => {
    const panel = { marker: "編集面" } as unknown as NonNullable<Props["splice"]["panel"]>;
    renderOutcome({ splice: { panel }, generation: { failure: "混み合っています" } });
    withRoutes([route("a")]);
    expect(stubProps("RouteSplicePanel")).toEqual(panel);
    expect(screen.queryByRole("tablist", { name: "ルート結果" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("作り直せませんでした。混み合っています");
  });
});

describe("比較", () => {
  const slot = (weights: Record<string, number>): ExperimentSlot => ({
    id: JSON.stringify(weights),
    color: "#000",
    conditions: { route_preference: weights } as unknown as GenerationConditions,
    topCandidate: route("top"),
  });

  it("研究モードでない間は「比較」の行を出さない", () => {
    renderOutcome();
    withRoutes([route("a")]);
    expect(screen.queryByRole("tab", { name: "比較" })).not.toBeInTheDocument();
  });

  it("研究モードでは末尾に「比較」を出し、軸はいずれかのスロットを作ったときの重みが正だった軸に絞る。押すと比較を見る", async () => {
    setResearchEnabled(true);
    const user = userEvent.setup();
    const slots = [slot({ axis_a: 0.5, axis_b: 0 }), slot({ axis_c: 1 })];
    renderOutcome({ generation: { experimentSlots: slots } });
    withRoutes([route("a")]);
    expect(rows().at(-1)).toHaveTextContent("比較");
    expect(stubProps("ComparisonPanel")).toEqual({
      slots,
      axisLabels: CATALOG.axisLabels,
      axes: CATALOG.axes.filter((axis) => axis.axisId !== "axis_b"),
      materials: MATERIAL_CATALOG,
    });
    await user.click(screen.getByRole("tab", { name: "比較" }));
    expect(resultsRef.current.comparisonTabActive).toBe(true);
    expect(screen.getByRole("tab", { name: "比較" })).toHaveAttribute("aria-selected", "true");
  });
});
