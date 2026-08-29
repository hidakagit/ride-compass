import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MapOverlayControls, { type OverlayLayerChip } from "./MapOverlayControls";

function baseLayers(): OverlayLayerChip[] {
  return [
    { id: "elevation", label: "標高図", on: false },
    { id: "roadSurface", label: "路面", on: false },
    { id: "route", label: "ルート", on: false },
  ];
}

function baseProps() {
  return {
    layers: baseLayers(),
    onToggle: vi.fn(),
  };
}

// 凡例・絞り込み編集・色分けモード選択などの「細かな設定」はすべてサイドバー側
// （MapLayersPanel.test.tsx）で検証する。ここは地図の上に残った最小限の要素
// （ON/OFFチップと▶で開く凡例パネル）だけを見る。このコンポーネントはレイヤー固有の
// 知識を持たない汎用描画係のため、テストもpropsで渡した表示状態の反映のみを確認する。
//
// 改善計画T406: baseLayers()のレイヤーはどれもcategoryを持たないため（単独チップの
// まま）、以下の基本テスト自体は旧「観測/推定/動的」時代から変更不要（category未指定の
// レイヤーの扱いは今回の再編と無関係）。
describe("MapOverlayControls", () => {
  // グループの開閉・表示項目の設定はlocalStorageへ永続化される（ユーザー要望「次開いた時に
  // 同じ状態にして」）。前のテストで書き込まれた値が次のテストの初期状態に漏れないよう、
  // 各テストの前に消し込む。
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("各チップがON状態をaria-pressedで反映する", () => {
    const layers = baseLayers().map((layer) => ({ ...layer, on: true }));
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    expect(screen.getByRole("button", { name: "標高図" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "路面" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "ルート" })).toHaveAttribute("aria-pressed", "true");
  });

  it("チップのクリックでonToggleがレイヤーIDと現在値の反転で呼ばれる", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const layers = baseLayers();
    layers[1].on = true; // 路面だけON
    render(<MapOverlayControls {...baseProps()} layers={layers} onToggle={onToggle} />);

    await user.click(screen.getByRole("button", { name: "標高図" }));
    expect(onToggle).toHaveBeenCalledWith("elevation", true);

    await user.click(screen.getByRole("button", { name: "路面" }));
    expect(onToggle).toHaveBeenCalledWith("roadSurface", false);
  });

  // 全レイヤー一括OFFボタンは地図下部中央の時刻スライダー隣へ移設し、page.tsx
  // （handleClearAllLayers）が持つようになったため、このコンポーネント自体はもう
  // 描画しない（実機フィードバック「左上の全クリアアイコンをスライドバーの左側に
  // 移動して」、MapOverlayControls.module.css参照）。

  it("disabledのチップは押せず、on=trueでもaria-pressedはfalseのまま", () => {
    const layers = baseLayers();
    layers[2] = { ...layers[2], on: true, disabled: true };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    const routeChip = screen.getByRole("button", { name: "ルート" });
    expect(routeChip).toBeDisabled();
    expect(routeChip).toHaveAttribute("aria-pressed", "false");
  });

  it("legendDetailsがあれば絞り込み中でなくても▶が出て、開くと軸ごとの全カテゴリ内訳が出る", async () => {
    const user = userEvent.setup();
    const layers = baseLayers();
    layers[1] = {
      ...layers[1],
      on: true,
      summary: null, // 絞り込み無し
      legendDetails: [
        {
          label: "路面の種類",
          legend: [
            { key: "asphalt", label: "アスファルト", color: "#16a34a", filter: ["literal", true] },
            { key: "concrete", label: "コンクリート", color: "#0d9488", filter: ["literal", true] },
          ],
          hiddenKeys: [],
        },
      ],
    };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    const toggle = screen.getByRole("button", { name: "路面の凡例を表示" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("アスファルト")).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    // 軸見出し・非表示カテゴリを含む全カテゴリがそれ単体で読める形で出る（1行要約は出さない）
    expect(screen.getByText("路面の種類")).toBeInTheDocument();
    expect(screen.getByText("アスファルト")).toBeInTheDocument();
    expect(screen.getByText("コンクリート")).toBeInTheDocument();
    expect(screen.queryByText(/路面:/)).not.toBeInTheDocument();
  });

  it("絞り込み中は非表示カテゴリに「非表示」バッジが付く", async () => {
    const user = userEvent.setup();
    const layers = baseLayers();
    layers[1] = {
      ...layers[1],
      on: true,
      summary: "コンクリート以外",
      legendDetails: [
        {
          label: "路面の種類",
          legend: [
            { key: "asphalt", label: "アスファルト", color: "#16a34a", filter: ["literal", true] },
            { key: "concrete", label: "コンクリート", color: "#0d9488", filter: ["literal", true] },
          ],
          hiddenKeys: ["concrete"],
        },
      ],
    };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);
    await user.click(screen.getByRole("button", { name: "路面の凡例を表示" }));

    expect(screen.getByText("非表示")).toBeInTheDocument();
    // 1行要約テキストそのものは表示しない（▶を押した本人には自明という実機フィードバック対応）
    expect(screen.queryByText("コンクリート以外")).not.toBeInTheDocument();
  });

  it("legendDetailsが空でもsummaryがあれば▶が出て、開くと案内文が出る", async () => {
    const user = userEvent.setup();
    const layers = baseLayers();
    layers[1] = { ...layers[1], on: true, summary: "ズームインすると表示されます", legendDetails: [] };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    const toggle = screen.getByRole("button", { name: "路面の凡例を表示" });
    await user.click(toggle);
    expect(screen.getByText("ズームインすると表示されます")).toBeInTheDocument();
  });

  it("OFF・disabled・凡例無しのレイヤーには▶が出ない", () => {
    const layers: OverlayLayerChip[] = [
      { id: "elevation", label: "標高図", on: true, summary: null, legendDetails: [] }, // 凡例無し
      { id: "roadSurface", label: "路面", on: false, summary: null, legendDetails: [{ label: "路面の種類", legend: [], hiddenKeys: [] }] }, // OFF
      { id: "route", label: "ルート", on: true, disabled: true, summary: "色分け: 風の影響" }, // disabled
    ];
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    expect(screen.queryByRole("button", { name: "標高図の凡例を表示" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "路面の凡例を表示" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ルートの凡例を表示" })).not.toBeInTheDocument();
  });

  // 最上位グループ束ね（改善計画T406、旧「次数束ね」T166を全面再編、T418で評価軸グループを
  // 撤去）: 旧「観測/推定/動的」（データの出自による3分類）を廃止し、「対象（何についての
  // 情報か）」で束ね直した「道路/環境/スポット」の3グループになった（docs/tasks/T400.md
  // 「1. パネルの最上位グルーピング」節、docs/tasks/T418.md）。mapOverlayGroupFor()
  // （mapLayers.ts）の判定規則:
  // - 道路: category==="roadCondition"
  // - 環境: category==="terrain"||"weather"
  // - スポット: category==="trafficSafety"||"amenity"
  // - 軸スタジオ由来のレイヤー（isAxisStudioLayer、dataNature==="composite"またはid===
  //   "windAxis"）はどのグループにも属さず、単独チップとしても出ない（下記
  //   「軸スタジオ由来レイヤーの撤去（改善計画T418）」参照）
  // - それ以外どれにも該当しない（category未指定、route等）は単独チップのまま
  describe("最上位グループ束ね（改善計画T406/T418）", () => {
    function groupedLayers(): OverlayLayerChip[] {
      return [
        { id: "route", label: "ルート", on: false }, // どのグループにも属さない→単独のまま
        { id: "roadType", label: "道路の種類", on: false, category: "roadCondition" },
        { id: "designation", label: "指定路線", on: true, category: "roadCondition" },
        { id: "axis:car_stress", label: "車の圧迫感", on: true, category: "trafficSafety", dataNature: "composite" },
        { id: "accidents", label: "事故地点", on: false, category: "trafficSafety" }, // dataNature省略→composite以外扱い
        { id: "elevation", label: "標高図", on: false, category: "terrain" },
      ];
    }

    it("道路（roadCondition）・環境（terrain/weather）・スポット（trafficSafety/amenity）へそれぞれ束ねられ、個別ボタンは出ない。軸スタジオ由来（composite）は単独チップとしても出ない", () => {
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      expect(screen.getByRole("button", { name: "ルート" })).toBeInTheDocument(); // どのグループにも属さない単独チップ
      expect(screen.queryByRole("button", { name: "道路の種類" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "指定路線" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "車の圧迫感" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "事故地点" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "標高図" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "道路" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "評価軸" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "環境" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "スポット" })).toBeInTheDocument();
    });

    it("チップ列は道路→環境→スポット→ルートの順で並ぶ（docs/tasks/T400.mdの記載順のうち評価軸を除いたもの）", () => {
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      const names = screen
        .getAllByRole("button", { name: /^(道路|環境|スポット|ルート)$/ })
        .map((el) => el.textContent);
      expect(names).toEqual(["道路", "環境", "スポット", "ルート"]);
    });
  });

  // 軸スタジオ由来レイヤーの撤去（改善計画T418）: ramp軸（dataNature==="composite"）・
  // windAxisは、評価軸チップ自体が地図UIから撤去されたため、単独チップとしても
  // 復活しない（buildChipGroupsのisAxisStudioLayer除外、mapLayers.ts参照）。
  describe("軸スタジオ由来レイヤーの撤去（改善計画T418）", () => {
    it("ramp軸（dataNature=composite）はどのグループにも束ねられず、単独チップとしても出ない", () => {
      const layers: OverlayLayerChip[] = [
        { id: "route", label: "ルート", on: false },
        { id: "axis:car_stress", label: "車の圧迫感", on: true, category: "trafficSafety", dataNature: "composite" },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      expect(screen.getByRole("button", { name: "ルート" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "車の圧迫感" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "評価軸" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "スポット" })).not.toBeInTheDocument();
    });

    it("windAxisはどのグループにも束ねられず、単独チップとしても出ない", () => {
      const layers: OverlayLayerChip[] = [
        { id: "route", label: "ルート", on: false },
        {
          id: "windAxis",
          label: "風（評価軸）",
          chipLabel: "風軸",
          on: false,
          category: "weather",
          dataNature: "dynamic",
        },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      expect(screen.getByRole("button", { name: "ルート" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "風軸" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "評価軸" })).not.toBeInTheDocument();
      // windAxis以外にメンバーが無いため環境グループ自体も出ない
      expect(screen.queryByRole("button", { name: "環境" })).not.toBeInTheDocument();
    });
  });

  // 道路グループ（改善計画T406、旧「観測データ」group:rawのうちroadCondition部分を継承）。
  // 挙動・構成は旧観測グループと同一（▼縦積み・地続き展開、表示項目設定パネル、凡例排他等）。
  describe("道路グループ（改善計画T406）", () => {
    function roadLayers(): OverlayLayerChip[] {
      return [
        { id: "elevation", label: "標高図", on: false, category: "terrain" }, // 環境グループ側の対照用
        { id: "roadType", label: "道路の種類", on: false, category: "roadCondition" },
        { id: "designation", label: "指定路線", on: true, category: "roadCondition" },
      ];
    }

    it("道路グループを開いても内訳を囲むカード（サブフレーム）は出ず、メンバーはチップ列と同じ階層の兄弟要素として並ぶ", async () => {
      const user = userEvent.setup();
      const { container } = render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);

      await user.click(screen.getByRole("button", { name: "道路" }));
      expect(container.querySelector('[class*="detailPanelBase"]')).not.toBeInTheDocument();

      const roadButton = screen.getByRole("button", { name: "道路" });
      const designationButton = screen.getByRole("button", { name: "指定路線" });
      expect(roadButton.closest('[class*="chipRowItem"]')?.parentElement).toBe(
        designationButton.closest('[class*="chipRowItem"]')?.parentElement
      );
    });

    it("ONのメンバーもグループ色分けクラス(iconChipGroupRoad)を保持したままiconChipActiveが付く", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);
      await user.click(screen.getByRole("button", { name: "道路" }));
      const designationButton = screen.getByRole("button", { name: "指定路線" });
      expect(designationButton.className).toMatch(/iconChipGroupRoad/);
      expect(designationButton.className).toMatch(/iconChipActive/);
    });

    it("道路見出しは折りたたみ時iconChipExpandedを持たず、展開するとgroupHeaderChip+iconChipGroupRoad+iconChipExpandedの組み合わせになる", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);
      const roadButton = screen.getByRole("button", { name: "道路" });
      expect(roadButton.className).toMatch(/groupHeaderChip/);
      expect(roadButton.className).toMatch(/iconChipGroupRoad/);
      expect(roadButton.className).not.toMatch(/iconChipExpanded/);

      await user.click(roadButton);
      expect(roadButton.className).toMatch(/groupHeaderChip/);
      expect(roadButton.className).toMatch(/iconChipGroupRoad/);
      expect(roadButton.className).toMatch(/iconChipExpanded/);
    });

    it("道路グループを開くとcategory小見出しを出さずメンバーのON/OFFボタンがフラットに並ぶ", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "道路" }));
      const designationToggle = screen.getByRole("button", { name: "指定路線" });
      expect(designationToggle).toHaveAttribute("aria-pressed", "true");

      await user.click(designationToggle);
      expect(onToggle).toHaveBeenCalledWith("designation", false);
      // 環境グループの標高図は道路グループに含まれない
      expect(screen.queryByRole("button", { name: "標高図" })).not.toBeInTheDocument();
    });

    it("グループチップ自体はメンバーのON状態を表すaria-pressedを持たず、展開状態のaria-expandedだけを持つ", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);
      const roadButton = screen.getByRole("button", { name: "道路" });
      expect(roadButton).not.toHaveAttribute("aria-pressed");
      expect(roadButton).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByRole("button", { name: /道路の凡例を/ })).not.toBeInTheDocument();

      await user.click(roadButton);
      expect(roadButton).toHaveAttribute("aria-expanded", "true");
    });

    it("折りたたみ中だけ見出しの脇に「表示項目を設定」ボタンが出て、展開すると消える", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);

      const settingsToggle = screen.getByRole("button", { name: "道路の表示項目を設定" });
      expect(settingsToggle).toBeInTheDocument();

      await user.click(settingsToggle);
      expect(screen.queryByRole("button", { name: "指定路線" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "道路" })).toHaveAttribute("aria-expanded", "false");
      expect(screen.getByText("道路の種類")).toBeInTheDocument();
      expect(screen.getByText("指定路線")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "道路" }));
      expect(screen.getByRole("button", { name: "指定路線" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "道路の表示項目を設定" })).not.toBeInTheDocument();
    });

    it("表示項目の設定で非表示に選ぶと、グループを開いてもそのメンバーだけが出ない", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);

      await user.click(screen.getByRole("button", { name: "道路の表示項目を設定" }));
      await user.click(screen.getByRole("button", { name: "指定路線を表示しない" }));
      await user.click(screen.getByRole("button", { name: "道路" }));
      expect(screen.queryByRole("button", { name: "指定路線" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "道路の種類" })).toBeInTheDocument(); // 他は影響なし
    });

    it("表示項目の設定で非表示に選ぶと、そのレイヤーがONなら即座にOFFにされる", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "道路の表示項目を設定" }));
      await user.click(screen.getByRole("button", { name: "指定路線を表示しない" }));
      expect(onToggle).toHaveBeenCalledWith("designation", false);
    });

    it("非表示を解除してもレイヤーは自動でONにならない", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "道路の表示項目を設定" }));
      await user.click(screen.getByRole("button", { name: "指定路線を表示しない" }));
      onToggle.mockClear();

      await user.click(screen.getByRole("button", { name: "指定路線を表示する" }));
      expect(onToggle).not.toHaveBeenCalled();
    });

    it("表示項目設定で、説明文(panelHint)を持つ項目には情報アイコンが出て、押すと説明文が開閉する", async () => {
      const user = userEvent.setup();
      const layers: OverlayLayerChip[] = [
        {
          id: "designation",
          label: "指定路線",
          on: false,
          category: "roadCondition",
          panelHint: "これはテスト用の説明文です。",
        },
        { id: "roadType", label: "道路の種類", on: false, category: "roadCondition" }, // panelHint未設定
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      await user.click(screen.getByRole("button", { name: "道路の表示項目を設定" }));

      const infoButton = screen.getByRole("button", { name: "指定路線の説明を表示" });
      expect(infoButton).toBeInTheDocument();
      expect(screen.queryByText("これはテスト用の説明文です。")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "道路の種類の説明を表示" })).not.toBeInTheDocument();

      await user.click(infoButton);
      expect(screen.getByText("これはテスト用の説明文です。")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "指定路線の説明を隠す" })).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "指定路線の説明を隠す" }));
      expect(screen.queryByText("これはテスト用の説明文です。")).not.toBeInTheDocument();
    });

    it("画面下端に近い位置で設定パネルを開くと、パネルのmaxHeightが利用可能な高さに収まるよう縮む", async () => {
      const user = userEvent.setup();
      vi.spyOn(window, "innerHeight", "get").mockReturnValue(768);
      vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
        top: 700,
        bottom: 700,
        left: 10,
        right: 50,
        width: 40,
        height: 0,
        x: 10,
        y: 700,
        toJSON: () => ({}),
      });
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);

      await user.click(screen.getByRole("button", { name: "道路の表示項目を設定" }));
      const panel = document.querySelector('[class*="detailPanel"]') as HTMLElement;
      expect(panel).toBeTruthy();
      expect(panel.style.maxHeight).toBe("120px");

      vi.restoreAllMocks();
    });

    it("グループの開閉状態と表示項目の設定はlocalStorageへ保存され、再マウント後も復元される", async () => {
      const user = userEvent.setup();
      const { unmount } = render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);

      await user.click(screen.getByRole("button", { name: "道路の表示項目を設定" }));
      await user.click(screen.getByRole("button", { name: "道路の種類を表示しない" }));
      await user.click(screen.getByRole("button", { name: "道路" }));
      expect(screen.getByRole("button", { name: "道路" })).toHaveAttribute("aria-expanded", "true");
      expect(screen.queryByRole("button", { name: "道路の種類" })).not.toBeInTheDocument();

      unmount();

      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);
      expect(await screen.findByRole("button", { name: "道路" })).toHaveAttribute("aria-expanded", "true");
      expect(screen.queryByRole("button", { name: "道路の種類" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "指定路線" })).toBeInTheDocument();
    });

    it("見出しのDOMノードは折りたたみ↔展開の切り替えでも同一のまま保たれる", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);

      const roadButton = screen.getByRole("button", { name: "道路" });
      await user.click(roadButton);
      expect(roadButton).toHaveAttribute("aria-expanded", "true");
      expect(roadButton).toBe(screen.getByRole("button", { name: "道路" }));

      await user.click(roadButton);
      expect(roadButton).toHaveAttribute("aria-expanded", "false");
    });

    it("道路グループのメンバータイルは凡例を持てば個別に▶展開ボタンが付き、開くと右へ凡例が出る", async () => {
      const user = userEvent.setup();
      const layers = roadLayers();
      const roadType = layers.find((l) => l.id === "roadType")!;
      roadType.on = true;
      roadType.legendDetails = [
        {
          label: "道路の種類",
          legend: [{ key: "primary", label: "幹線道路", color: "#111827", filter: ["literal", true] }],
          hiddenKeys: [],
        },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      await user.click(screen.getByRole("button", { name: "道路" }));
      const expandToggle = screen.getByRole("button", { name: "道路の種類の凡例を表示" });
      expect(screen.queryByText("幹線道路")).not.toBeInTheDocument();

      await user.click(expandToggle);
      expect(screen.getByText("幹線道路")).toBeInTheDocument();
    });
  });

  // 環境グループ（改善計画T406、旧「動的データ」group:dynamicを継承しつつterrain=標高図も
  // 統合）。挙動・構成は旧動的グループと同一（▼縦積み・地続き展開、凡例排他等）。
  describe("環境グループ（改善計画T406）", () => {
    function environmentLayers(): OverlayLayerChip[] {
      return [
        { id: "route", label: "ルート", on: false }, // どのグループにも属さない→単独のまま
        {
          id: "precipitationNowcast",
          label: "降水ナウキャスト",
          chipLabel: "降水",
          on: false,
          category: "weather",
          dataNature: "dynamic",
        },
      ];
    }

    it("terrain（標高図）・weather（降水等）どちらのcategoryのチップも「環境」へ束ねられ、個別ボタンは出ない", () => {
      const layers: OverlayLayerChip[] = [
        ...environmentLayers(),
        { id: "elevation", label: "標高図", on: false, category: "terrain" },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      expect(screen.queryByRole("button", { name: "降水" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "標高図" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "環境" })).toBeInTheDocument();
    });

    it("環境グループを開くと、独立したカードに閉じ込めずメンバーが兄弟要素として並ぶ", async () => {
      const user = userEvent.setup();
      const { container } = render(<MapOverlayControls {...baseProps()} layers={environmentLayers()} />);

      await user.click(screen.getByRole("button", { name: "環境" }));
      expect(container.querySelector('[class*="detailPanelBase"]')).not.toBeInTheDocument();

      const environmentButton = screen.getByRole("button", { name: "環境" });
      const memberButton = screen.getByRole("button", { name: "降水" });
      expect(environmentButton.closest('[class*="chipRowItem"]')?.parentElement).toBe(
        memberButton.closest('[class*="chipRowItem"]')?.parentElement
      );
    });

    it("環境グループのメンバーをタップするとonToggleがレイヤーIDと反転値で呼ばれる", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={environmentLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "環境" }));
      await user.click(screen.getByRole("button", { name: "降水" }));
      expect(onToggle).toHaveBeenCalledWith("precipitationNowcast", true);
    });

    // 改善計画T199（統合レビュー2026-08-22指摘）: 降水ナウキャストと風の凡例を続けて開くと、
    // 両方がdocument.bodyへのfloatingパネルとして同時に表示され、近接する行同士で
    // 重なって両方とも判読不能になっていた（実機Playwright確認で再現）。member:系の
    // floatingパネルは排他（新しく開いたら他を閉じる）にする。
    it("環境グループの凡例は排他表示になる（先に開いた凡例は自動で閉じる）", async () => {
      const user = userEvent.setup();
      const layers: OverlayLayerChip[] = [
        {
          id: "precipitationNowcast",
          label: "降水ナウキャスト",
          chipLabel: "降水",
          on: true,
          category: "weather",
          dataNature: "dynamic",
          legendDetails: [{ label: "降水強度", legend: [{ key: "light", label: "弱い雨", color: "#7dd3fc", filter: ["literal", true] }], hiddenKeys: [] }],
        },
        {
          id: "windVector",
          label: "風（矢印）",
          chipLabel: "風",
          on: true,
          category: "weather",
          dataNature: "dynamic",
          legendDetails: [{ label: "風速", legend: [{ key: "calm", label: "無風", color: "#94a3b8", filter: ["literal", true] }], hiddenKeys: [] }],
        },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);
      await user.click(screen.getByRole("button", { name: "環境" }));

      await user.click(screen.getByRole("button", { name: "降水ナウキャストの凡例を表示" }));
      expect(screen.getByText("弱い雨")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "風（矢印）の凡例を表示" }));
      expect(screen.getByText("無風")).toBeInTheDocument();
      // 降水側の凡例は自動的に閉じている（重なって両方判読不能になる不具合の再発防止）
      expect(screen.queryByText("弱い雨")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "降水ナウキャストの凡例を表示" })).toHaveAttribute("aria-expanded", "false");
    });

    it("表示項目設定(Ⓘ)で、説明文(panelHint)を持つ項目には情報アイコンが出て、押すと説明文が開閉する", async () => {
      const user = userEvent.setup();
      const layers: OverlayLayerChip[] = [
        {
          id: "windVector",
          label: "風（矢印）",
          on: false,
          category: "weather",
          dataNature: "dynamic",
          panelHint: "これはテスト用の説明文です。",
        },
        { id: "precipitationNowcast", label: "降水ナウキャスト", on: false, category: "weather", dataNature: "dynamic" },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      await user.click(screen.getByRole("button", { name: "環境の表示項目を設定" }));

      const infoButton = screen.getByRole("button", { name: "風（矢印）の説明を表示" });
      expect(infoButton).toBeInTheDocument();
      expect(screen.queryByText("これはテスト用の説明文です。")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "降水ナウキャストの説明を表示" })).not.toBeInTheDocument();

      await user.click(infoButton);
      expect(screen.getByText("これはテスト用の説明文です。")).toBeInTheDocument();
    });
  });

  // スポットグループ（改善計画T406、旧「観測データ」group:rawのうちtrafficSafety/amenity
  // 部分を継承）。挙動・構成は道路/環境グループと同じ（▼縦積み・地続き展開）ため、代表的な
  // シナリオのみ検証する（詳細な仕組み自体は道路グループのテストで検証済み）。
  describe("スポットグループ（改善計画T406）", () => {
    function spotLayers(): OverlayLayerChip[] {
      return [
        { id: "route", label: "ルート", on: false },
        { id: "stopPoi", label: "停止要因", on: false, category: "trafficSafety" },
        { id: "accidents", label: "事故地点", on: true, category: "trafficSafety" },
        { id: "supplyPoi", label: "補給・休憩ポイント", chipLabel: "補給休憩", on: false, category: "amenity" },
      ];
    }

    it("trafficSafety/amenity（非composite）のチップは「スポット」へ束ねられ、車の圧迫感（composite）は含まれない", () => {
      const layers: OverlayLayerChip[] = [
        ...spotLayers(),
        { id: "axis:car_stress", label: "車の圧迫感", on: false, category: "trafficSafety", dataNature: "composite" },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      expect(screen.getByRole("button", { name: "スポット" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "停止要因" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "事故地点" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "補給休憩" })).not.toBeInTheDocument();
    });

    it("スポットグループを開くとメンバーがフラットに並び、タップでonToggleが呼ばれる", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={spotLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "スポット" }));
      const accidentsToggle = screen.getByRole("button", { name: "事故地点" });
      expect(accidentsToggle).toHaveAttribute("aria-pressed", "true");

      await user.click(screen.getByRole("button", { name: "補給休憩" }));
      expect(onToggle).toHaveBeenCalledWith("supplyPoi", true);
    });

    it("スポット見出しのグループ色分けクラスはiconChipGroupSpot", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={spotLayers()} />);
      const spotButton = screen.getByRole("button", { name: "スポット" });
      expect(spotButton.className).toMatch(/iconChipGroupSpot/);

      await user.click(spotButton);
      const accidentsButton = screen.getByRole("button", { name: "事故地点" });
      expect(accidentsButton.className).toMatch(/iconChipGroupSpot/);
      expect(accidentsButton.className).toMatch(/iconChipActive/);
    });
  });

});
