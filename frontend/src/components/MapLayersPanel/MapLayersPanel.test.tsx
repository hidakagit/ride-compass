import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  buildMapLayers,
  buildRoadSurfaceSharedLayerIds,
  layerSectionDomId,
  type LayerDataStatusByLayer,
  type MapLayerId,
} from "@/components/Map/mapLayers";
import { RAMP_AXES } from "@/components/Map/axisLayers";
import { buildStaticFilterAxes } from "@/components/Map/staticAttributeLayers";

// 改善計画T308: 実運用ではpage.tsxがaxisCatalog（useAxisCatalog）由来のrampAxesを
// build*()へ渡すが、テストではビルド時静的フォールバック（RAMP_AXES、既存7軸）で十分。
const MAP_LAYERS = buildMapLayers(RAMP_AXES);
const ROAD_SURFACE_SHARED_LAYER_IDS = buildRoadSurfaceSharedLayerIds(RAMP_AXES);
const STATIC_FILTER_AXES = buildStaticFilterAxes(RAMP_AXES);
import MapLayersPanel from "./MapLayersPanel";
import styles from "./MapLayersPanel.module.css";

function baseProps() {
  return {
    layerVisibility: {
      elevation: false,
      roadType: false,
      roadSurface: false,
      "axis:car_stress": false,
      designation: false,
      tunnel: false,
      oneway: false,
      stopPoi: false,
      supplyPoi: false,
      accidents: false,
      route: false,
      precipitationNowcast: false,
      windVector: false,
      windAxis: false,
      gradientFill: false,
      gradientAxis: false,
      disaster: false,
    },
    onLayerToggle: vi.fn(),
    roadHiddenKeysByMode: { surface: [], highway: [] } as Record<"surface" | "highway", readonly string[]>,
    onRoadLegendToggle: vi.fn(),
    onRoadAxisSetHidden: vi.fn(),
    // car_stress（改善計画T292でramp軸化）はdesignation等と同じStaticFilterAxisId文字列
    // （axisIdそのもの、layerVisibility側の"axis:car_stress"とは別の値）を使う。
    staticFilterHiddenKeysByAxis: {
      car_stress: [],
      designation: [],
      tunnel: [],
      oneway: [],
      stopPoi: [],
      supplyPoi: [],
      accidentParty: [],
      accidentSeverity: [],
    } as Record<
      | "car_stress"
      | "designation"
      | "tunnel"
      | "oneway"
      | "stopPoi"
      | "supplyPoi"
      | "accidentParty"
      | "accidentSeverity",
      readonly string[]
    >,
    onStaticFilterLegendToggle: vi.fn(),
    onStaticFilterAxisSetHidden: vi.fn(),
    regionZoomTooWide: false,
    layerDataStatus: {} as LayerDataStatusByLayer,
    hasHiddenFilters: false,
    onClearAllFilters: vi.fn(),
    mapLayers: MAP_LAYERS,
    roadSurfaceSharedLayerIds: ROAD_SURFACE_SHARED_LAYER_IDS,
    staticFilterAxes: STATIC_FILTER_AXES,
  };
}

// 各レイヤーは折りたたみ（Disclosure/Radix Accordion、モバイル実機フィードバック対応T38）で
// デフォルト全閉のため、セクション内の凡例・絞り込み等（renderSectionBodyの出力）を検証する
// テストは先にこれで開く。見出しやON/OFFチップ（LayerChip）はトリガーの外に出ており閉じていても
// 常に見えるため開く必要はない。domIdはDisclosureのコンテナ（Root）に振られている
// （MapLayersPanel.tsx参照。以前はネイティブ<details>の.open書き換えだったが、T254の
// Radix Accordion化でコンテナ内のトリガー（button）を辿ってクリックする方式へ変更した）。
function openSection(id: MapLayerId) {
  // 生DOMの.click()ではなくfireEvent.click（act()で包まれる）を使う。ネイティブ<details>の
  // .open書き換えと違いRadix Accordionの開閉はReactのstate更新を伴うため、act()無しだと
  // 次のexpectまでに再描画が反映されないことがある。
  const button = document.getElementById(layerSectionDomId(id))?.querySelector("button");
  if (button) fireEvent.click(button);
}

