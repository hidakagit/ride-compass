/**
 * `features/route/RouteOutcome/RouteOutcome.tsx`——「ルート結果」の中身。
 *
 * 見るもの:
 * - 候補が無い間の案内（生成中の進み方・直近の案内・生成前）と、候補がある間の作り直しの失敗・条件のずれ・
 *   既定の配分で作ったこと・目的地の補正の知らせ（作り直しの失敗を出している間は条件のずれを重ねない）、乗り換えで
 *   作った経路と同じ道だったので選んだ候補の知らせと、その行を見える位置へ出すこと
 * - 候補の一覧: 一番上の列の見出し、群（最速・生成した候補・合成）の間の区切りの線と名前の列の印（意味を読み上げの
 *   名前に持つ）、行に出す名前・距離・基準線の所要時間・ほかの候補の基準線との差・総合難易度（無ければ「—」）、
 *   選ばれているタブ（選んだ候補・無ければ先頭・比較を見ている間は比較）と、タブを押したときに上がる操作
 * - 選んだ候補の中身: 合成（始められるときだけ）・GPXの操作、編集で作ったルートの「元との違い」の元と名前、
 *   道のりのグラフ（横軸・押した区間・動かして選ぶこと）、区間を押している間の地点・到達予想・解除・
 *   区間の総合難易度（全部0なら0であることの文）・風・内訳（チップから開く軸の詳細を含む）と研究モードの材料の値、
 *   押していない間の内訳、編集中は編集面だけを出し、同じ道の候補を一覧の名前で渡すこと
 * - 研究モードの比較タブと、比較表に並ぶ軸（どれかの回で重みが0より大きかった軸）
 *
 * ここで見ないもの: 一覧の並び・群・名前・基準線と差の決め方 → `features/route/routeTabLabel.ts`。
 * 結果の状態の移り変わり → `features/route/useRouteResults.ts`。子の部品（比較表・道のりのグラフ・内訳・寄与の帯・
 * 元との違い・区間の風・編集面）は本物を描き、ここでは受け渡し（親の値が子のどこに出るか・子の操作で親の何が変わるか）
 * だけを見る。子が値をどう描くか（書式・並び・空のときの案内）は各部品のテストが見る。値を子・文へそのまま渡すだけの所
 * （内訳の生値・材料の値・所要の前提の知らせ・内訳に渡す重み・GPXの使い方の点の上限等）は1行の委譲なので見ない。
 * 道のりのグラフの塗り（積む軸の並び・色・値の無い区間の高さ）は読み上げに出ないので見ない。
 *
 * 差し替えたもの: 軸カタログの応答（網の層）と、GPXのファイルを落とす関数（`features/route/gpxExport.ts: downloadGpx`）。
 *
 * 軸は架空のもの（`axis_a`等）を`src/testing/catalogAxes.ts`の雛形から作る。
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { downloadGpx } from "@/features/route/gpxExport";
import { COMPARISON_TAB, type EditedRoute, type RouteResults } from "@/features/route/useRouteResults";
import { MATERIAL_CATALOG } from "@/lib/axisMaterialsCatalog";
import { setResearchEnabled } from "@/lib/researchMode";
import { serveAxisCatalog } from "@/testing/backendServer";
import { catalogEntry, catalogOf, catalogResponse } from "@/testing/catalogAxes";
import { makeGenerationConditions, makeRouteCandidate, makeRouteSegment } from "@/testing/routeFixtures";
import type { ExperimentSlot } from "@/types/experimentSlot";
import type { RouteCandidate, RouteSegmentDetail, SelectedRouteSegment } from "@/types/route";
import RouteOutcome from "./RouteOutcome";

vi.mock("@/features/route/gpxExport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/route/gpxExport")>()),
  downloadGpx: vi.fn(),
}));

const ENTRIES = [
  catalogEntry({ axis_id: "axis_a", label: "軸A" }),
  catalogEntry({ axis_id: "axis_b", label: "軸B" }),
  catalogEntry({ axis_id: "axis_c", label: "軸C" }),
];
const CATALOG = catalogOf(ENTRIES);

beforeEach(() => {
  serveAxisCatalog(catalogResponse(ENTRIES));
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
    Pick<
      RouteResults,
      "generated" | "edits" | "selectedRouteId" | "reusedRouteId" | "comparisonTabActive" | "selectedRouteSegment"
    >
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
    reusedRouteId: state.reusedRouteId ?? null,
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
    selectReused: vi.fn(),
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
    ...overrides,
  };
}

type Splice = ComponentProps<typeof RouteOutcome>["splice"];

function renderOutcome({
  results = resultsOf(),
  generation = generationOf(),
  splice = { canStart: false, start: vi.fn(), panel: null },
}: {
  results?: RouteResults;
  generation?: Generation;
  splice?: Splice;
} = {}) {
  render(<RouteOutcome results={results} generation={generation} splice={splice} routeWeights={{}} />);
  return { results, splice };
}

/** 一覧の行を、上から行の文で（列の見出しを含み、区切りの線は「―」）。 */
function listTexts(): string[] {
  const list = screen.getByRole("tablist", { name: "ルート結果" });
  return Array.from(list.children).map((child) =>
    child.getAttribute("role") === "separator" || child.tagName === "HR" ? "―" : (child.textContent ?? ""),
  );
}

