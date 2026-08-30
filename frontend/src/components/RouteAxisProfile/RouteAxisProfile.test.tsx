import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import RouteAxisProfile from "./RouteAxisProfile";

const AXES: PreferenceAxisDef[] = [
  { axisId: "car_stress", label: "車の圧迫感", description: "" },
  { axisId: "wind", label: "風", description: "" },
  { axisId: "night", label: "夜間", description: "" },
];

describe("RouteAxisProfile", () => {
  it("axisDifficultiesに値を持つ軸だけを、軸カタログの並び順で横棒グラフ表示する", () => {
    render(
      <RouteAxisProfile
        axes={AXES}
        axisDifficulties={{ car_stress: 72.4, night: 10 }}
      />,
    );

    // 軸カタログの並び順（car_stress→wind→night）のうち、値を持つ2軸だけが表示される
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("車の圧迫感");
    expect(items[1]).toHaveTextContent("夜間");
    expect(screen.queryByText("風")).not.toBeInTheDocument();

    // 表示値は四捨五入した整数
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
  });

  it("axisDifficultiesが空のときは案内文を表示する", () => {
    render(<RouteAxisProfile axes={AXES} axisDifficulties={{}} />);

    expect(screen.getByText("このルートで表示できる評価軸データがありません")).toBeInTheDocument();
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });

  it("難易度バーがdisplay:blockで描画される（review:ui F-2の再発防止。trackもbarも<span>のため、" +
    "displayを明示しない既定のinlineのままだとwidthスタイルがCSS仕様上無視され、バーが幅0で" +
    "描画されなくなる）", () => {
    const { container } = render(
      <RouteAxisProfile axes={AXES} axisDifficulties={{ car_stress: 72.4 }} />,
    );

    const bar = container.querySelector('[class*="bar"]');
    expect(bar).not.toBeNull();
    expect(getComputedStyle(bar as Element).display).toBe("block");
  });
});
