import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MapOverlayControls, { type OverlayLayerChip } from "./MapOverlayControls";
import { LAYER_DATA_STATUS_LABELS } from "@/features/map/layers/mapLayers";
import { MAP_OVERLAY_MAX_EXPANDED_GROUPS } from "@/features/map/layers/mapLayers";

// このコンポーネントは渡されたアイコンをそのまま描くだけで、形を見ない。
const TestIcon = () => <svg />;

function baseLayers(): OverlayLayerChip[] {
  return [
    { id: "elevation", icon: TestIcon, label: "標高図", on: false },
    { id: "surface", icon: TestIcon, label: "路面", on: false },
    { id: "route", icon: TestIcon, label: "ルート", on: false },
  ];
}

function baseProps() {
  return {
    layers: baseLayers(),
    onToggle: vi.fn(),
    onLegendEntryToggle: vi.fn(),
    onLegendAxisSetHidden: vi.fn(),
  };
}

// 凡例・絞り込み編集・色分けモード選択などの「細かな設定」はすべてサイドバー側
// （このファイル自身の▶パネルのテスト）で検証する。ここは地図の上に残った最小限の要素
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
    expect(onToggle).toHaveBeenCalledWith("surface", false);
  });

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

  describe("▶パネルの内訳トグル（axisIdを持つ軸だけチェックボックスで操作できる）", () => {
    function layersWithToggleableLegend(hiddenKeys: string[] = []) {
      const layers = baseLayers();
      layers[1] = {
        ...layers[1],
        on: true,
        legendDetails: [
          {
            label: "路面の種類",
            legend: [
              { key: "asphalt", label: "アスファルト", color: "#16a34a", filter: ["literal", true] },
              { key: "concrete", label: "コンクリート", color: "#0d9488", filter: ["literal", true] },
            ],
            hiddenKeys,
            axisId: "surface",
          },
        ],
      };
      return layers;
    }

    it("チェックを外すとonLegendEntryToggleが軸IDとカテゴリキーで呼ばれる", async () => {
      const user = userEvent.setup();
      const onLegendEntryToggle = vi.fn();
      render(
        <MapOverlayControls
          {...baseProps()}
          layers={layersWithToggleableLegend()}
          onLegendEntryToggle={onLegendEntryToggle}
        />,
      );

      await user.click(screen.getByRole("button", { name: "路面の凡例を表示" }));
      await user.click(screen.getByRole("checkbox", { name: "アスファルト" }));

      expect(onLegendEntryToggle).toHaveBeenCalledWith("surface", "asphalt");
    });

    it("非表示のカテゴリはチェックが外れた状態で描かれる（サイドバーの絞り込みと同じ状態を共有）", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={layersWithToggleableLegend(["concrete"])} />);

      await user.click(screen.getByRole("button", { name: "路面の凡例を表示" }));

      expect(screen.getByRole("checkbox", { name: "アスファルト" })).toBeChecked();
      expect(screen.getByRole("checkbox", { name: "コンクリート" })).not.toBeChecked();
    });

    it("見出しの一括チェックは、全部表示中なら押すと全部隠す", async () => {
      const user = userEvent.setup();
      const onLegendAxisSetHidden = vi.fn();
      render(
        <MapOverlayControls
          {...baseProps()}
          layers={layersWithToggleableLegend()}
          onLegendAxisSetHidden={onLegendAxisSetHidden}
        />,
      );

      await user.click(screen.getByRole("button", { name: "路面の凡例を表示" }));
      await user.click(screen.getByRole("checkbox", { name: "路面の種類をまとめて表示/非表示" }));

      expect(onLegendAxisSetHidden).toHaveBeenCalledWith("surface", ["asphalt", "concrete"]);
    });

    it("見出しの一括チェックは、1つでも隠れていれば押すと全部表示に戻す", async () => {
      const user = userEvent.setup();
      const onLegendAxisSetHidden = vi.fn();
      render(
        <MapOverlayControls
          {...baseProps()}
          layers={layersWithToggleableLegend(["concrete"])}
          onLegendAxisSetHidden={onLegendAxisSetHidden}
        />,
      );

      await user.click(screen.getByRole("button", { name: "路面の凡例を表示" }));
      const bulk = screen.getByRole("checkbox", { name: "路面の種類をまとめて表示/非表示" });
      expect(bulk).not.toBeChecked();

      await user.click(bulk);
      expect(onLegendAxisSetHidden).toHaveBeenCalledWith("surface", []);
    });

    it("axisIdを持たない軸（ラスタ等、カテゴリ単位で絞り込めない）はチェックボックスを出さない", async () => {
      const user = userEvent.setup();
      const layers = baseLayers();
      layers[1] = {
        ...layers[1],
        on: true,
        legendDetails: [
          {
            label: "雷ナウキャスト（活動度）",
            legend: [{ key: "level1", label: "活動度1", color: "#f2e700", filter: ["literal", true] }],
            hiddenKeys: [],
          },
        ],
      };
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      await user.click(screen.getByRole("button", { name: "路面の凡例を表示" }));

      expect(screen.getByText("活動度1")).toBeInTheDocument();
      expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    });
  });

  it("絞り込み中は非表示カテゴリに「非表示」バッジが付く", async () => {
    const user = userEvent.setup();
    const layers = baseLayers();
    layers[1] = {
      ...layers[1],
      on: true,
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
  });

  it("凡例が無くても案内文があれば▶が出て、開くと案内文が出る", async () => {
    const user = userEvent.setup();
    const layers = baseLayers();
    layers[1] = { ...layers[1], on: true, notice: "ズームインすると表示されます", legendDetails: [] };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    const toggle = screen.getByRole("button", { name: "路面の凡例を表示" });
    await user.click(toggle);
    expect(screen.getByText("ズームインすると表示されます")).toBeInTheDocument();
  });

  // 案内が出るのは「ONにしても何も出ない」状態だけで、そのときの凡例は地図に存在しない
  // 色見本の表になる。呼ぶ側が凡例を空へ揃える形だと、揃え忘れたレイヤーで案内が黙って
  // 落ちる——**凡例が非空でも案内が勝つ**ことをここで固定する。
  it("凡例があっても、案内文があるときは案内文を出す", async () => {
    const user = userEvent.setup();
    const layers = baseLayers();
    layers[1] = {
      ...layers[1],
      on: true,
      notice: "ズームインすると表示されます",
      legendDetails: [
        {
          label: "路面の種類",
          legend: [{ key: "asphalt", label: "アスファルト", color: "#16a34a", filter: ["literal", true] }],
          hiddenKeys: [],
        },
      ],
    };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    await user.click(screen.getByRole("button", { name: "路面の凡例を表示" }));
    expect(screen.getByText("ズームインすると表示されます")).toBeInTheDocument();
    expect(screen.queryByText("アスファルト")).not.toBeInTheDocument();
  });

  // 線レイヤーは太さ・線種で意味を運ばない（T858）。どのカテゴリも同じ色ドットで描かれ、
  // 「このカテゴリだけ別の見た目」が混ざらないことを確認する。
  it("凡例カテゴリはどれも色ドットで描画される", async () => {
    const user = userEvent.setup();
    const layers = baseLayers();
    layers[1] = {
      ...layers[1],
      on: true,
      legendDetails: [
        {
          label: "道路の種類",
          legend: [
            { key: "primary", label: "幹線道路", color: "#111827", filter: ["literal", true] },
            { key: "residential", label: "生活道路", color: "#9ca3af", filter: ["literal", true] },
          ],
          hiddenKeys: [],
        },
      ],
    };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    await user.click(screen.getByRole("button", { name: "路面の凡例を表示" }));

    for (const label of ["幹線道路", "生活道路"]) {
      const row = screen.getByText(label).closest("li")!;
      const dot = row.querySelector("span") as HTMLElement;
      expect(dot).toBeTruthy();
      expect(dot.getAttribute("style") ?? "").toContain("background");
      // 太さバーは高さをインラインで持っていた。色ドットは持たない。
      expect(dot.style.height).toBe("");
    }
  });

  it("OFF・disabled・凡例無しのレイヤーには▶が出ない", () => {
    const layers: OverlayLayerChip[] = [
      { id: "elevation", icon: TestIcon, label: "標高図", on: true, legendDetails: [] }, // 凡例無し
      {
        id: "surface",
        icon: TestIcon,
        label: "路面",
        on: false,
        legendDetails: [{ label: "路面の種類", legend: [], hiddenKeys: [] }],
      }, // OFF
      {
        id: "route",
        icon: TestIcon,
        label: "ルート",
        on: true,
        disabled: true,
        notice: "配信情報を取得できず表示できません",
      }, // disabled
    ];
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    expect(screen.queryByRole("button", { name: "標高図の凡例を表示" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "路面の凡例を表示" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ルートの凡例を表示" })).not.toBeInTheDocument();
  });

  // 最上位グループ束ね（改善計画T406、旧「次数束ね」T166を全面再編、T418で評価軸グループを
  // 撤去）: 旧「観測/推定/動的」（データの出自による3分類）を廃止し、「対象（何についての
  // 情報か）」で束ね直した「道路/環境/スポット」の3グループになった（docs/records/tasks/T400.md
  // 「1. パネルの最上位グルーピング」節、docs/records/tasks/T418.md）。mapOverlayGroupFor()
  // （mapLayers.ts）の判定規則:
  // - 道路: category==="roadCondition"
  // - 環境: category==="terrain"||"weather"
  // - スポット: category==="trafficSafety"||"amenity"
  // - 軸スタジオ由来のレイヤー（isAxisStudioLayer、レイヤー記述子のaxisStudioLayerフラグ
  //   またはdataNature==="composite"で判定する）はどのグループにも属さず、単独チップ
  //   としても出ない（下記「軸スタジオ由来レイヤーの撤去（改善計画T418）」参照）
  // - それ以外どれにも該当しない（category未指定、route等）は単独チップのまま
  describe("最上位グループ束ね（改善計画T406/T418）", () => {
    function groupedLayers(): OverlayLayerChip[] {
      return [
        { id: "route", icon: TestIcon, label: "ルート", on: false }, // どのグループにも属さない→単独のまま
        { id: "highway", icon: TestIcon, label: "道路の種類", on: false, category: "roadCondition" },
        { id: "tunnel", icon: TestIcon, label: "トンネル", on: true, category: "roadCondition" },
        {
          id: "axis:axis_sample",
          icon: TestIcon,
          label: "見本の軸",
          on: true,
          category: "trafficSafety",
          dataNature: "composite",
        },
        { id: "accident_point", icon: TestIcon, label: "事故地点", on: false, category: "trafficSafety" }, // dataNature省略→composite以外扱い
        { id: "elevation", icon: TestIcon, label: "標高図", on: false, category: "terrain" },
      ];
    }

    it("道路（roadCondition）・環境（terrain/weather）・スポット（trafficSafety/amenity）へそれぞれ束ねられ、個別ボタンは出ない。軸スタジオ由来（composite）は単独チップとしても出ない", () => {
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      expect(screen.getByRole("button", { name: "ルート" })).toBeInTheDocument(); // どのグループにも属さない単独チップ
      expect(screen.queryByRole("button", { name: "道路の種類" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "トンネル" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "見本の軸" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "事故地点" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "標高図" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "道路" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "評価軸" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "環境" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "スポット" })).toBeInTheDocument();
    });

    it("チップ列は道路→環境→スポット→ルートの順で並ぶ（docs/records/tasks/T400.mdの記載順のうち評価軸を除いたもの）", () => {
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
        { id: "route", icon: TestIcon, label: "ルート", on: false },
        {
          id: "axis:axis_sample",
          icon: TestIcon,
          label: "見本の軸",
          on: true,
          category: "trafficSafety",
          dataNature: "composite",
        },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      expect(screen.getByRole("button", { name: "ルート" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "見本の軸" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "評価軸" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "スポット" })).not.toBeInTheDocument();
    });

    it("専用way値配信軸はどのグループにも束ねられず、単独チップとしても出ない", () => {
      const layers: OverlayLayerChip[] = [
        { id: "route", icon: TestIcon, label: "ルート", on: false },
        {
          id: "windAxis",
          icon: TestIcon,
          axisStudioLayer: true,
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

  // 開いたグループのメンバーはチップ列へ縦に積まれるため、開くほど地図が縦に隠れる
  // （375×812の実測: すべて畳んで画面の縦の23%、1グループ開いて54%、3グループすべてで72%）。
  describe("同時に開けるグループの数", () => {
    function allGroupLayers(): OverlayLayerChip[] {
      return [
        { id: "highway", icon: TestIcon, label: "道路の種類", on: false, category: "roadCondition" },
        { id: "elevation", icon: TestIcon, label: "標高図", on: false, category: "terrain" },
        { id: "stop_poi", icon: TestIcon, label: "停止要因", on: false, category: "trafficSafety" },
      ];
    }

    it("別のグループを開くと、先に開いていたグループは畳まれる", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={allGroupLayers()} />);

      await user.click(screen.getByRole("button", { name: "道路" }));
      expect(screen.getByRole("button", { name: "道路" })).toHaveAttribute("aria-expanded", "true");

      await user.click(screen.getByRole("button", { name: "環境" }));

      expect(screen.getByRole("button", { name: "環境" })).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByRole("button", { name: "道路" })).toHaveAttribute("aria-expanded", "false");
      expect(screen.getByRole("button", { name: "スポット" })).toHaveAttribute("aria-expanded", "false");
    });

    it("上限を超えた保存済みの状態も、復元した時点で上限へ収まる", async () => {
      // 上限を下げる前に保存された値が残っていると、次に開いたときだけ上限を超えた状態で
      // 復元される（保存側だけを直しても、既に書かれた値は直らない）。
      window.localStorage.setItem(
        "ridecompass:map-overlay-expanded-groups",
        JSON.stringify(["group:road", "group:environment", "group:spot"]),
      );

      render(<MapOverlayControls {...baseProps()} layers={allGroupLayers()} />);

      const expanded = ["道路", "環境", "スポット"].filter(
        (name) => screen.getByRole("button", { name }).getAttribute("aria-expanded") === "true",
      );
      expect(expanded).toHaveLength(MAP_OVERLAY_MAX_EXPANDED_GROUPS);
    });
  });

  // 道路グループ（改善計画T406、旧「観測データ」group:rawのうちroadCondition部分を継承）。
  // 挙動・構成は旧観測グループと同一（▼縦積み・地続き展開、表示項目設定パネル、凡例排他等）。
  describe("道路グループ（改善計画T406）", () => {
    function roadLayers(): OverlayLayerChip[] {
      return [
        { id: "elevation", icon: TestIcon, label: "標高図", on: false, category: "terrain" }, // 環境グループ側の対照用
        { id: "highway", icon: TestIcon, label: "道路の種類", on: false, category: "roadCondition" },
        { id: "tunnel", icon: TestIcon, label: "トンネル", on: true, category: "roadCondition" },
      ];
    }

    it("道路グループを開いても内訳を囲むカード（サブフレーム）は出ず、メンバーはチップ列と同じ階層の兄弟要素として並ぶ", async () => {
      const user = userEvent.setup();
      const { container } = render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);

      await user.click(screen.getByRole("button", { name: "道路" }));
      expect(screen.queryByRole("region")).not.toBeInTheDocument();

      const roadButton = screen.getByRole("button", { name: "道路" });
      const tunnelButton = screen.getByRole("button", { name: "トンネル" });
      expect(roadButton.closest('[data-slot="chip-row-item"]')?.parentElement).toBe(
        tunnelButton.closest('[data-slot="chip-row-item"]')?.parentElement,
      );
    });

    it("道路グループを開くとcategory小見出しを出さずメンバーのON/OFFボタンがフラットに並ぶ", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "道路" }));
      const tunnelToggle = screen.getByRole("button", { name: "トンネル" });
      expect(tunnelToggle).toHaveAttribute("aria-pressed", "true");

      await user.click(tunnelToggle);
      expect(onToggle).toHaveBeenCalledWith("tunnel", false);
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
      expect(screen.queryByRole("button", { name: "トンネル" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "道路" })).toHaveAttribute("aria-expanded", "false");
      expect(screen.getByText("道路の種類")).toBeInTheDocument();
      expect(screen.getByText("トンネル")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "道路" }));
      expect(screen.getByRole("button", { name: "トンネル" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "道路の表示項目を設定" })).not.toBeInTheDocument();
    });

    // 設定パネルは折りたたみ中にだけ出る。開いたままのキーを残すと、次にそのグループを
    // 畳んだ瞬間、ⓘを押していないのに設定パネルが開いた状態で戻ってくる。
    it("設定パネルを開いたままグループを開くと、畳み直したときに再出現しない", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);

      await user.click(screen.getByRole("button", { name: "道路の表示項目を設定" }));
      expect(screen.getByText("道路の種類")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "道路" }));
      expect(screen.getByRole("button", { name: "道路" })).toHaveAttribute("aria-expanded", "true");

      await user.click(screen.getByRole("button", { name: "道路" }));
      expect(screen.queryByText("道路の種類")).not.toBeInTheDocument();
    });

    it("表示項目の設定で非表示に選ぶと、グループを開いてもそのメンバーだけが出ない", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);

      await user.click(screen.getByRole("button", { name: "道路の表示項目を設定" }));
      await user.click(screen.getByRole("checkbox", { name: "トンネルを表示しない" }));
      await user.click(screen.getByRole("button", { name: "道路" }));
      expect(screen.queryByRole("button", { name: "トンネル" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "道路の種類" })).toBeInTheDocument(); // 他は影響なし
    });

    it("表示項目の設定で非表示に選ぶと、そのレイヤーがONなら即座にOFFにされる", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "道路の表示項目を設定" }));
      await user.click(screen.getByRole("checkbox", { name: "トンネルを表示しない" }));
      expect(onToggle).toHaveBeenCalledWith("tunnel", false);
    });

    it("非表示を解除してもレイヤーは自動でONにならない", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "道路の表示項目を設定" }));
      await user.click(screen.getByRole("checkbox", { name: "トンネルを表示しない" }));
      onToggle.mockClear();

      await user.click(screen.getByRole("checkbox", { name: "トンネルを表示する" }));
      expect(onToggle).not.toHaveBeenCalled();
    });

    it("表示項目設定で、説明文(panelHint)を持つ項目には情報アイコンが出て、押すと説明文が開閉する", async () => {
      const user = userEvent.setup();
      const layers: OverlayLayerChip[] = [
        {
          id: "tunnel",
          icon: TestIcon,
          label: "トンネル",
          on: false,
          category: "roadCondition",
          panelHint: "これはテスト用の説明文です。",
        },
        { id: "highway", icon: TestIcon, label: "道路の種類", on: false, category: "roadCondition" }, // panelHint未設定
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      await user.click(screen.getByRole("button", { name: "道路の表示項目を設定" }));

      const infoButton = screen.getByRole("button", { name: "トンネルの説明を表示" });
      expect(infoButton).toBeInTheDocument();
      expect(screen.queryByText("これはテスト用の説明文です。")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "道路の種類の説明を表示" })).not.toBeInTheDocument();

      await user.click(infoButton);
      expect(screen.getByText("これはテスト用の説明文です。")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "トンネルの説明を隠す" })).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "トンネルの説明を隠す" }));
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
      const panel = screen.getByRole("region", { name: "道路の表示項目" });
      expect(panel).toBeTruthy();
      expect(panel.style.maxHeight).toBe("120px");

      vi.restoreAllMocks();
    });

    it("グループの開閉状態と表示項目の設定はlocalStorageへ保存され、再マウント後も復元される", async () => {
      const user = userEvent.setup();
      const { unmount } = render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);

      await user.click(screen.getByRole("button", { name: "道路の表示項目を設定" }));
      await user.click(screen.getByRole("checkbox", { name: "道路の種類を表示しない" }));
      await user.click(screen.getByRole("button", { name: "道路" }));
      expect(screen.getByRole("button", { name: "道路" })).toHaveAttribute("aria-expanded", "true");
      expect(screen.queryByRole("button", { name: "道路の種類" })).not.toBeInTheDocument();

      unmount();

      render(<MapOverlayControls {...baseProps()} layers={roadLayers()} />);
      expect(await screen.findByRole("button", { name: "道路" })).toHaveAttribute("aria-expanded", "true");
      expect(screen.queryByRole("button", { name: "道路の種類" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "トンネル" })).toBeInTheDocument();
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
      const roadType = layers.find((l) => l.id === "highway")!;
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
        { id: "route", icon: TestIcon, label: "ルート", on: false }, // どのグループにも属さない→単独のまま
        {
          id: "precipitationNowcast",
          icon: TestIcon,
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
        { id: "elevation", icon: TestIcon, label: "標高図", on: false, category: "terrain" },
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
      expect(screen.queryByRole("region")).not.toBeInTheDocument();

      const environmentButton = screen.getByRole("button", { name: "環境" });
      const memberButton = screen.getByRole("button", { name: "降水" });
      expect(environmentButton.closest('[data-slot="chip-row-item"]')?.parentElement).toBe(
        memberButton.closest('[data-slot="chip-row-item"]')?.parentElement,
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
          icon: TestIcon,
          label: "降水ナウキャスト",
          chipLabel: "降水",
          on: true,
          category: "weather",
          dataNature: "dynamic",
          legendDetails: [
            {
              label: "降水強度",
              legend: [{ key: "light", label: "弱い雨", color: "#7dd3fc", filter: ["literal", true] }],
              hiddenKeys: [],
            },
          ],
        },
        {
          id: "windVector",
          icon: TestIcon,
          label: "風（矢印）",
          chipLabel: "風",
          on: true,
          category: "weather",
          dataNature: "dynamic",
          legendDetails: [
            {
              label: "風速",
              legend: [{ key: "calm", label: "無風", color: "#94a3b8", filter: ["literal", true] }],
              hiddenKeys: [],
            },
          ],
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
      expect(screen.getByRole("button", { name: "降水ナウキャストの凡例を表示" })).toHaveAttribute(
        "aria-expanded",
        "false",
      );
    });

    it("表示項目設定(Ⓘ)で、説明文(panelHint)を持つ項目には情報アイコンが出て、押すと説明文が開閉する", async () => {
      const user = userEvent.setup();
      const layers: OverlayLayerChip[] = [
        {
          id: "windVector",
          icon: TestIcon,
          label: "風（矢印）",
          on: false,
          category: "weather",
          dataNature: "dynamic",
          panelHint: "これはテスト用の説明文です。",
        },
        {
          id: "precipitationNowcast",
          icon: TestIcon,
          label: "降水ナウキャスト",
          on: false,
          category: "weather",
          dataNature: "dynamic",
        },
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
        { id: "route", icon: TestIcon, label: "ルート", on: false },
        { id: "stop_poi", icon: TestIcon, label: "停止要因", on: false, category: "trafficSafety" },
        { id: "accident_point", icon: TestIcon, label: "事故地点", on: true, category: "trafficSafety" },
        {
          id: "supply_poi",
          icon: TestIcon,
          label: "補給・休憩ポイント",
          chipLabel: "補給休憩",
          on: false,
          category: "amenity",
        },
      ];
    }

    it("trafficSafety/amenity（非composite）のチップは「スポット」へ束ねられ、見本の軸（composite）は含まれない", () => {
      const layers: OverlayLayerChip[] = [
        ...spotLayers(),
        {
          id: "axis:axis_sample",
          icon: TestIcon,
          label: "見本の軸",
          on: false,
          category: "trafficSafety",
          dataNature: "composite",
        },
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
      expect(onToggle).toHaveBeenCalledWith("supply_poi", true);
    });
  });

  describe("凡例の絞り込み中の印", () => {
    const filteredLegend = (hiddenKeys: string[]) => [
      {
        axisId: "surface",
        label: "路面の種類",
        legend: [
          { key: "asphalt", label: "アスファルト", color: "#16a34a", filter: ["literal", true] },
          { key: "gravel", label: "砂利", color: "#a16207", filter: ["literal", true] },
        ],
        hiddenKeys,
      },
    ];

    it("ONで一部を隠しているチップだけに印を付け、titleにも添える", () => {
      const layers = baseLayers();
      layers[1] = { ...layers[1], on: true, legendDetails: filteredLegend(["gravel"]) };
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      const chip = screen.getByRole("button", { name: "路面" });
      expect(chip.getAttribute("title")).toContain("絞り込み中");
    });

    it("何も隠していない・OFFのチップには印を付けない", () => {
      const layers = baseLayers();
      layers[0] = { ...layers[0], on: false, legendDetails: filteredLegend(["gravel"]) };
      layers[1] = { ...layers[1], on: true, legendDetails: filteredLegend([]) };
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      expect(screen.getByRole("button", { name: "標高図" }).getAttribute("title") ?? "").not.toContain("絞り込み中");
      expect(screen.getByRole("button", { name: "路面" }).getAttribute("title") ?? "").not.toContain("絞り込み中");
    });

    it("畳んだグループの見出しは、メンバーの絞り込みを印で示す（開くとメンバー側が持つ）", async () => {
      const user = userEvent.setup();
      const layers: OverlayLayerChip[] = [
        {
          id: "accident_point",
          icon: TestIcon,
          label: "事故地点",
          on: true,
          category: "trafficSafety",
          legendDetails: filteredLegend(["gravel"]),
        },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      const header = screen.getByRole("button", { name: "スポット" });
      expect(header.getAttribute("title")).toContain("絞り込み中");

      await user.click(header);
      expect(header.getAttribute("title") ?? "").not.toContain("絞り込み中");
      expect(screen.getByRole("button", { name: "事故地点" }).getAttribute("title")).toContain("絞り込み中");
    });
  });

  describe("レイヤーのデータ取得状態（改善計画T87/T606: 地図上チップの状態ドット）", () => {
    it("dataStatusを渡すとON中のチップに状態ドットが描画され、titleへ状態文言が反映される", () => {
      const layers: OverlayLayerChip[] = [
        { id: "route", icon: TestIcon, label: "ルート", on: true, title: "選択中ルート", dataStatus: "loading" },
      ];
      render(
        <MapOverlayControls
          layers={layers}
          onToggle={vi.fn()}
          onLegendEntryToggle={vi.fn()}
          onLegendAxisSetHidden={vi.fn()}
        />,
      );

      const chip = screen.getByRole("button", { name: "ルート" });
      expect(chip).toHaveAttribute("title", "選択中ルート（読み込み中です）");
    });

    it("OFF中のチップはdataStatusがあってもドットを出さない（LayerChipと同じ抑制条件）", () => {
      const layers: OverlayLayerChip[] = [
        { id: "route", icon: TestIcon, label: "ルート", on: false, dataStatus: "error" },
      ];
      render(
        <MapOverlayControls
          layers={layers}
          onToggle={vi.fn()}
          onLegendEntryToggle={vi.fn()}
          onLegendAxisSetHidden={vi.fn()}
        />,
      );

      const chip = screen.getByRole("button", { name: "ルート" });
      expect(chip.getAttribute("title") ?? "").not.toContain(LAYER_DATA_STATUS_LABELS.error);
    });

    it("ON中で状態があるチップは、凡例が無くても▶を出し、開くと状態を文で読める（titleに頼らない）", async () => {
      const user = userEvent.setup();
      const layers: OverlayLayerChip[] = [
        { id: "route", icon: TestIcon, label: "ルート", on: true, dataStatus: "empty" },
      ];
      render(
        <MapOverlayControls
          layers={layers}
          onToggle={vi.fn()}
          onLegendEntryToggle={vi.fn()}
          onLegendAxisSetHidden={vi.fn()}
        />,
      );

      await user.click(screen.getByRole("button", { name: "ルートの凡例を表示" }));
      expect(screen.getByRole("status")).toHaveTextContent("この範囲に表示できるデータがありません");
    });

    it("凡例を持つチップでは、状態の文を凡例と並べて出す", async () => {
      const user = userEvent.setup();
      const layers = baseLayers();
      layers[1] = {
        ...layers[1],
        on: true,
        dataStatus: "error",
        legendDetails: [
          {
            label: "路面の種類",
            legend: [{ key: "asphalt", label: "アスファルト", color: "#16a34a", filter: ["literal", true] }],
            hiddenKeys: [],
          },
        ],
      };
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      await user.click(screen.getByRole("button", { name: "路面の凡例を表示" }));
      expect(screen.getByRole("status")).toHaveTextContent("データの取得に失敗しました");
      expect(screen.getByText("アスファルト")).toBeInTheDocument();
    });

    it("dataStatus未指定（正常）のチップはドットを出さない", () => {
      const layers: OverlayLayerChip[] = [{ id: "route", icon: TestIcon, label: "ルート", on: true }];
      render(
        <MapOverlayControls
          layers={layers}
          onToggle={vi.fn()}
          onLegendEntryToggle={vi.fn()}
          onLegendAxisSetHidden={vi.fn()}
        />,
      );

      const chip = screen.getByRole("button", { name: "ルート" });
      expect(chip.getAttribute("title") ?? "").not.toContain(LAYER_DATA_STATUS_LABELS.error);
    });
  });
});