const HEADER = "km時間難易度";

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
    expect(screen.getByText(/候補がここに並びます/)).toHaveTextContent(
      "「ルート設定」のルート生成を押すと候補がここに並びます",
    );
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

  it.each([true, false])(
    "条件のずれ・既定の配分で作ったこと・目的地の補正を、それぞれの間だけ知らせる（当たる: %s）",
    (on) => {
      renderOutcome({
        results: resultsOf({ generated: [FAST] }),
        generation: generationOf({ conditionsDirty: on, weightsNotApplied: on, destinationCorrected: on }),
      });
      for (const text of [
        "生成条件が変更されています",
        "重み配分を反映できず、既定の配分で作りました。",
        /近くのアクセス可能な地点へ補正しました/,
      ]) {
        expect(screen.queryByText(text) !== null).toBe(on);
      }
    },
  );

  it("乗り換えで作った経路と同じ道だったので選んだ候補は、一覧の名前で知らせ、その行を見える位置へ出す", () => {
    const scrolled = vi.spyOn(HTMLElement.prototype, "scrollIntoView");
    renderOutcome({ results: resultsOf({ generated: [FAST, SLOW], selectedRouteId: "slow", reusedRouteId: "slow" }) });

    expect(screen.getByText("作った組み合わせは「2」と同じ道なので、「2」を選びました")).toBeInTheDocument();
    expect(scrolled.mock.contexts).toEqual([screen.getByRole("tab", { name: /^2 / })]);
  });
});

