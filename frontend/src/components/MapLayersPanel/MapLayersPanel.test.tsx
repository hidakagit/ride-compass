import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { layerSectionDomId, type LayerDataStatusByLayer, type MapLayerId } from "@/components/Map/mapLayers";
import MapLayersPanel from "./MapLayersPanel";
import styles from "./MapLayersPanel.module.css";

function baseProps() {
  return {
    layerVisibility: {
      elevation: false,
      road: false,
      trafficStress: false,
      bicycleInfra: false,
      designation: false,
      stopPoi: false,
      accidents: false,
      route: false,
    },
    onLayerToggle: vi.fn(),
    roadHiddenKeysByMode: { surface: [], highway: [] } as Record<"surface" | "highway", readonly string[]>,
    onRoadLegendToggle: vi.fn(),
    onRoadAxisSetHidden: vi.fn(),
    staticFilterHiddenKeysByAxis: {
      trafficStress: [],
      bicycleInfra: [],
      designation: [],
      stopPoi: [],
      accidentParty: [],
      accidentSeverity: [],
    } as Record<
      "trafficStress" | "bicycleInfra" | "designation" | "stopPoi" | "accidentParty" | "accidentSeverity",
      readonly string[]
    >,
    onStaticFilterLegendToggle: vi.fn(),
    onStaticFilterAxisSetHidden: vi.fn(),
    regionZoomTooWide: false,
    layerDataStatus: {} as LayerDataStatusByLayer,
    routeStyleModeId: "wind" as const,
    onRouteStyleModeChange: vi.fn(),
    hiddenRouteLegendKeys: [] as string[],
    onRouteLegendToggle: vi.fn(),
    hasDetail: false,
    hasHiddenFilters: false,
    onClearAllFilters: vi.fn(),
  };
}

// 各レイヤーは折りたたみ（<details>、モバイル実機フィードバック対応T38）でデフォルト全閉のため、
// セクション内の凡例・絞り込み等（renderSectionBodyの出力）を検証するテストは先にこれで開く。
// 見出し（h3）やON/OFFチップ（LayerChip）は<summary>直下にあり閉じていても常に見えるため
// 開く必要はない。
function openSection(id: MapLayerId) {
  const details = document.getElementById(layerSectionDomId(id));
  if (details instanceof HTMLDetailsElement) details.open = true;
}

