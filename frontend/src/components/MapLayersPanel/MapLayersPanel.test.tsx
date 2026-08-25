import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  MAP_LAYERS,
  ROAD_SURFACE_SHARED_LAYER_IDS,
  layerSectionDomId,
  type LayerDataStatusByLayer,
  type MapLayerId,
} from "@/components/Map/mapLayers";
import { SECONDARY_AXES } from "@/components/Map/secondaryAxes";
import MapLayersPanel from "./MapLayersPanel";
import styles from "./MapLayersPanel.module.css";

function baseProps() {
  return {
    layerVisibility: {
      elevation: false,
      roadType: false,
      roadSurface: false,
      "axis:car_stress": false,
      bicycleInfra: false,
      designation: false,
      tunnel: false,
      oneway: false,
      stopPoi: false,
      supplyPoi: false,
      accidents: false,
      route: false,
      precipitationNowcast: false,
      windVector: false,
      thunderNowcast: false,
      tornadoNowcast: false,
    },
    onLayerToggle: vi.fn(),
    roadHiddenKeysByMode: { surface: [], highway: [] } as Record<"surface" | "highway", readonly string[]>,
    onRoadLegendToggle: vi.fn(),
    onRoadAxisSetHidden: vi.fn(),
    // car_stress（改善計画T292でramp軸化）はbicycleInfra等と同じStaticFilterAxisId文字列
    // （axisIdそのもの、layerVisibility側の"axis:car_stress"とは別の値）を使う。
    staticFilterHiddenKeysByAxis: {
      car_stress: [],
      bicycleInfra: [],
      designation: [],
      tunnel: [],
      oneway: [],
      stopPoi: [],
      supplyPoi: [],
      accidentParty: [],
      accidentSeverity: [],
    } as Record<
      | "car_stress"
      | "bicycleInfra"
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
    // 改善計画T308: 実運用ではpage.tsxがaxisCatalog（useAxisCatalog）由来の値を渡すが、
    // テストでは静的フォールバック（既存7軸）で十分。
    mapLayers: MAP_LAYERS,
    roadSurfaceSharedLayerIds: ROAD_SURFACE_SHARED_LAYER_IDS,
    secondaryAxes: SECONDARY_AXES,
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
// （情報アイコンのrenderHintToggleボタンやFieldLabelのPopover.Triggerも同じ
// aria-expanded="false"を持つが、いずれもaria-controlsを持たないため誤って開いてしまわない。
// 「セクションを開いただけでは説明は見えない」ことを検証するテスト自体は個別にopenSectionを
// 使う）。
function openAllSections() {
  document
    .querySelectorAll('button[aria-expanded="false"][aria-controls]')
    .forEach((button) => fireEvent.click(button));
}

// 各メンバーの説明（panelHint、改善計画: 実機フィードバック「各メンバーの説明は、情報
// アイコン（！）を押したら見えるようにして」への対応）は情報アイコンを押すまで本文が
// DOMに出ない。openSectionでセクション自体を開いたうえで、このヘルパーで「{label}の説明を
// 表示」ボタンを押してから説明文を検証する。
function openHint(subjectLabel: string) {
  fireEvent.click(screen.getByRole("button", { name: `${subjectLabel}の説明を表示` }));
}

// パネルの枠組み（レイヤーカタログからのセクション生成・表示チップ・凡例チェックの
// 出し分け）を見る。道路情報の絞り込みは即時反映（T31で旧RoadFilterEditorの
// 下書き→適用を廃止し、チェック方式へ統一）。「生成したルートの色分け」（route）は
// このパネルの対象外へ移設したため、そちらの挙動はpage.tsx側で検証する。
describe("MapLayersPanel", () => {
  // 改善計画（地図の見え方パネルのグルーピングを地図上チップと統一。T171で3値目
  // 「動的」を追加）: 見出しは次数（観測/推定/動的）のみのフラットな1階層。地図上チップ側が
  // 実機フィードバックでカテゴリ見出しを廃止した経緯（改善計画T169）と揃え、こちらも
  // 中分類（category）の見出しは出さない（「地図の見え方と合わせて、中分類は不要」という
  // 実機フィードバック）。「生成したルートの色分け」（route、次数を持たない）はこのパネルの
  // 対象外へ移設した（「ルートを作る」パネル、page.tsx参照）。
  it("レイヤーカタログの全レイヤーが、次数見出し（観測/推定/動的）のみのフラットな一覧としてセクションで並ぶ", () => {
    const { container } = render(<MapLayersPanel {...baseProps()} />);

    const natureHeadings = Array.from(container.querySelectorAll("h2")).map((h) => h.textContent);
    // パネル内は観測を推定より上にする（実機フィードバック「推定指標よりも観測指標を
    // 上にして」への対応。地図チップ側の「推定→観測」順とはあえて独立させている、
    // mapLayers.ts: MAP_LAYER_DATA_NATURE_ORDERのコメント参照）。動的は末尾。
    expect(natureHeadings).toEqual(["観測データ", "推定指標（合成）", "動的データ"]);

    // 中分類（category）の見出しは出ない（.groupTitleはこのパネル自身はもう使わない、
    // page.tsx側の「生成したルートの色分け」だけが同じクラスを再利用している）。
    expect(container.querySelectorAll(`.${styles.groupTitle}`).length).toBe(0);

    // 各セクションに安定したDOM id（layerSectionDomId）が振られている（openSection参照）
    expect(container.querySelector("#map-layer-section-elevation")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-roadType")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-roadSurface")).toBeInTheDocument();
    // axis:car_stressはコロンを含むためCSS ID選択子（#...）では壊れる。属性選択子で確認する。
    expect(container.querySelector('[id="map-layer-section-axis:car_stress"]')).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-bicycleInfra")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-designation")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-tunnel")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-stopPoi")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-supplyPoi")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-accidents")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-precipitationNowcast")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-route")).not.toBeInTheDocument();
  });

  it("レイヤーが想定した次数グループの下に属する", () => {
    render(<MapLayersPanel {...baseProps()} />);

    function natureTitleFor(layerId: string): string | null {
      // axis:car_stressのようなコロンを含むIDはCSS ID選択子（#...）では壊れるため
      // getElementByIdで引く（属性値としては通常のCSS.escape不要な安全な経路）。
      const section = document.getElementById(`map-layer-section-${layerId}`);
      const nature = section?.closest(`.${styles.natureGroup}`);
      return nature?.querySelector(`.${styles.natureTitle}`)?.textContent ?? null;
    }

    // axis:car_stressのみ推定指標（合成）、他は観測データ（車ストレスは車の圧迫感の材料から
    // 合成した推定指標、mapLayers.ts参照）
    expect(natureTitleFor("axis:car_stress")).toBe("推定指標（合成）");
    expect(natureTitleFor("roadType")).toBe("観測データ");
    expect(natureTitleFor("roadSurface")).toBe("観測データ");
    expect(natureTitleFor("designation")).toBe("観測データ");
    expect(natureTitleFor("accidents")).toBe("観測データ");
    expect(natureTitleFor("stopPoi")).toBe("観測データ");
    expect(natureTitleFor("supplyPoi")).toBe("観測データ");
    expect(natureTitleFor("bicycleInfra")).toBe("観測データ");
    expect(natureTitleFor("elevation")).toBe("観測データ");
    // 改善計画T171: 降水ナウキャストは3値目「動的」に属する。
    expect(natureTitleFor("precipitationNowcast")).toBe("動的データ");
  });

  // 実機フィードバック「推定指標の上から数えた順番を地図上の左から数えた順番と一致させて」
  // への対応。地図チップの推定グループは軸カタログ順（SECONDARY_AXES＝axis-catalog.json由来、
  // 勾配・舗装質・停止密度・車の圧迫感・夜間・事故密度）で横並びに展開されるため、
  // パネル側もこの順を再現する（以前はcategory順で、地図チップの並びと食い違っていた）。
  it("推定グループの並び順が地図チップの並び（勾配・舗装質・停止密度・車の圧迫感・夜間・事故密度）と一致する", () => {
    const { container } = render(<MapLayersPanel {...baseProps()} />);
    const compositeHeading = Array.from(container.querySelectorAll("h2")).find(
      (h) => h.textContent === "推定指標（合成）",
    );
    const compositeGroup = compositeHeading?.closest(`.${styles.natureGroup}`);
    expect(compositeGroup).toBeTruthy();
    const titles = Array.from(compositeGroup!.querySelectorAll("h3")).map((h) => h.textContent);
    expect(titles).toEqual(["勾配", "舗装質", "停止密度", "車の圧迫感", "夜間", "事故密度"]);
  });

  // 実機フィードバック「各メンバーの説明は、情報アイコン（！）を押したら見えるようにして」
  // への対応。以前はセクションを開く（<details>）だけで説明文（panelHint）が常に見えており、
  // 車ストレスの8行に及ぶ判定内訳などが常時表示されて読みにくいという指摘につながっていた。
  it("レイヤーの説明はセクションを開いただけでは見えず、情報アイコンを押すと表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();
    openSection("elevation");
    expect(screen.queryByText("国土地理院の色別標高図を重ねる")).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "標高図の説明を表示" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);

    expect(screen.getByText("国土地理院の色別標高図を重ねる")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "標高図の説明を隠す" })).toHaveAttribute("aria-expanded", "true");
  });

  // 改善計画T171: 降水ナウキャストは絞り込みUIを持たないため、elevationと同じ専用case
  // （説明の情報アイコンのみ、「絞り込みを操作すると自動でON」案内は出さない）で表示される。
  // 表示時刻は地図上の時刻スライダー（page.tsx）で操作する、このパネルの対象外の機構。
  it("降水ナウキャストのセクションが表示され、説明が出るがOFF案内（絞り込み用）は出ない", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();
    openSection("precipitationNowcast");
    openHint("降水ナウキャスト");

    expect(screen.getByText(/気象庁の高解像度降水ナウキャストです/)).toBeInTheDocument();
    const section = document.getElementById(layerSectionDomId("precipitationNowcast")) as HTMLElement;
    expect(within(section).queryByText(/絞り込みを操作すると自動でONになります/)).not.toBeInTheDocument();
  });

  // 実機フィードバック「地図上でグレー表示のものも展開だけさせず存在させて」への対応。
  // 専用の表示レイヤーを持たない軸（勾配。材料gradient_percentがタイル非依存のため
  // 改善計画T278の自動導出対象外）は、地図チップではタップ不能の灰色タイルとして存在する
  // 一方、以前のパネルはMapLayerId自体を持たないため一覧から完全に抜け落ちていた。
  // 設定項目もON/OFFも無いため、他レイヤーのような開閉式セクションではなく常時見える
  // 案内行として存在させる。
  it("専用の表示レイヤーを持たない推定軸（勾配）は開閉式にせず、情報アイコンを押すと案内文が見える", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();

    // 改善計画T202: 案内文は先頭に「（地図表示なし）」が付く（統合レビュー2026-08-22指摘、
    // 展開せずとも「押せない行がなぜあるのか」が伝わるようにするための接頭辞）ため、
    // 完全一致ではなく部分一致（正規表現）で検証する。
    expect(screen.queryByText(/標高レイヤーで確認できます/)).not.toBeInTheDocument();
    openHint("勾配");
    expect(screen.getByText(/標高レイヤーで確認できます/)).toBeInTheDocument();
  });

  // 改善計画T278: surface_q・nightは材料（surface_good・no_lit/has_tunnel）がMVTタイルへ
  // 焼き込み済みのためkind="ramp"の自動導出表示を持つようになり、以前の「専用レイヤー無し」
  // 案内行（proxy）から、他のramp軸（停止密度・事故密度）と同じ実レイヤーセクション
  // （ON/OFFチップ付き）へ変わった。
  it("改善計画T278でramp表示になった舗装質・夜間は、他のレイヤーと同じON/OFFチップ付きセクションとして表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();

    expect(screen.getByRole("button", { name: "舗装質レイヤーを表示" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "夜間レイヤーを表示" })).toBeInTheDocument();
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
          elevation: true,
          roadType: false,
          roadSurface: false,
          "axis:car_stress": false,
          bicycleInfra: false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          thunderNowcast: false,
          tornadoNowcast: false,
        }}
        onLayerToggle={onLayerToggle}
      />,
    );

    expect(screen.getByRole("button", { name: "標高図レイヤーを表示" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "路面の種類レイヤーを表示" })).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: "路面の種類レイヤーを表示" }));
    expect(onLayerToggle).toHaveBeenCalledWith("roadSurface", true);

    await user.click(screen.getByRole("button", { name: "標高図レイヤーを表示" }));
    expect(onLayerToggle).toHaveBeenCalledWith("elevation", false);
  });

  it("チップ操作は所属するセクションの開閉状態を変えない", async () => {
    const user = userEvent.setup();
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();

    const section = document.getElementById(layerSectionDomId("elevation")) as HTMLElement;
    const trigger = within(section).getByRole("button", { name: "標高図" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.click(screen.getByRole("button", { name: "標高図レイヤーを表示" }));

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
          bicycleInfra: false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          thunderNowcast: false,
          tornadoNowcast: false,
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
          "axis:car_stress": true,
          bicycleInfra: false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          thunderNowcast: false,
          tornadoNowcast: false,
        }}
        layerDataStatus={{ "axis:car_stress": "error" }}
      />,
    );
    openSection("axis:car_stress");
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
          bicycleInfra: false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: true,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          thunderNowcast: false,
          tornadoNowcast: false,
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
        layerDataStatus={{ "axis:car_stress": "error" }}
      />,
    );
    openSection("axis:car_stress");
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
          bicycleInfra: false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          thunderNowcast: false,
          tornadoNowcast: false,
        }}
        regionZoomTooWide={true}
        layerDataStatus={{ roadSurface: "empty" }}
      />,
    );
    openSection("roadSurface");
    expect(screen.getByText("表示範囲が広すぎます。ズームインしてください。")).toBeInTheDocument();
    expect(screen.queryByText("この範囲に表示できるデータがありません")).not.toBeInTheDocument();
  });

  it("改善計画T87レビュー指摘: road_surfaceタイルを共有するaxis:car_stressも、regionZoomTooWide中はデータ状態の案内を出さない", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{
          elevation: false,
          roadType: false,
          roadSurface: false,
          "axis:car_stress": true,
          bicycleInfra: false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          thunderNowcast: false,
          tornadoNowcast: false,
        }}
        regionZoomTooWide={true}
        layerDataStatus={{ "axis:car_stress": "empty" }}
      />,
    );
    openSection("axis:car_stress");
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
          bicycleInfra: false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          thunderNowcast: false,
          tornadoNowcast: false,
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
          bicycleInfra: false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: true,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          thunderNowcast: false,
          tornadoNowcast: false,
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
          bicycleInfra: false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          thunderNowcast: false,
          tornadoNowcast: false,
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
          bicycleInfra: false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          thunderNowcast: false,
          tornadoNowcast: false,
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
          bicycleInfra: false,
          designation: false,
          tunnel: false,
          oneway: false,
          stopPoi: false,
          supplyPoi: false,
          accidents: false,
          route: false,
          precipitationNowcast: false,
          windVector: false,
          thunderNowcast: false,
          tornadoNowcast: false,
        }}
        roadHiddenKeysByMode={{ surface: ["gravel"], highway: [] }}
      />,
    );
    openSection("roadSurface");
    expect(screen.getByRole("checkbox", { name: /砂利・締固め/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeChecked();
  });

  // 改善計画T292: 車ストレス（車の圧迫感）は専用Pythonレシピの廃止に伴い、他の推定軸
  // （停止密度・事故密度等）と同じ汎用ramp機構へ統合された。専用の5段階panelHintDetail
  // （加点/減点の箇条書き内訳）は廃止され、mapLayers.ts: RAMP_AXIS_PANEL_HINTSの
  // 単一の説明文（ramp軸共通の形）に置き換わった。
  it("車の圧迫感の凡例に判定基準の説明が表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();
    openSection("axis:car_stress");
    openHint("車の圧迫感");
    expect(screen.getByText(/道路種別・自転車インフラ・制限速度・車線数・指定路線・自動車通行可否から推定した/)).toBeInTheDocument();
  });

  // 「不明」がしきい値段階と並ぶ数値段階に見えないよう、区切り線付きの専用クラスで
  // 分離する（legendFilter.ts: LegendEntry.isFallback）。車の圧迫感はhighway材料が
  // 未登録の道路種別（path/footway等）で「不明」になる（axis_display.py参照）。
  it("車の圧迫感の凡例で「不明」はしきい値段階と区切って表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();
    openSection("axis:car_stress");
    const section = document.getElementById(layerSectionDomId("axis:car_stress")) as HTMLElement;
    const fallbackLabel = within(section).getByText("不明");
    const row = fallbackLabel.closest("label");
    expect(row?.className).toMatch(/legendCheckboxRowFallback/);
  });

  it("自転車インフラの凡例に道路情報（路面）との違いの説明が表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();
    openSection("bicycleInfra");
    openHint("自転車インフラ");
    expect(screen.getByText(/「路面の種類」レイヤーの/)).toBeInTheDocument();
  });

  it("停止要因POIの凡例（種別ごとの色分け）が表示される", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();
    openSection("stopPoi");
    expect(screen.getByText("信号")).toBeInTheDocument();
    expect(screen.getByText("踏切")).toBeInTheDocument();
  });

  // 改善計画T63: 道路情報以外の絞り込み可能レイヤー（車ストレス・自転車インフラ・停止要因POI・
  // 事故）も、OFF中の案内・凡例チェックボックスの絞り込み操作・自動ONが道路情報と
  // 同じ挙動になったことを検証する。
  it("車ストレスOFFのときはOFF案内が出て、絞り込みチェックはOFF中でも操作できる", () => {
    render(<MapLayersPanel {...baseProps()} />);
    openAllSections();
    openSection("axis:car_stress");
    // OFF案内の文言は他レイヤーとも共通のため、セクション内に絞って確認する
    const section = document.getElementById(layerSectionDomId("axis:car_stress")) as HTMLElement;
    expect(within(section).getByText(/絞り込みを操作すると自動でONになります/)).toBeInTheDocument();
    // 車の圧迫感のrampしきい値[2,3,4]（registry_defaults.py参照）の最下段バンドラベル。
    expect(screen.getByRole("checkbox", { name: "2未満" })).toBeInTheDocument();
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
          bicycleInfra: [],
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
