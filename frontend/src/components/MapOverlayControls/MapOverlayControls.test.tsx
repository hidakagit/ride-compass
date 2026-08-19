import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import MapOverlayControls, { type OverlayLayerChip } from "./MapOverlayControls";

function baseLayers(): OverlayLayerChip[] {
  return [
    { id: "elevation", label: "標高図", on: false },
    { id: "road", label: "路面", on: false },
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
    expect(onToggle).toHaveBeenCalledWith("road", false);
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
      { id: "road", label: "路面", on: false, summary: null, legendDetails: [{ label: "路面の種類", legend: [], hiddenKeys: [] }] }, // OFF
      { id: "route", label: "ルート", on: true, disabled: true, summary: "色分け: 風の影響" }, // disabled
    ];
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    expect(screen.queryByRole("button", { name: "標高図の凡例を表示" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "路面の凡例を表示" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ルートの凡例を表示" })).not.toBeInTheDocument();
  });

  // カテゴリ束ね（改善計画T128）: 同じcategoryを持つチップが2件以上あるときだけ
  // 1個のグループチップへ束ねる。categoryを持たない/1件しかないレイヤーは従来どおり単独。
  describe("カテゴリ束ね（改善計画T128）", () => {
    function groupedLayers(): OverlayLayerChip[] {
      return [
        { id: "elevation", label: "標高図", on: false }, // categoryなし→単独のまま
        { id: "road", label: "道路情報", on: false, category: "roadCondition" },
        { id: "designation", label: "指定路線", on: true, category: "roadCondition" },
        { id: "carStress", label: "車の圧迫感", on: true, category: "trafficSafety", dataNature: "composite" },
        { id: "accidents", label: "事故", on: false, category: "trafficSafety" }, // dataNature省略→raw扱い
      ];
    }

    it("同じcategoryが2件以上あるレイヤーは1個のグループチップへ束ねられ、個別ボタンは出ない", () => {
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      expect(screen.getByRole("button", { name: "標高図" })).toBeInTheDocument(); // categoryなしは単独のまま
      expect(screen.queryByRole("button", { name: "道路情報" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "指定路線" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "道路状態" })).toBeInTheDocument(); // カテゴリ見出しの束ねチップ
      expect(screen.getByRole("button", { name: "交通・安全" })).toBeInTheDocument();
    });

    it("グループチップを開くとメンバーごとのON/OFFボタンが並ぶ", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} onToggle={onToggle} />);

      await user.click(screen.getByRole("button", { name: "道路状態" }));
      const designationToggle = screen.getByRole("button", { name: "指定路線" });
      expect(designationToggle).toHaveAttribute("aria-pressed", "true");

      await user.click(designationToggle);
      expect(onToggle).toHaveBeenCalledWith("designation", false);
    });

    it("メンバーのdataNatureが混在するグループだけ「推定指標（合成）」「観測データ」の小見出しが出る", async () => {
      const user = userEvent.setup();
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);

      // 道路状態（road/designationとも既定dataNature=raw、混在しない）は小見出し無し
      await user.click(screen.getByRole("button", { name: "道路状態" }));
      expect(screen.queryByText("推定指標（合成）")).not.toBeInTheDocument();
      expect(screen.queryByText("観測データ")).not.toBeInTheDocument();

      // 交通・安全（carStress=composite、accidents=raw、混在する）は小見出しが出る
      await user.click(screen.getByRole("button", { name: "交通・安全" }));
      expect(screen.getByText("推定指標（合成）")).toBeInTheDocument();
      expect(screen.getByText("観測データ")).toBeInTheDocument();
    });

    it("いずれかのメンバーがONならグループチップがaria-pressed=trueになる", () => {
      render(<MapOverlayControls {...baseProps()} layers={groupedLayers()} />);
      // road=OFF・designation=ONの道路状態グループ → 全体としてはON扱い
      expect(screen.getByRole("button", { name: "道路状態" })).toHaveAttribute("aria-pressed", "true");
    });
  });
});
