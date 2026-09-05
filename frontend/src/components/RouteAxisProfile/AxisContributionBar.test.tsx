import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import AxisContributionBar from "./AxisContributionBar";

const AXES: PreferenceAxisDef[] = [
  { axisId: "car_stress", label: "車の圧迫感", description: "説明", dedicatedWayValueLayer: false },
  { axisId: "wind", label: "風", description: "説明", dedicatedWayValueLayer: true },
  { axisId: "night", label: "夜間", description: "説明", dedicatedWayValueLayer: false },
];

const AXIS_COLORS: Record<string, string> = { car_stress: "#111111", wind: "#222222", night: "#333333" };

describe("AxisContributionBar", () => {
  it("contributionsにキーが無い軸は表示しない（呼び出し側で絞り込まなくてよい）", () => {
    render(
      <AxisContributionBar
        axes={AXES}
        contributions={{ car_stress: 30, night: 5 }}
        axisColors={AXIS_COLORS}
      />
    );

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(screen.queryByText("風")).not.toBeInTheDocument();
  });

  it("値が0の軸は表示しない（backendは重み0の軸もキー付きで値0.0を返すため、キーの有無だけでは絞り込めない）", () => {
    render(
      <AxisContributionBar
        axes={AXES}
        contributions={{ car_stress: 30, wind: 0, night: 5 }}
        axisColors={AXIS_COLORS}
      />
    );

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(screen.queryByText("風")).not.toBeInTheDocument();
  });

  it("負の値（クランプ前）は0ではないため除外しない", () => {
    render(
      <AxisContributionBar
        axes={AXES}
        contributions={{ car_stress: -10, night: 5 }}
        axisColors={AXIS_COLORS}
      />
    );

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(screen.getByText("車の圧迫感")).toBeInTheDocument();
  });

  it("軸カタログの並び順で凡例を表示し、値をそのまま(小数1桁)表示する", () => {
    render(
      <AxisContributionBar
        axes={AXES}
        contributions={{ night: 5.25, car_stress: 30.1 }}
        axisColors={AXIS_COLORS}
      />
    );

    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("車の圧迫感");
    expect(items[0]).toHaveTextContent("30.1");
    expect(items[1]).toHaveTextContent("夜間");
    expect(items[1]).toHaveTextContent("5.3");
  });

  it("各セグメントの幅はcontributionsの値そのもの（%）、色はaxisColorsを使う", () => {
    const { container } = render(
      <AxisContributionBar
        axes={AXES}
        contributions={{ car_stress: 30, night: 5 }}
        axisColors={AXIS_COLORS}
      />
    );

    const segments = Array.from(container.querySelectorAll('[class*="stackSegment"]')) as HTMLElement[];
    expect(segments).toHaveLength(2);
    expect(segments[0].style.width).toBe("30%");
    expect(segments[0].style.background).toBe("#111111");
    expect(segments[1].style.width).toBe("5%");
  });

  it("contributionsが空なら何も描画しない（呼び出し側の空状態文言に委ねる）", () => {
    const { container } = render(
      <AxisContributionBar axes={AXES} contributions={{}} axisColors={AXIS_COLORS} />
    );

    expect(container.firstChild).toBeNull();
  });

  it("値が0-100の範囲外でもクランプする", () => {
    const { container } = render(
      <AxisContributionBar
        axes={AXES}
        contributions={{ car_stress: -10, night: 150 }}
        axisColors={AXIS_COLORS}
      />
    );

    const segments = Array.from(container.querySelectorAll('[class*="stackSegment"]')) as HTMLElement[];
    expect(segments[0].style.width).toBe("0%");
    expect(segments[1].style.width).toBe("100%");
  });
});