// 個別セクションの開閉自体ではなく中身の挙動を検証する大半のテストのために、レンダー直後に
// 全セクションを開く一括版。Accordion.Triggerだけを`[aria-controls]`の有無で区別する
// （FieldLabelのPopover.Triggerも同じaria-expanded="false"を持つが、aria-controlsを
// 持たないため誤って開いてしまわない）。
function openAllSections() {
  document
    .querySelectorAll('button[aria-expanded="false"][aria-controls]')
    .forEach((button) => fireEvent.click(button));
}

// パネルの枠組み（レイヤーカタログからのセクション生成・表示チップ・凡例チェックの
// 出し分け）を見る。道路情報の絞り込みは即時反映（T31で旧RoadFilterEditorの
// 下書き→適用を廃止し、チェック方式へ統一）。「生成したルートの色分け」（route）は
// このパネルの対象外へ移設したため、そちらの挙動はpage.tsx側で検証する。
describe("MapLayersPanel", () => {
  // 改善計画T413（地図の見え方パネルのグルーピングを地図上チップ[T406]と統一）・T418
  // （評価軸グループの撤去）: 見出しは「道路/環境/スポット」（mapOverlayGroupFor）のみの
  // フラットな1階層。地図上チップ側が実機フィードバックでカテゴリ見出しを廃止した経緯
  // （改善計画T169）と揃え、こちらも中分類（category）の見出しは出さない（「地図の見え方と
  // 合わせて、中分類は不要」という実機フィードバック）。「生成したルートの色分け」
  // （route、どのグループにも属さない）は「ルートを作る」パネル（page.tsx参照）、評価軸
  // （軸スタジオ由来のレイヤー、car_stress等）はルート設定パネル（RouteSettingsPanel.tsx、
  // docs/tasks/T418.md）へそれぞれ移設し、このパネルの対象外になった。
  it("レイヤーカタログの全レイヤーが、グループ見出し（道路/スポット）のみのフラットな一覧としてセクションで並ぶ", () => {
    const { container } = render(<MapLayersPanel {...baseProps()} />);

    const groupHeadings = Array.from(container.querySelectorAll("h2")).map((h) => h.textContent);
    // 表示順は地図上チップと同じMAP_OVERLAY_GROUP_ORDER（道路→環境→スポット）をそのまま
    // 使う（旧「観測/推定」時代のパネル専用反転は廃止、mapLayers.tsのコメント参照）。
    // 降水ナウキャスト・風・雷・竜巻等dataNature="dynamic"のレイヤー、およびelevation
    // （hideFromLayersPanel、下記の別テスト参照）はこのパネルから撤去済みのため、
    // 「環境」グループはメンバーが1件も残らずグループ見出し自体が現れない
    // （MapLayersPanel.tsx: layers.length === 0のグループを描画しない分岐）。
    expect(groupHeadings).toEqual(["道路", "スポット"]);

    // 中分類（category）の見出しは出ない（.groupTitleはこのパネル自身はもう使わない、
    // page.tsx側の「生成したルートの色分け」だけが同じクラスを再利用している）。
    expect(container.querySelectorAll(`.${styles.groupTitle}`).length).toBe(0);

    // 各セクションに安定したDOM id（layerSectionDomId）が振られている（openSection参照）
    expect(container.querySelector("#map-layer-section-roadType")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-roadSurface")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-designation")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-tunnel")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-stopPoi")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-supplyPoi")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-accidents")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-route")).not.toBeInTheDocument();
    // 改善計画T418: 評価軸チップ自体を地図UIから撤去したため、axis:car_stress等の
    // 軸スタジオ由来レイヤーはこのパネルのどのセクションとしても現れない
    // （属性選択子で確認。コロンを含むIDはCSS ID選択子[#...]では壊れる）。
    expect(container.querySelector('[id="map-layer-section-axis:car_stress"]')).not.toBeInTheDocument();
  });

  // ユーザー判断（2026-08-25）: 降水ナウキャスト・風・雷・竜巻等dataNature="dynamic"の
  // レイヤーは他のレイヤーと違い、凡例の帯単位で表示/非表示を切り替える絞り込み機能を持たない
  // （降水の直近60分・雷・竜巻は気象庁配信の完成画像のみで生データがフロントに来ない
  // ため技術的に困難、風のみ限定的に可能だが「仕様を統一する」ため実装しない判断）。
  // 絞り込み機能が無い以上このパネルに出しても「表示」トグル以外に意味のある操作が
  // 無いため、丸ごと撤去した（ON/OFFは地図上チップで引き続き操作できる、各レイヤーの
  // 説明文はMapOverlayControls.tsxの▶パネルへ移設——MapOverlayControls.test.tsx参照）。
  // 改善計画T413でグループ再編後もこの除外自体は変更していない。
  it("dataNature=dynamicのレイヤー（降水ナウキャスト・風・災害）は行が表示されない", () => {
    const { container } = render(<MapLayersPanel {...baseProps()} />);

    expect(container.querySelector("#map-layer-section-precipitationNowcast")).not.toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-windVector")).not.toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-disaster")).not.toBeInTheDocument();
  });

  // ユーザー指摘（2026-08-31）: elevation（標高図）はラスタタイルのため他レイヤーのような
  // 凡例ベースの絞り込みができず、ON/OFFのみで完結する（地図上チップ側で操作できる）。
  // dataNature="dynamic"ではない（静的データのため）が、上のdynamicレイヤーと同じ理由
  // （絞り込み機能を持たずこのパネルへ掲載する価値が無い）でhideFromLayersPanelにより
  // 個別に除外される（mapLayers.ts: MapLayerDescriptor.hideFromLayersPanel参照）。
  it("hideFromLayersPanel=trueのレイヤー（標高図）は行が表示されない", () => {
    const { container } = render(<MapLayersPanel {...baseProps()} />);

    expect(container.querySelector("#map-layer-section-elevation")).not.toBeInTheDocument();
  });

  // 改善計画T413: mapOverlayGroupForの判定どおり、道路の純粋な属性（roadType/roadSurface/
  // designation）は「道路」、点レイヤー（accidents/stopPoi/supplyPoi）は「スポット」に属する。
  // 以前はcar_stress以外の全レイヤーが単一の「観測」グループへ一緒くたに入っていた
  // （地図上チップ側は既にT406でこの分類だったため、パネルとチップで所属グループの語彙が
  // 食い違っていた）。「環境」（terrain/weather）に属するレイヤーは全てdataNature=
  // "dynamic"またはhideFromLayersPanelでこのパネルから除外されるため、確認対象に含めない
  // （上記の別テスト参照。「環境」グループ見出し自体が現れないことは冒頭のテストで確認済み）。
  it("レイヤーが地図上チップ（mapOverlayGroupFor）と同じグループの下に属する", () => {
    render(<MapLayersPanel {...baseProps()} />);

    function overlayGroupTitleFor(layerId: string): string | null {
      const section = document.getElementById(`map-layer-section-${layerId}`);
      const group = section?.closest(`.${styles.overlayGroup}`);
      return group?.querySelector(`.${styles.overlayGroupTitle}`)?.textContent ?? null;
    }

    expect(overlayGroupTitleFor("roadType")).toBe("道路");
    expect(overlayGroupTitleFor("roadSurface")).toBe("道路");
    expect(overlayGroupTitleFor("designation")).toBe("道路");
    expect(overlayGroupTitleFor("accidents")).toBe("スポット");
    expect(overlayGroupTitleFor("stopPoi")).toBe("スポット");
    expect(overlayGroupTitleFor("supplyPoi")).toBe("スポット");
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
    openAllSections();
    openSection("designation");

    expect(screen.getByText("緊急輸送道路[N10]")).toBeInTheDocument();
    expect(screen.getByText("重要物流道路[N12]")).toBeInTheDocument();
    expect(screen.getByText("緊急輸送 かつ 重要物流道路[N10＋N12]")).toBeInTheDocument();
  });

  it("事故レイヤーのセクションに凡例（自転車関連/その他）が表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();
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
          elevation: false,
          roadType: false,
          roadSurface: false,
          "axis:car_stress": false,
          designation: false,
          tunnel: true,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          windAxis: false,
      gradientFill: false,
      gradientAxis: false,
          disaster: false,
        }}
        onLayerToggle={onLayerToggle}
      />,
    );

    expect(screen.getByRole("button", { name: "トンネルレイヤーを表示" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "路面の種類レイヤーを表示" })).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: "路面の種類レイヤーを表示" }));
    expect(onLayerToggle).toHaveBeenCalledWith("roadSurface", true);

    await user.click(screen.getByRole("button", { name: "トンネルレイヤーを表示" }));
    expect(onLayerToggle).toHaveBeenCalledWith("tunnel", false);
  });

  it("チップ操作は所属するセクションの開閉状態を変えない", async () => {
    const user = userEvent.setup();
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();

    const section = document.getElementById(layerSectionDomId("tunnel")) as HTMLElement;
    const trigger = within(section).getByRole("button", { name: "トンネル" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.click(screen.getByRole("button", { name: "トンネルレイヤーを表示" }));

    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("路面の種類OFFのときはOFF案内が出て、絞り込みチェックはOFF中でも操作できる", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();
    openSection("roadSurface");
    // OFF案内の文言はT63で他レイヤーにも共通化されたため、セクション内に絞って確認する
    const section = document.getElementById(layerSectionDomId("roadSurface")) as HTMLElement;
    expect(within(section).getByText(/絞り込みを操作すると自動でONになります/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeInTheDocument();
  });

  it("絞り込みチェックの操作でonRoadLegendToggleが呼ばれ、レイヤーOFFなら自動でONになる", async () => {
    const user = userEvent.setup();
    const onRoadLegendToggle = vi.fn();
    const onLayerToggle = vi.fn();
    render(<MapLayersPanel {...baseProps()} onRoadLegendToggle={onRoadLegendToggle} onLayerToggle={onLayerToggle} />);
    openSection("roadSurface");

    await user.click(screen.getByRole("checkbox", { name: /アスファルト/ }));

    expect(onRoadLegendToggle).toHaveBeenCalledWith("surface", "asphalt");
    expect(onLayerToggle).toHaveBeenCalledWith("roadSurface", true);
  });

  it("「すべて隠す」で軸の全カテゴリキーがonRoadAxisSetHiddenへ渡る", async () => {
    const user = userEvent.setup();
    const onRoadAxisSetHidden = vi.fn();
    render(<MapLayersPanel {...baseProps()} onRoadAxisSetHidden={onRoadAxisSetHidden} />);
    openSection("roadSurface");

    // 改善計画T165で路面の種類・道路の種類は別セクションへ分かれたため、
    // 「路面の種類」セクション内の「すべて隠す」ボタンへスコープする。
    const section = document.getElementById(layerSectionDomId("roadSurface")) as HTMLElement;
    await user.click(within(section).getByRole("button", { name: "すべて隠す" }));

    expect(onRoadAxisSetHidden).toHaveBeenCalledWith("surface", [
      "asphalt",
      "concrete",
      "stones",
      "gravel",
      "dirt",
      "unknown",
    ]);
  });

  it("路面の種類ON && regionZoomTooWide=trueのときズーム警告が表示される（絞り込みは操作可能なまま）", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          roadType: false,
          roadSurface: true,
          "axis:car_stress": false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          windAxis: false,
      gradientFill: false,
      gradientAxis: false,
          disaster: false,
        }}
        regionZoomTooWide={true}
      />,
    );
    openSection("roadSurface");
    expect(screen.getByText("表示範囲が広すぎます。ズームインしてください。")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeInTheDocument();
  });

  it("改善計画T87: 表示ONのレイヤーでlayerDataStatusがerrorのとき取得失敗の案内とチップの状態ドットが出る", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          roadType: false,
          roadSurface: false,
          "axis:car_stress": false,
          designation: true,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          windAxis: false,
      gradientFill: false,
      gradientAxis: false,
          disaster: false,
        }}
        layerDataStatus={{ designation: "error" }}
      />,
    );
    openSection("designation");
    expect(screen.getByText(/データの取得に失敗しました/)).toBeInTheDocument();
  });

  it("改善計画T87: layerDataStatusがemptyのとき「表示できるデータがありません」の案内が出る", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          roadType: false,
          roadSurface: false,
          "axis:car_stress": false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: true,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          windAxis: false,
      gradientFill: false,
      gradientAxis: false,
          disaster: false,
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
        layerDataStatus={{ designation: "error" }}
      />,
    );
    openSection("designation");
    expect(screen.queryByText(/データの取得に失敗しました/)).not.toBeInTheDocument();
  });

  it("改善計画T87: 路面の種類でregionZoomTooWide中はデータ状態の案内を出さない（ズーム警告と二重表示しない）", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          roadType: false,
          roadSurface: true,
          "axis:car_stress": false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          windAxis: false,
      gradientFill: false,
      gradientAxis: false,
          disaster: false,
        }}
        regionZoomTooWide={true}
        layerDataStatus={{ roadSurface: "empty" }}
      />,
    );
    openSection("roadSurface");
    expect(screen.getByText("表示範囲が広すぎます。ズームインしてください。")).toBeInTheDocument();
    expect(screen.queryByText("この範囲に表示できるデータがありません")).not.toBeInTheDocument();
  });

  it("改善計画T87レビュー指摘: regionZoomTooWide中はroad_surface共有レイヤーのヘッダーチップにも状態ドット/ツールチップを出さない", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          roadType: true,
          roadSurface: true,
          "axis:car_stress": false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          windAxis: false,
      gradientFill: false,
      gradientAxis: false,
          disaster: false,
        }}
        regionZoomTooWide={true}
        layerDataStatus={{ roadSurface: "empty" }}
      />,
    );
    const roadChip = screen.getByRole("button", { name: "路面の種類レイヤーを表示" });
    expect(roadChip.title).not.toContain("この範囲に表示できるデータがありません");
    expect(roadChip.querySelector("span[aria-hidden]")).not.toBeInTheDocument();
  });

  it("改善計画T87レビュー指摘: road_surface非共有レイヤー（stopPoi）はregionZoomTooWideの影響を受けない", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          roadType: false,
          roadSurface: false,
          "axis:car_stress": false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: true,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          windAxis: false,
      gradientFill: false,
      gradientAxis: false,
          disaster: false,
        }}
        regionZoomTooWide={true}
        layerDataStatus={{ stopPoi: "empty" }}
      />,
    );
    openSection("stopPoi");
    expect(screen.getByText("この範囲に表示できるデータがありません")).toBeInTheDocument();
  });

  // 改善計画T165: 「道路情報」が路面の種類・道路の種類の別セクションへ分かれたため、
  // それぞれの軸見出しは自分のセクションにだけ表示されることを別テストで確認する。
  it("路面の種類ONのとき色の軸見出しが表示される", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          roadType: false,
          roadSurface: true,
          "axis:car_stress": false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          windAxis: false,
      gradientFill: false,
      gradientAxis: false,
          disaster: false,
        }}
      />,
    );
    openSection("roadSurface");
    expect(screen.getByText(/色：路面の種類/)).toBeInTheDocument();
    expect(screen.queryByText("表示範囲が広すぎます。ズームインしてください。")).not.toBeInTheDocument();
  });

  it("道路の種類ONのとき太さの軸見出しが表示される", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          roadType: true,
          roadSurface: false,
          "axis:car_stress": false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          windAxis: false,
      gradientFill: false,
      gradientAxis: false,
          disaster: false,
        }}
      />,
    );
    openSection("roadType");
    expect(screen.getByText(/太さ：道路の種類/)).toBeInTheDocument();
    expect(screen.queryByText("表示範囲が広すぎます。ズームインしてください。")).not.toBeInTheDocument();
  });

  it("非表示中のカテゴリはチェックが外れた状態で表示される", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          roadType: true,
          roadSurface: true,
          "axis:car_stress": false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          windAxis: false,
      gradientFill: false,
      gradientAxis: false,
          disaster: false,
        }}
        roadHiddenKeysByMode={{ surface: ["gravel"], highway: [] }}
      />,
    );
    openSection("roadSurface");
    expect(screen.getByRole("checkbox", { name: /砂利・締固め/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeChecked();
  });

  it("停止要因POIの凡例（種別ごとの色分け）が表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();
    openSection("stopPoi");
    expect(screen.getByText("信号")).toBeInTheDocument();
    expect(screen.getByText("踏切")).toBeInTheDocument();
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
          car_stress: [],
          designation: [],
          stopPoi: [],
          supplyPoi: [],
          accidentParty: [],
          accidentSeverity: ["nonfatal"],
        }}
      />,
    );
    openSection("accidents");
    expect(screen.getByRole("checkbox", { name: "死亡事故以外" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "死亡事故" })).toBeChecked();
  });

});