// パネルの枠組み（レイヤーカタログからのセクション生成・表示チップ・凡例チェックの
// 出し分け・ルートの色分け選択）を見る。道路情報の絞り込みは即時反映（T31で
// 旧RoadFilterEditorの下書き→適用を廃止し、ルート凡例と同じチェック方式へ統一）。
describe("MapLayersPanel", () => {
  it("レイヤーカタログの全レイヤーが、中分類ごとのグループ見出しの下にセクションとして並ぶ(改善計画T86)", () => {
    const { container } = render(<MapLayersPanel {...baseProps()} />);

    // "自転車インフラ"はグループ見出しとレイヤー名（h3）の両方に現れるため、見出し（h2）に
    // 絞って確認する。
    const headings = Array.from(container.querySelectorAll("h2")).map((h) => h.textContent);
    expect(headings).toEqual(["道路状態", "交通・安全", "自転車インフラ", "地形", "生成したルートの色分け"]);
    // 各セクションに安定したDOM id（layerSectionDomId）が振られている（openSection参照）
    expect(container.querySelector("#map-layer-section-elevation")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-road")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-trafficStress")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-bicycleInfra")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-designation")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-stopPoi")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-accidents")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-route")).toBeInTheDocument();
  });

  it("レイヤーが想定した中分類グループの下に属する(改善計画T86)", () => {
    const { container } = render(<MapLayersPanel {...baseProps()} />);

    function groupTitleFor(layerId: string): string | null {
      const section = container.querySelector(`#map-layer-section-${layerId}`);
      const group = section?.closest(`.${styles.group}`);
      return group?.querySelector(`.${styles.groupTitle}`)?.textContent ?? null;
    }

    expect(groupTitleFor("road")).toBe("道路状態");
    expect(groupTitleFor("designation")).toBe("道路状態");
    expect(groupTitleFor("trafficStress")).toBe("交通・安全");
    expect(groupTitleFor("accidents")).toBe("交通・安全");
    expect(groupTitleFor("stopPoi")).toBe("交通・安全");
    expect(groupTitleFor("bicycleInfra")).toBe("自転車インフラ");
    expect(groupTitleFor("elevation")).toBe("地形");
    expect(groupTitleFor("route")).toBe("生成したルートの色分け");
  });

  it("絞り込み中の軸が無ければ「絞り込みを一括クリア」ボタンは出ず、あれば出て押すとonClearAllFiltersが呼ばれる", async () => {
    const user = userEvent.setup();
    const onClearAllFilters = vi.fn();
    const { rerender } = render(
      <MapLayersPanel {...baseProps()} hasHiddenFilters={false} onClearAllFilters={onClearAllFilters} />,
    );
    expect(screen.queryByRole("button", { name: "絞り込みを一括クリア" })).not.toBeInTheDocument();

    rerender(<MapLayersPanel {...baseProps()} hasHiddenFilters={true} onClearAllFilters={onClearAllFilters} />);
    await user.click(screen.getByRole("button", { name: "絞り込みを一括クリア" }));
    expect(onClearAllFilters).toHaveBeenCalledTimes(1);
  });

  it("「絞り込みを一括クリア」ボタンはhasHiddenFiltersの値に関わらずDOM上に常駐する（レイアウトシフト防止の回帰テスト）", () => {
    // 実機バグ: 条件付きレンダリングでこの行が出現/消失すると、パネル内の他のボタン
    // （レイヤーの表示トグル等）が上下にずれ、直後のクリックが別要素に当たる誤操作を
    // Playwrightで実測確認した。visibility制御なら高さは常に確保されずれない。
    const { container, rerender } = render(<MapLayersPanel {...baseProps()} hasHiddenFilters={false} />);
    const buttonWhenHidden = container.querySelector('button[type="button"][disabled]');
    expect(buttonWhenHidden).not.toBeNull();
    expect(buttonWhenHidden?.textContent).toBe("絞り込みを一括クリア");

    rerender(<MapLayersPanel {...baseProps()} hasHiddenFilters={true} />);
    const buttonWhenVisible = screen.getByRole("button", { name: "絞り込みを一括クリア" });
    expect(buttonWhenVisible).toBeEnabled();
  });

  it("指定路線レイヤーのセクションに凡例（緊急輸送道路/重要物流道路/両方該当）が表示される(外部静的データソース T51、改善計画T74)", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openSection("designation");

    expect(screen.getByText("緊急輸送道路（N10）")).toBeInTheDocument();
    expect(screen.getByText("重要物流道路（N12）")).toBeInTheDocument();
    expect(screen.getByText("緊急輸送道路 かつ 重要物流道路[N10・N12]")).toBeInTheDocument();
  });

  it("事故レイヤーのセクションに凡例（自転車関連/その他）が表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openSection("accidents");

    expect(screen.getByText("自転車関連")).toBeInTheDocument();
    expect(screen.getByText("その他")).toBeInTheDocument();
  });

  it("各レイヤーの表示チップは閉じたセクションでも見え、ON/OFF状態をaria-pressedで反映し、操作でonLayerToggleが呼ばれる", async () => {
    const user = userEvent.setup();
    const onLayerToggle = vi.fn();
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: true,
          road: false,
          trafficStress: false,
          bicycleInfra: false,
          designation: false,
          stopPoi: false,
          accidents: false,
          route: false,
        }}
        onLayerToggle={onLayerToggle}
      />,
    );

    expect(screen.getByRole("button", { name: "標高図レイヤーを表示" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "道路情報レイヤーを表示" })).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: "道路情報レイヤーを表示" }));
    expect(onLayerToggle).toHaveBeenCalledWith("road", true);

    await user.click(screen.getByRole("button", { name: "標高図レイヤーを表示" }));
    expect(onLayerToggle).toHaveBeenCalledWith("elevation", false);
  });

  it("チップ操作は所属するセクションの開閉状態を変えない", async () => {
    const user = userEvent.setup();
    render(<MapLayersPanel {...baseProps()} />);

    const details = document.getElementById(layerSectionDomId("elevation")) as HTMLDetailsElement;
    expect(details.open).toBe(false);

    await user.click(screen.getByRole("button", { name: "標高図レイヤーを表示" }));

    expect(details.open).toBe(false);
  });

  it("道路情報OFFのときはOFF案内が出て、絞り込みチェックはOFF中でも操作できる", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openSection("road");
    // OFF案内の文言はT63で他レイヤーにも共通化されたため、セクション内に絞って確認する
    const section = document.getElementById(layerSectionDomId("road")) as HTMLElement;
    expect(within(section).getByText(/絞り込みを操作すると自動でONになります/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeInTheDocument();
  });

  it("絞り込みチェックの操作でonRoadLegendToggleが呼ばれ、レイヤーOFFなら自動でONになる", async () => {
    const user = userEvent.setup();
    const onRoadLegendToggle = vi.fn();
    const onLayerToggle = vi.fn();
    render(<MapLayersPanel {...baseProps()} onRoadLegendToggle={onRoadLegendToggle} onLayerToggle={onLayerToggle} />);
    openSection("road");

    await user.click(screen.getByRole("checkbox", { name: /アスファルト/ }));

    expect(onRoadLegendToggle).toHaveBeenCalledWith("surface", "asphalt");
    expect(onLayerToggle).toHaveBeenCalledWith("road", true);
  });

  it("「すべて隠す」で軸の全カテゴリキーがonRoadAxisSetHiddenへ渡る", async () => {
    const user = userEvent.setup();
    const onRoadAxisSetHidden = vi.fn();
    render(<MapLayersPanel {...baseProps()} onRoadAxisSetHidden={onRoadAxisSetHidden} />);
    openSection("road");

    // 一括ボタンは軸ごとにあるため、1つ目（色＝路面の種類の軸）を操作する
    await user.click(screen.getAllByRole("button", { name: "すべて隠す" })[0]);

    expect(onRoadAxisSetHidden).toHaveBeenCalledWith("surface", [
      "asphalt",
      "concrete",
      "stones",
      "gravel",
      "dirt",
      "unknown",
    ]);
  });

  it("道路情報ON && regionZoomTooWide=trueのときズーム警告が表示される（絞り込みは操作可能なまま）", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          road: true,
          trafficStress: false,
          bicycleInfra: false,
          designation: false,
          stopPoi: false,
          accidents: false,
          route: false,
        }}
        regionZoomTooWide={true}
      />,
    );
    openSection("road");
    expect(screen.getByText("表示範囲が広すぎます。ズームインしてください。")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeInTheDocument();
  });

  it("改善計画T87: 表示ONのレイヤーでlayerDataStatusがerrorのとき取得失敗の案内とチップの状態ドットが出る", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          road: false,
          trafficStress: true,
          bicycleInfra: false,
          designation: false,
          stopPoi: false,
          accidents: false,
          route: false,
        }}
        layerDataStatus={{ trafficStress: "error" }}
      />,
    );
    openSection("trafficStress");
    expect(screen.getByText(/データの取得に失敗しました/)).toBeInTheDocument();
  });

  it("改善計画T87: layerDataStatusがemptyのとき「表示できるデータがありません」の案内が出る", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          road: false,
          trafficStress: false,
          bicycleInfra: false,
          designation: false,
          stopPoi: true,
          accidents: false,
          route: false,
        }}
        layerDataStatus={{ stopPoi: "empty" }}
      />,
    );
    openSection("stopPoi");
    expect(screen.getByText("この範囲に表示できるデータがありません")).toBeInTheDocument();
  });

  it("改善計画T87: レイヤーが表示OFFのときはlayerDataStatusに値があっても案内を出さない", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerDataStatus={{ trafficStress: "error" }}
      />,
    );
    openSection("trafficStress");
    expect(screen.queryByText(/データの取得に失敗しました/)).not.toBeInTheDocument();
  });

  it("改善計画T87: 道路情報でregionZoomTooWide中はデータ状態の案内を出さない（ズーム警告と二重表示しない）", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          road: true,
          trafficStress: false,
          bicycleInfra: false,
          designation: false,
          stopPoi: false,
          accidents: false,
          route: false,
        }}
        regionZoomTooWide={true}
        layerDataStatus={{ road: "empty" }}
      />,
    );
    openSection("road");
    expect(screen.getByText("表示範囲が広すぎます。ズームインしてください。")).toBeInTheDocument();
    expect(screen.queryByText("この範囲に表示できるデータがありません")).not.toBeInTheDocument();
  });

  it("改善計画T87レビュー指摘: road_surfaceタイルを共有するtrafficStressも、regionZoomTooWide中はデータ状態の案内を出さない", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          road: false,
          trafficStress: true,
          bicycleInfra: false,
          designation: false,
          stopPoi: false,
          accidents: false,
          route: false,
        }}
        regionZoomTooWide={true}
        layerDataStatus={{ trafficStress: "empty" }}
      />,
    );
    openSection("trafficStress");
    expect(screen.queryByText("この範囲に表示できるデータがありません")).not.toBeInTheDocument();
  });

  it("改善計画T87レビュー指摘: regionZoomTooWide中はroad_surface共有レイヤーのヘッダーチップにも状態ドット/ツールチップを出さない", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          road: true,
          trafficStress: false,
          bicycleInfra: false,
          designation: false,
          stopPoi: false,
          accidents: false,
          route: false,
        }}
        regionZoomTooWide={true}
        layerDataStatus={{ road: "empty" }}
      />,
    );
    const roadChip = screen.getByRole("button", { name: "道路情報レイヤーを表示" });
    expect(roadChip.title).not.toContain("この範囲に表示できるデータがありません");
    expect(roadChip.querySelector("span[aria-hidden]")).not.toBeInTheDocument();
  });

  it("改善計画T87レビュー指摘: road_surface非共有レイヤー（stopPoi）はregionZoomTooWideの影響を受けない", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          road: false,
          trafficStress: false,
          bicycleInfra: false,
          designation: false,
          stopPoi: true,
          accidents: false,
          route: false,
        }}
        regionZoomTooWide={true}
        layerDataStatus={{ stopPoi: "empty" }}
      />,
    );
    openSection("stopPoi");
    expect(screen.getByText("この範囲に表示できるデータがありません")).toBeInTheDocument();
  });

  it("道路情報ONのとき色・太さ両方の軸見出しが表示される", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          road: true,
          trafficStress: false,
          bicycleInfra: false,
          designation: false,
          stopPoi: false,
          accidents: false,
          route: false,
        }}
      />,
    );
    openSection("road");
    expect(screen.getByText(/色：路面の種類/)).toBeInTheDocument();
    expect(screen.getByText(/太さ：道路の種類/)).toBeInTheDocument();
    expect(screen.queryByText("表示範囲が広すぎます。ズームインしてください。")).not.toBeInTheDocument();
  });

  it("非表示中のカテゴリはチェックが外れた状態で表示される", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          road: true,
          trafficStress: false,
          bicycleInfra: false,
          designation: false,
          stopPoi: false,
          accidents: false,
          route: false,
        }}
        roadHiddenKeysByMode={{ surface: ["gravel"], highway: [] }}
      />,
    );
    openSection("road");
    expect(screen.getByRole("checkbox", { name: /砂利・締固め/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeChecked();
  });

  it("交通ストレスの凡例に判定基準の説明が表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openSection("trafficStress");
    expect(screen.getByText(/4段階（1=快適〜4=ストレス大）/)).toBeInTheDocument();
  });

  // 改善計画T89: 「ストレス1〜5評価基準が分かりにくい」という実機フィードバック対応。
  // 1〜2文の要約だけでは加点/減点の内訳が伝わらなかったため、panelHintDetail（箇条書き）で補う。
  it("交通ストレスの凡例に加点/減点の内訳が箇条書きで表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openSection("trafficStress");
    expect(screen.getByText(/制限速度30km\/h以下: -1/)).toBeInTheDocument();
    expect(screen.getByText(/車線数4以上: \+1/)).toBeInTheDocument();
    expect(screen.getByText(/指定路線.*に該当: \+1/)).toBeInTheDocument();
  });

  // 「不明・他」が1〜4と並ぶ5番目の数値段階に見え「1〜5評価」と誤解される実機フィードバックを
  // 受け、区切り線付きの専用クラスで分離する（legendFilter.ts: LegendEntry.isFallback）。
  it("交通ストレスの凡例で「不明・他」は数値段階と区切って表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openSection("trafficStress");
    const section = document.getElementById(layerSectionDomId("trafficStress")) as HTMLElement;
    const fallbackLabel = within(section).getByText("不明・他（判定対象外の道路種別）");
    const row = fallbackLabel.closest("label");
    expect(row?.className).toMatch(/legendCheckboxRowFallback/);
  });

  it("自転車インフラの凡例に道路情報（路面）との違いの説明が表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openSection("bicycleInfra");
    expect(screen.getByText(/道路情報レイヤーの/)).toBeInTheDocument();
  });

  it("停止要因POIの凡例（種別ごとの色分け）が表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openSection("stopPoi");
    expect(screen.getByText("信号")).toBeInTheDocument();
    expect(screen.getByText("踏切")).toBeInTheDocument();
  });

  // 改善計画T63: 道路情報以外の絞り込み可能レイヤー（交通ストレス・自転車インフラ・停止要因POI・
  // 事故）も、OFF中の案内・凡例チェックボックスの絞り込み操作・自動ONが道路情報と
  // 同じ挙動になったことを検証する。
  it("交通ストレスOFFのときはOFF案内が出て、絞り込みチェックはOFF中でも操作できる", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openSection("trafficStress");
    // OFF案内の文言は他レイヤーとも共通のため、セクション内に絞って確認する
    const section = document.getElementById(layerSectionDomId("trafficStress")) as HTMLElement;
    expect(within(section).getByText(/絞り込みを操作すると自動でONになります/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "1（快適）" })).toBeInTheDocument();
  });

  it("事故のセクションは当事者・重大度の2軸が別々の見出しで表示され、死亡事故だけの絞り込みができる", async () => {
    const user = userEvent.setup();
    const onStaticFilterLegendToggle = vi.fn();
    render(<MapLayersPanel {...baseProps()} onStaticFilterLegendToggle={onStaticFilterLegendToggle} />);
    openSection("accidents");

    expect(screen.getByText("当事者")).toBeInTheDocument();
    expect(screen.getByText("重大度")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "死亡事故" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "死亡事故以外" })).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "死亡事故以外" }));
    expect(onStaticFilterLegendToggle).toHaveBeenCalledWith("accidentSeverity", "nonfatal");
  });

  it("事故の非表示中カテゴリ（重大度）はチェックが外れた状態で表示される", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        staticFilterHiddenKeysByAxis={{
          trafficStress: [],
          bicycleInfra: [],
          designation: [],
          stopPoi: [],
          accidentParty: [],
          accidentSeverity: ["nonfatal"],
        }}
      />,
    );
    openSection("accidents");
    expect(screen.getByRole("checkbox", { name: "死亡事故以外" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "死亡事故" })).toBeChecked();
  });

  it("hasDetail=falseのときルート欄は案内のみで、表示チップも非活性", () => {
    render(<MapLayersPanel {...baseProps()} hasDetail={false} />);
    openSection("route");
    expect(screen.getByText(/ルートを生成・選択すると使えます/)).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "ルートの色分け" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ルートレイヤーを表示" })).toBeDisabled();
  });

  it("hasDetail=falseの案内からonGoToGenerateで「ルートを作る」へ誘導できる", async () => {
    const user = userEvent.setup();
    const onGoToGenerate = vi.fn();
    render(<MapLayersPanel {...baseProps()} hasDetail={false} onGoToGenerate={onGoToGenerate} />);
    openSection("route");

    await user.click(screen.getByRole("button", { name: "「ルートを作る」へ" }));

    expect(onGoToGenerate).toHaveBeenCalled();
  });

  it("hasDetail=trueのときルートのモード選択・凡例チェックボックスが表示される", () => {
    render(<MapLayersPanel {...baseProps()} hasDetail={true} />);
    openSection("route");
    expect(screen.getByRole("radio", { name: "風の影響" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("checkbox", { name: /易しい/ })).toBeInTheDocument();
  });

  it("ルートのモード選択でonRouteStyleModeChangeが呼ばれ、レイヤーOFFなら自動でONにする", async () => {
    const user = userEvent.setup();
    const onRouteStyleModeChange = vi.fn();
    const onLayerToggle = vi.fn();
    render(
      <MapLayersPanel
        {...baseProps()}
        hasDetail={true}
        layerVisibility={{
          elevation: false,
          road: false,
          trafficStress: false,
          bicycleInfra: false,
          designation: false,
          stopPoi: false,
          accidents: false,
          route: false,
        }}
        onRouteStyleModeChange={onRouteStyleModeChange}
        onLayerToggle={onLayerToggle}
      />,
    );
    openSection("route");

    await user.click(screen.getByRole("radio", { name: "勾配" }));

    expect(onRouteStyleModeChange).toHaveBeenCalledWith("gradient");
    expect(onLayerToggle).toHaveBeenCalledWith("route", true);
  });

  it("ルートのモード選択時、レイヤーが既にONならonLayerToggleは呼ばれない", async () => {
    const user = userEvent.setup();
    const onLayerToggle = vi.fn();
    render(
      <MapLayersPanel
        {...baseProps()}
        hasDetail={true}
        layerVisibility={{
          elevation: false,
          road: false,
          trafficStress: false,
          bicycleInfra: false,
          designation: false,
          stopPoi: false,
          accidents: false,
          route: true,
        }}
        onLayerToggle={onLayerToggle}
      />,
    );
    openSection("route");

    await user.click(screen.getByRole("radio", { name: "勾配" }));

    expect(onLayerToggle).not.toHaveBeenCalled();
  });

  it("ルートの凡例チェックボックス操作でonRouteLegendToggleが呼ばれる", async () => {
    const user = userEvent.setup();
    const onRouteLegendToggle = vi.fn();
    render(
      <MapLayersPanel
        {...baseProps()}
        hasDetail={true}
        routeStyleModeId="gradient"
        onRouteLegendToggle={onRouteLegendToggle}
      />,
    );
    openSection("route");

    await user.click(screen.getByRole("checkbox", { name: /下り/ }));

    expect(onRouteLegendToggle).toHaveBeenCalledWith("downhill");
  });
});