describe("候補の一覧", () => {
  it("最速の印の無い生成は最速を分けず、番号・距離・時間・難易度の列だけで並べ、区切りの線も群の印も出さない", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST, SLOW] }) });
    expect(listTexts()).toEqual([HEADER, "1 10.0km 30分 難易度42", "2 20.0km +12分 難易度—"]);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("最速・生成した候補・合成がそろうと、その順に並べて群の間に線を引き、最速と合成は名前の列の印に意味を持ち、時間の列は最速の行と比べる", () => {
    // 合成の方が最速の行より速く見積もられても、比べる基準は最速の行のまま
    const edit: EditedRoute = {
      route: route("spliced-1", { distance_km: 12, estimated_duration_seconds: 1620 }),
      originId: "fast",
      number: 1,
    };
    renderOutcome({ results: resultsOf({ generated: [SLOW, { ...FAST, is_fastest: true }], edits: [edit] }) });
    expect(listTexts()).toEqual([
      HEADER,
      " 10.0km 30分 難易度42",
      "―",
      "1 20.0km +12分 難易度—",
      "―",
      "1 12.0km −3分 難易度—",
    ]);
    const [fastest, , spliced] = screen.getAllByRole("tab");
    expect(within(fastest).getByRole("img", { name: "最速ルート" })).toHaveAttribute("title", "最速ルート");
    expect(within(spliced).getByRole("img", { name: "合成ルート" })).toHaveAttribute("title", "合成ルート");
  });

  it.each([
    ["slow", /^2 /],
    [null, /^1 /],
  ])("選んだ候補（%s。無ければ先頭）のタブが選ばれている", (selectedRouteId, name) => {
    renderOutcome({ results: resultsOf({ generated: [FAST, SLOW], selectedRouteId }) });
    expect(screen.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true");
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

  it("編集で作ったルートには、元とその一覧での名前で「元との違い」を出し、「元を見る」で元のタブを選ぶ", async () => {
    const edited = route("spliced-1", { distance_km: 12 });
    const { results } = renderOutcome({
      results: resultsOf({
        generated: [FAST, SLOW],
        edits: [{ route: edited, originId: "slow", number: 1 }],
        selectedRouteId: edited.id,
      }),
    });
    const difference = screen.getByRole("region", { name: "元との違い" });
    expect(difference).toHaveTextContent("元: 2 20.0km");
    expect(difference).toHaveTextContent("距離−8.0km");
    await userEvent.click(within(difference).getByRole("button", { name: "元を見る" }));
    expect(results.selectTab).toHaveBeenCalledWith("slow");
  });

  it("生成した候補・元が一覧に無い編集には「元との違い」を出さない", () => {
    const orphan = route("spliced-1");
    renderOutcome({
      results: resultsOf({
        generated: [FAST],
        edits: [{ route: orphan, originId: "gone", number: 1 }],
        selectedRouteId: orphan.id,
      }),
    });
    expect(screen.queryByRole("region", { name: "元との違い" })).not.toBeInTheDocument();
  });

  it("区間のある候補に道のりのグラフを出し、横軸は一覧で最も長い候補の距離で、押した区間を示し、動かすとその区間を選ぶ", async () => {
    const first = makeRouteSegment({ distance_km: 1 });
    const second = makeRouteSegment({ distance_km: 1 });
    const { results } = renderOutcome({
      results: resultsOf({
        generated: [route("fast", { distance_km: 2, segments: [first, second] }), SLOW],
        selectedRouteSegment: { segment: second, latitude: 35, longitude: 139 },
      }),
    });
    const graph = screen.getByRole("slider", { name: /^道のりに沿った難易度/ });
    expect(graph).toHaveAttribute("aria-valuetext", "1.0 km地点");
    expect(screen.getByText("20.0km")).toBeInTheDocument();
    graph.focus();
    await userEvent.keyboard("{Home}");
    expect(results.selectSegment).toHaveBeenCalledWith(expect.objectContaining({ segment: first }));
  });

  it("区間を押していない間は、候補の総合難易度の内訳を出す", () => {
    const candidate = route("fast", { overall_difficulty: { average: 30, load: 300 } });
    renderOutcome({ results: resultsOf({ generated: [candidate] }) });
    expect(screen.getByText("総合難易度").parentElement).toHaveTextContent("総合難易度30/100");
    expect(screen.queryByRole("button", { name: "区間の選択を解除" })).not.toBeInTheDocument();
  });

  it("区間を押している間は、内訳の代わりに区間の地点・到達予想（日本時間）・風を出す", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST], selectedRouteSegment: segmentSelection() }) });
    expect(screen.getByText("3.3 km地点")).toBeInTheDocument();
    expect(screen.getByText("到達予想 09:42")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "総合難易度の説明" })).not.toBeInTheDocument();
    expect(screen.getByText(/^出発時点の風: .+ 3\.0m\/s$/)).toBeInTheDocument();
  });

  it.each([
    ["寄与のある", { difficulty: 12.4, axis_contributions: { axis_a: 12.4 } }, "12", false],
    ["寄与が全部0の", { difficulty: 0, axis_contributions: { axis_a: 0 } }, "0", true],
    ["算出できなかった", { difficulty: null, axis_contributions: {} }, "—", false],
  ])("%s区間は総合難易度を出し、全部0のときだけ0であることを文で言う", (_, segment, shown, allZero) => {
    renderOutcome({ results: resultsOf({ generated: [FAST], selectedRouteSegment: segmentSelection(segment) }) });

    expect(screen.getByText("総合難易度").parentElement).toHaveTextContent(`総合難易度${shown}/100`);
    expect(screen.queryByText("どの評価も0（易しい）") !== null).toBe(allZero);
  });

  it("区間の内訳のチップから開く詳細は、候補全体ではなくその区間の軸別難易度を出す", async () => {
    const candidate = route("fast", { axis_difficulties: { axis_a: 20, axis_b: 30 } });
    const selected = segmentSelection({
      axis_contributions: { axis_a: 12, axis_b: 5 },
      axis_difficulties: { axis_a: 72.4 },
    });
    renderOutcome({ results: resultsOf({ generated: [candidate], selectedRouteSegment: selected }) });
    await userEvent.click(await screen.findByRole("button", { name: "軸Aの詳細を表示" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("軸A軸別難易度 72/100");
    await userEvent.click(screen.getByRole("button", { name: "軸Aの詳細を隠す" }));
    await userEvent.click(screen.getByRole("button", { name: "軸Bの詳細を表示" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("軸Bデータなし");
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
    // 材料の値の行は「名前: 値」の文を自分で持つ（内訳のチップの行は文を持たない）。
    const materialLines = () =>
      screen.queryAllByText((content, element) => element?.tagName === "LI" && content !== "");
    expect(materialLines()).toHaveLength(0);
    unmount();

    setResearchEnabled(true);
    renderOutcome({ results: resultsOf({ generated: [FAST], selectedRouteSegment: selected }) });
    const lines = materialLines();
    expect(lines).toHaveLength(1);
    expect(lines[0].textContent?.startsWith(`${known.name}: 1.5`)).toBe(true);
  });

  it("編集している間は、一覧の代わりに編集面だけを出し、同じ道の候補は一覧の名前で渡す", () => {
    const panel: Splice["panel"] = {
      displayed: { ...FAST, edge_ids: ["e1"] },
      appliedCount: 0,
      hasAlternatives: true,
      onUndo: vi.fn(),
      onReset: vi.fn(),
      preview: null,
      sameRouteId: "slow",
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
    expect(screen.getByRole("region", { name: "区間の乗り換え" })).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.getByText("この組み合わせは「2」と同じ道です")).toBeInTheDocument();
  });
});

describe("研究モードの比較", () => {
  /** 回が無い間の比較表の案内。 */
  const COMPARISON_GUIDE = /その回の結果がここへ積まれます/;

  function slot(id: string, routePreference: Record<string, number>): ExperimentSlot {
    return {
      id,
      color: "",
      conditions: makeGenerationConditions({ route_preference: routePreference }),
      topCandidate: route(id, { axis_difficulties: { axis_a: 10, axis_b: 20, axis_c: 30 } }),
    };
  }

  it("研究モードでなければ比較タブを出さない", () => {
    renderOutcome({ results: resultsOf({ generated: [FAST] }) });
    expect(screen.queryByRole("tab", { name: "比較" })).not.toBeInTheDocument();
    expect(screen.queryByText(COMPARISON_GUIDE)).not.toBeInTheDocument();
  });

  it("比較タブを末尾に出し、開いていない間も比較表を描いておく", () => {
    setResearchEnabled(true);
    renderOutcome({ results: resultsOf({ generated: [FAST] }) });
    const tabs = screen.getAllByRole("tab");
    expect(tabs.at(-1)).toHaveTextContent("比較");
    expect(tabs.at(-1)).toHaveAttribute("aria-selected", "false");
    expect(screen.getByText(COMPARISON_GUIDE)).toBeInTheDocument();
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

  it("比較表には、どれかの回で重みが0より大きかった軸だけを並べる", async () => {
    setResearchEnabled(true);
    const slots = [slot("one", { axis_a: 0.5, axis_b: 0 }), slot("two", { axis_c: 0.2 })];
    renderOutcome({
      results: resultsOf({ generated: [FAST], comparisonTabActive: true }),
      generation: generationOf({ experimentSlots: slots }),
    });
    expect(await screen.findByRole("rowheader", { name: "軸A" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "軸C" })).toBeInTheDocument();
    expect(screen.queryByRole("rowheader", { name: "軸B" })).not.toBeInTheDocument();
  });
});
