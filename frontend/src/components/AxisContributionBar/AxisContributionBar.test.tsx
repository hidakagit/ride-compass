import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import AxisContributionBar from "./AxisContributionBar";

const AXES: PreferenceAxisDef[] = [
  { axisId: "axis_sample", label: "見本の軸", description: "説明", dedicatedWayValueLayer: false },
  { axisId: "wind", label: "風", description: "説明", dedicatedWayValueLayer: true },
  { axisId: "night", label: "夜間", description: "説明", dedicatedWayValueLayer: false },
];

const AXIS_COLORS: Record<string, string> = { axis_sample: "#111111", wind: "#222222", night: "#333333" };

describe("AxisContributionBar", () => {
  it("contributionsにキーが無い軸は表示しない（呼び出し側で絞り込まなくてよい）", () => {
    render(<AxisContributionBar axes={AXES} contributions={{ axis_sample: 30, night: 5 }} axisColors={AXIS_COLORS} />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    // 軸の名前はチップの文字ではなくアクセシブル名が持つ（チップはアイコンと値だけ）。
    expect(screen.queryByLabelText("風")).not.toBeInTheDocument();
  });

  it("値が0の軸は表示しない（backendは重み0の軸もキー付きで値0.0を返すため、キーの有無だけでは絞り込めない）", () => {
    render(
      <AxisContributionBar
        axes={AXES}
        contributions={{ axis_sample: 30, wind: 0, night: 5 }}
        axisColors={AXIS_COLORS}
      />,
    );

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(screen.queryByText("風")).not.toBeInTheDocument();
  });

  it("負の値（クランプ前）は0ではないため除外しない", () => {
    render(<AxisContributionBar axes={AXES} contributions={{ axis_sample: -10, night: 5 }} axisColors={AXIS_COLORS} />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(screen.getByLabelText("見本の軸")).toBeInTheDocument();
  });

  it("軸カタログの並び順で凡例を表示し、値をそのまま(小数1桁)表示する", () => {
    render(
      <AxisContributionBar axes={AXES} contributions={{ night: 5.25, axis_sample: 30.1 }} axisColors={AXIS_COLORS} />,
    );

    const items = screen.getAllByRole("listitem");
    expect(within(items[0]).getByLabelText("見本の軸")).toBeInTheDocument();
    expect(items[0]).toHaveTextContent("30.1");
    expect(within(items[1]).getByLabelText("夜間")).toBeInTheDocument();
    expect(items[1]).toHaveTextContent("5.3");
  });

  it("各セグメントの幅はcontributionsの値そのもの（%）、色はaxisColorsを使う", () => {
    const { container } = render(
      <AxisContributionBar axes={AXES} contributions={{ axis_sample: 30, night: 5 }} axisColors={AXIS_COLORS} />,
    );

    const segments = Array.from(screen.getByRole("img", { name: "難易度の内訳" }).children) as HTMLElement[];
    expect(segments).toHaveLength(2);
    expect(segments[0].style.width).toBe("30%");
    expect(segments[0].style.background).toBe("#111111");
    expect(segments[1].style.width).toBe("5%");
  });

  it("heightRatioは帯の高さの倍率になる（長さ＝難易度と合わせて面積が負荷になる）", () => {
    const { container } = render(
      <AxisContributionBar
        axes={AXES}
        contributions={{ axis_sample: 30, night: 5 }}
        axisColors={AXIS_COLORS}
        heightRatio={1.43}
      />,
    );

    const bar = screen.getByRole("img", { name: "難易度の内訳" });
    expect(bar.style.getPropertyValue("--load-bar-height-ratio")).toBe("1.43");
  });

  it("heightRatioを渡さない呼び出し側（距離を持たない区間の内訳）は長さだけの帯になる", () => {
    const { container } = render(
      <AxisContributionBar axes={AXES} contributions={{ axis_sample: 30, night: 5 }} axisColors={AXIS_COLORS} />,
    );

    const bar = screen.getByRole("img", { name: "難易度の内訳" });
    expect(bar.style.getPropertyValue("--load-bar-height-ratio")).toBe("1");
  });

  it("contributionsが空なら何も描画しない（呼び出し側の空状態文言に委ねる）", () => {
    const { container } = render(<AxisContributionBar axes={AXES} contributions={{}} axisColors={AXIS_COLORS} />);

    expect(container.firstChild).toBeNull();
  });

  it("renderDetailを渡すと凡例チップが押せる詳細の入口になる", async () => {
    const user = userEvent.setup();
    render(
      <AxisContributionBar
        axes={AXES}
        contributions={{ axis_sample: 30, night: 5 }}
        axisColors={AXIS_COLORS}
        renderDetail={(axis) => <span>{`${axis.label}の詳細本文`}</span>}
      />,
    );

    await user.click(screen.getByRole("button", { name: "見本の軸の詳細を表示" }));

    expect(await screen.findByText("見本の軸の詳細本文")).toBeInTheDocument();
  });

  it("renderDetailを渡さない呼び出し側（軸ごとの詳細を持たない区間詳細）では押せる要素を作らない", () => {
    render(<AxisContributionBar axes={AXES} contributions={{ axis_sample: 30, night: 5 }} axisColors={AXIS_COLORS} />);

    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByLabelText("見本の軸")).toBeInTheDocument();
  });

  it("renderDetailを渡さない呼び出しでは、チップを「押せない印」にしない", () => {
    // 押せる／押せないの区別が無い場面で全チップへ印を付けると、凡例全体が薄く描かれる。
    const { container } = render(
      <AxisContributionBar axes={AXES} contributions={{ axis_sample: 30, night: 5 }} axisColors={AXIS_COLORS} />,
    );

    expect(container.querySelectorAll('[data-checked="false"]')).toHaveLength(0);
  });

  it("legendAxesを渡すと、帯グラフに出ない軸も凡例に残る", () => {
    // 帯グラフ（axes）は寄与のある軸だけ、凡例（legendAxes）は詳細を持つ軸すべて。
    // このpropが無いと「効くはずの軸が効かなかった」ことが画面から消える。
    render(
      <AxisContributionBar
        axes={[AXES[0]]}
        legendAxes={AXES}
        contributions={{ axis_sample: 30 }}
        axisColors={AXIS_COLORS}
        renderDetail={(axis) => <span>{axis.label}</span>}
      />,
    );

    expect(screen.getByRole("button", { name: "夜間の詳細を表示" })).toBeInTheDocument();
  });

  it("renderDetailは軸あたり1回だけ呼ぶ", () => {
    // 絞り込みと本体で別々に呼ぶと、片方で組み立てたJSXがそのまま捨てられる。
    const calls: string[] = [];
    render(
      <AxisContributionBar
        axes={AXES}
        contributions={{ axis_sample: 30, night: 5 }}
        axisColors={AXIS_COLORS}
        renderDetail={(axis) => {
          calls.push(axis.axisId);
          return <span>{axis.label}</span>;
        }}
      />,
    );

    expect(calls).toEqual([...new Set(calls)]);
  });

  it("値が0-100の範囲外でもクランプする", () => {
    const { container } = render(
      <AxisContributionBar axes={AXES} contributions={{ axis_sample: -10, night: 150 }} axisColors={AXIS_COLORS} />,
    );

    const segments = Array.from(screen.getByRole("img", { name: "難易度の内訳" }).children) as HTMLElement[];
    expect(segments[0].style.width).toBe("0%");
    expect(segments[1].style.width).toBe("100%");
  });
});
