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

    it("観測グループを開くとcategory小見出し（道路状態・交通・安全）ごとにメンバーのON/OFFボタンが並ぶ", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "観測" }));
      expect(screen.getByText("道路状態")).toBeInTheDocument();
      expect(screen.getByText("交通・安全")).toBeInTheDocument();
      const designationToggle = screen.getByRole("button", { name: "指定路線" });
      expect(designationToggle).toHaveAttribute("aria-pressed", "true");

      await user.click(designationToggle);
      expect(onToggle).toHaveBeenCalledWith("designation", false);
      // compositeのcarStressは観測グループに含まれない
      expect(screen.queryByRole("button", { name: "車の圧迫感" })).not.toBeInTheDocument();
    });

    it("推定グループを開くと確定命名表の6軸すべてが並び、専用レイヤーの無い軸は薄字表示になる", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      await user.click(screen.getByRole("button", { name: "推定" }));
      // レイヤーを持つ軸（car_stress）はON/OFFトグル付きの行
      const carStressToggle = screen.getByRole("button", { name: "車の圧迫感" });
      expect(carStressToggle).toHaveAttribute("aria-pressed", "true");
      // レイヤーの無い軸（勾配・舗装質・夜間）は正式名だけの薄字表示（トグルボタンなし）
      expect(screen.getByText("勾配")).toBeInTheDocument();
      expect(screen.getByText("標高レイヤーで確認できます")).toBeInTheDocument();
      expect(screen.getByText("舗装質")).toBeInTheDocument();
      expect(screen.getByText("路面の種類レイヤーで確認できます")).toBeInTheDocument();
      expect(screen.getByText("夜間")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "勾配" })).not.toBeInTheDocument();
      // レイヤーはあるがlayers propに渡されていない軸（停止密度・事故密度）もトグル無しの
      // 情報行として一覧に含まれる（layersに無いのでLayerChipを引けない）
      expect(screen.getByText("停止密度")).toBeInTheDocument();
      expect(screen.getByText("事故密度")).toBeInTheDocument();
    });

    it("推定グループはcompositeチップが1件も渡されなくても常に表示される（SECONDARY_AXESの薄字項目があるため）", () => {
      render(<MapOverlayControls {...baseProps()} />); // baseLayers()にcompositeチップなし
      expect(screen.getByRole("button", { name: "推定" })).toBeInTheDocument();
    });

    it("いずれかのメンバーがONならグループチップがaria-pressed=trueになる", () => {
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      // roadType=OFF・designation=ONの観測グループ → 全体としてはON扱い
      expect(screen.getByRole("button", { name: "観測" })).toHaveAttribute("aria-pressed", "true");
      // carStress=ONの推定グループ → 全体としてはON扱い
      expect(screen.getByRole("button", { name: "推定" })).toHaveAttribute("aria-pressed", "true");
    });

    // 推定グループの各軸に材料一覧を出す（改善計画T167）。axisMaterials（T164）から導出した
    // 一次属性を、表示レイヤーの有無で「材料」「地図では未表示の材料」の2行に分ける。
    it("推定グループの各軸の下に材料一覧が出て、表示レイヤーの有無で分けて表示される", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      await user.click(screen.getByRole("button", { name: "推定" }));

      // 車の圧迫感: 道路種別・インフラ・指定路線はレイヤーあり、車線数・制限速度・車両可否は無し
      expect(screen.getByText("材料: 道路種別・インフラ・指定路線")).toBeInTheDocument();
      expect(screen.getByText("地図では未表示の材料: 車線数・制限速度・車両可否")).toBeInTheDocument();

      // 勾配: 材料の標高にはレイヤーがある（未表示材料は無し）
      expect(screen.getByText("材料: 標高")).toBeInTheDocument();

      // 夜間: 材料（街灯・トンネル）はどちらもレイヤーが無い
      expect(screen.getByText("地図では未表示の材料: 街灯・トンネル")).toBeInTheDocument();
    });
  });
});
