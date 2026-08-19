import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
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
describe("MapOverlayControls", () => {
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

  // 次数束ね（改善計画T166）: T128のcategory束ねを、観測データ/推定指標（合成）の2トップへ
  // 反転した。categoryを持つraw（省略含む）チップは「観測」、compositeチップは「推定」へ
  // 集約され、categoryを持たないレイヤー（route等）は従来どおり単独。
  describe("次数束ね（改善計画T166）", () => {
    function groupedLayers(): OverlayLayerChip[] {
      return [
        { id: "elevation", label: "標高図", on: false }, // categoryなし→単独のまま
        { id: "roadType", label: "道路の種類", on: false, category: "roadCondition" },
        { id: "designation", label: "指定路線", on: true, category: "roadCondition" },
        { id: "carStress", label: "車の圧迫感", on: true, category: "trafficSafety", dataNature: "composite" },
        { id: "accidents", label: "事故地点", on: false, category: "trafficSafety" }, // dataNature省略→raw扱い
      ];
    }

    it("観測（raw）チップはすべて「観測」へ、推定（composite）チップはすべて「推定」へ束ねられ、個別ボタンは出ない", () => {
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      expect(screen.getByRole("button", { name: "標高図" })).toBeInTheDocument(); // categoryなしは単独のまま
      expect(screen.queryByRole("button", { name: "道路の種類" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "指定路線" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "車の圧迫感" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "観測" })).toBeInTheDocument(); // 次数見出しの束ねチップ（略名）
      expect(screen.getByRole("button", { name: "推定" })).toBeInTheDocument();
    });

    // 表示順・展開方式の見直し（実機フィードバック: 「推定→観測」の順に入替え、観測の▼展開は
    // 独立したサブフレームではなくチップ列と地続きの縦並びにする）。
    it("チップ列は推定→観測→ルートの順で並ぶ", () => {
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      const names = screen.getAllByRole("button", { name: /^(推定|観測|標高図)$/ }).map((el) => el.textContent);
      expect(names.indexOf("推定")).toBeLessThan(names.indexOf("観測"));
    });

    it("観測グループを開いても内訳を囲むカード（サブフレーム）は出ず、メンバーはチップ列と同じ階層の兄弟要素として並ぶ", async () => {
      const user = userEvent.setup();
      const { container } = render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      await user.click(screen.getByRole("button", { name: "観測" }));
      // 以前は背景・枠・影付きのカードに閉じ込めていた。地続き化した今は出ない。
      expect(container.querySelector('[class*="detailPanelBase"]')).not.toBeInTheDocument();

      const observedButton = screen.getByRole("button", { name: "観測" });
      const designationButton = screen.getByRole("button", { name: "指定路線" });
      // ChipButtonは自身をchipRowItemとして返すため、観測チップの行とメンバーの行は
      // 同じ親（chipRow）を共有する兄弟要素になる。
      expect(observedButton.closest('[class*="chipRowItem"]')?.parentElement).toBe(
        designationButton.closest('[class*="chipRowItem"]')?.parentElement
      );
    });

    // category小見出し（道路状態・交通・安全）は表示しない（実機フィードバック
    // 「道路状態や交通・安全等のグルーピングを消して」への対応）。フラットな一覧になる。
    it("観測グループを開くとcategory小見出しを出さずメンバーのON/OFFボタンがフラットに並ぶ", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "観測" }));
      expect(screen.queryByText("道路状態")).not.toBeInTheDocument();
      expect(screen.queryByText("交通・安全")).not.toBeInTheDocument();
      const designationToggle = screen.getByRole("button", { name: "指定路線" });
      expect(designationToggle).toHaveAttribute("aria-pressed", "true");

      await user.click(designationToggle);
      expect(onToggle).toHaveBeenCalledWith("designation", false);
      // compositeのcarStressは観測グループに含まれない
      expect(screen.queryByRole("button", { name: "車の圧迫感" })).not.toBeInTheDocument();
    });

    // 展開方式の見直し（実機フィードバック: 観測の▼縦並び地続き化と対になる横並び版。
    // 推定も▶を開くと、独立したカード（サブフレーム、position: fixedのポータル）ではなく、
    // 推定チップ本体と同じ上端・同じ間隔の横並びとして地続きに展開する）。
    it("推定グループを開いても内訳を囲むカード（サブフレーム）は出ず、推定チップ本体と軸タイルは同じ上端の横並びの兄弟要素になる", async () => {
      const user = userEvent.setup();
      const { container } = render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      await user.click(screen.getByRole("button", { name: "推定" }));
      // 以前はdocument.bodyへポータルしたposition: fixedのカード（.detailPanel）に
      // 閉じ込めていた。地続き化した今は出ない（.detailPanelはdocument.bodyへポータル
      // されるためcontainerの外に出る。document.body全体を見て確認する）。
      expect(document.body.querySelector('[class*="detailPanel"]')).not.toBeInTheDocument();

      const estimatedButton = screen.getByRole("button", { name: "推定" });
      const carStressButton = screen.getByRole("button", { name: "車の圧迫感" });
      // ChipButtonは自身をchipRowItemとして返すため、推定チップの行と軸タイルの行は
      // 同じ親（横並びのestimatedFlatRow）を共有する兄弟要素になる。
      expect(estimatedButton.closest('[class*="chipRowItem"]')?.parentElement).toBe(
        carStressButton.closest('[class*="chipRowItem"]')?.parentElement
      );
    });

    // マトリックス化（改善計画T169）: 推定グループの内訳は、観測グループのメンバーと同じ
    // 「アイコン+略名の四角タイル」（ChipButton）を横並びで並べる。専用レイヤーの無い軸は
    // タップ不能（disabled）の情報タイルとして同じ見た目で並ぶ（薄字の行ではなくなった）。
    it("推定グループを開くと確定命名表の6軸すべてがタイルとして並び、専用レイヤーの無い軸は押せない情報タイルになる", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      await user.click(screen.getByRole("button", { name: "推定" }));
      // レイヤーを持つ軸（car_stress）はON/OFFタイル
      const carStressToggle = screen.getByRole("button", { name: "車の圧迫感" });
      expect(carStressToggle).toHaveAttribute("aria-pressed", "true");
      expect(carStressToggle).not.toBeDisabled();
      // レイヤーの無い軸（勾配・舗装質・夜間）は正式名のタイルだが押せない（disabled）
      const gradientTile = screen.getByRole("button", { name: "勾配" });
      expect(gradientTile).toBeDisabled();
      const surfaceQTile = screen.getByRole("button", { name: "舗装質" });
      expect(surfaceQTile).toBeDisabled();
      expect(screen.getByRole("button", { name: "夜間" })).toBeDisabled();
      // レイヤーはあるがlayers propに渡されていない軸（停止密度・事故密度）も同様に
      // disabledのタイルとして並ぶ（layersに無いので対応するチップを引けない）
      expect(screen.getByRole("button", { name: "停止密度" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "事故密度" })).toBeDisabled();

      // 専用レイヤーの無い軸にも個々に▼展開ボタンが付き、代役案内文（proxyHint）が見える
      await user.click(screen.getByRole("button", { name: "勾配の凡例を表示" }));
      expect(screen.getByText("標高レイヤーで確認できます")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "舗装質の凡例を表示" }));
      expect(screen.getByText("路面の種類レイヤーで確認できます")).toBeInTheDocument();
    });

    it("推定グループはcompositeチップが1件も渡されなくても常に表示される（SECONDARY_AXESの情報タイルがあるため）", () => {
      render(<MapOverlayControls {...baseProps()} />); // baseLayers()にcompositeチップなし
      expect(screen.getByRole("button", { name: "推定" })).toBeInTheDocument();
    });

    // 次数グループ本体（観測/推定）は展開/収納の見出しであり、タップしてもレイヤーの
    // ON/OFFは切り替わらない。以前はメンバーが1件でもONならこの見出し自体もON扱い
    // （aria-pressed=true）にしていたが、材料の連動ON（T167、推定指標をONにすると
    // 観測データも連動ONする）で「事故密度だけONにしたつもりが推定・観測の見出しまで
    // ONに見える」という実機フィードバックを受け、見出し自体は常にfalseにした。
    it("メンバーがONでもグループチップ自体はaria-pressed=falseのまま", () => {
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      // roadType=OFF・designation=ONの観測グループ
      expect(screen.getByRole("button", { name: "観測" })).toHaveAttribute("aria-pressed", "false");
      // carStress=ONの推定グループ
      expect(screen.getByRole("button", { name: "推定" })).toHaveAttribute("aria-pressed", "false");
    });

    // 推定グループの各軸タイルに材料一覧を出す（改善計画T167→T169）。axisMaterials（T164）
    // から導出した一次属性を、表示レイヤーの有無で「材料」「地図では未表示の材料」の2行に
    // 分ける。マトリックス化後は各軸タイル自身の▼展開を押してはじめて見える。
    it("推定グループの各軸タイルの▼を開くと材料一覧が出て、表示レイヤーの有無で分けて表示される", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      await user.click(screen.getByRole("button", { name: "推定" }));

      // 車の圧迫感: 道路種別・インフラ・指定路線はレイヤーあり、車線数・制限速度・車両可否は無し
      await user.click(screen.getByRole("button", { name: "車の圧迫感の凡例を表示" }));
      expect(screen.getByText("材料: 道路種別・インフラ・指定路線")).toBeInTheDocument();
      expect(screen.getByText("地図では未表示の材料: 車線数・制限速度・車両可否")).toBeInTheDocument();

      // 勾配: 材料の標高にはレイヤーがある（未表示材料は無し）
      await user.click(screen.getByRole("button", { name: "勾配の凡例を表示" }));
      expect(screen.getByText("材料: 標高")).toBeInTheDocument();

      // 夜間: 材料（街灯・トンネル）はどちらもレイヤーが無い
      await user.click(screen.getByRole("button", { name: "夜間の凡例を表示" }));
      expect(screen.getByText("地図では未表示の材料: 街灯・トンネル")).toBeInTheDocument();
    });

    // タイルの見た目統一（改善計画T169、ユーザー指摘「1次要素、2次要素すべて推定と同様の
    // 四角タイルアイコンにして」）: 観測グループのメンバーは推定グループの軸タイルと同じ
    // ChipButtonを再利用しており、個々に凡例展開ボタンが付く。観測グループ自体が▼縦積みの
    // ため、メンバー個々の展開はそれと直交する▶（右）になる。
    it("観測グループのメンバータイルは凡例を持てば個別に▶展開ボタンが付き、開くと右へ凡例が出る", async () => {
      const user = userEvent.setup();
      const layers = groupedLayers();
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

      await user.click(screen.getByRole("button", { name: "観測" }));
      const expandToggle = screen.getByRole("button", { name: "道路の種類の凡例を表示" });
      expect(screen.queryByText("幹線道路")).not.toBeInTheDocument();

      await user.click(expandToggle);
      expect(screen.getByText("幹線道路")).toBeInTheDocument();
    });

    // 実機フィードバック「道路種別や路面等に▶を付けて、凡例を横展開できるようにして」
    // への対応: 以前はON時のみ▶を出していたが、推定グループの軸タイルが常に▼を出すのと
    // 揃え、OFFのままでも凡例があれば▶が出るようにした。
    it("観測グループのメンバータイルはOFFのままでも凡例があれば▶展開ボタンが付く", async () => {
      const user = userEvent.setup();
      const layers = groupedLayers();
      const roadType = layers.find((l) => l.id === "roadType")!;
      roadType.on = false;
      roadType.legendDetails = [
        {
          label: "道路の種類",
          legend: [{ key: "primary", label: "幹線道路", color: "#111827", filter: ["literal", true] }],
          hiddenKeys: [],
        },
      ];
      render(<MapOverlayControls {...baseProps()} layers={layers} />);

      await user.click(screen.getByRole("button", { name: "観測" }));
      expect(screen.getByRole("button", { name: "道路の種類の凡例を表示" })).toBeInTheDocument();
    });
  });
});
