/**
 * `components/AxisContributionBar/AxisContributionBar.tsx`——重み付きの寄与の内訳（積み上げの帯1本と凡例）と、
 * 寄与があるかの判定（`hasContribution`）。
 *
 * 見るもの: 寄与のある軸だけを`axes`の順に帯へ積むこと、帯の長さと添える値（0〜100へ寄せる）、軸の色と
 * 色の無い軸の色、凡例に並ぶ軸（既定・`legendAxes`・`renderDetail`がnullを返した軸）とチップに出す値、
 * チップを、詳細を開くボタンにすること、寄与が1つも無ければ何も描かないこと。
 *
 * ここで見ないもの: 軸のアイコンの引き方 → `components/ui/icons/axisIconPalette.tsx`。詳細の中身 → 呼び出し側
 * （`features/route/RouteOutcome`等）。チップを押すと詳細が出ること → `components/ui/InfoPopover/InfoPopover.tsx`
 * （詳細とチップの中身をそのまま渡すだけ）。
 *
 * 軸は架空のもの（`axis_a`等）を`src/testing/catalogAxes.ts`の雛形から作る。
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { catalogAxisFromEntry } from "@/lib/catalogAxis";
import { catalogEntry } from "@/testing/catalogAxes";
import AxisContributionBar, { hasContribution } from "./AxisContributionBar";

const A = catalogAxisFromEntry(catalogEntry({ axis_id: "axis_a", label: "軸A" }));
const B = catalogAxisFromEntry(catalogEntry({ axis_id: "axis_b", label: "軸B" }));
const C = catalogAxisFromEntry(catalogEntry({ axis_id: "axis_c", label: "軸C" }));
const COLORS = { axis_a: "rgb(10, 20, 30)", axis_b: "rgb(40, 50, 60)", axis_c: "rgb(70, 80, 90)" };

type Props = React.ComponentProps<typeof AxisContributionBar>;

function renderBar(props: Partial<Props> = {}) {
  return render(
    <AxisContributionBar
      axes={[A, B, C]}
      contributions={{}}
      axisColors={COLORS}
      renderDetail={(axis) => `${axis.label}の中身`}
      {...props}
    />,
  );
}

/** 凡例のチップ（詳細を開くボタン）。 */
function chip(label: string): HTMLElement {
  return screen.getByRole("button", { name: `${label}の詳細を表示` });
}

/** 帯の一片（名前と値を`title`に持つ）を、帯に積まれた順に。 */
function segments(): HTMLElement[] {
  return Array.from(screen.getByRole("img", { name: "難易度の内訳" }).children) as HTMLElement[];
}

/** 凡例のチップに付いた軸の色。 */
function chipColor(chip: HTMLElement): string {
  const icon = chip.querySelector<HTMLElement>('[aria-hidden="true"]');
  if (!icon) throw new Error("チップのアイコンが無い");
  return icon.style.color;
}

describe("hasContribution", () => {
  it.each([
    ["キーが無い", {}, false],
    ["0", { axis_a: 0 }, false],
    ["0でない値", { axis_a: 0.4 }, true],
  ])("寄与が%sなら%s", (_, contributions, expected) => {
    expect(hasContribution(contributions, "axis_a")).toBe(expected);
  });
});

describe("AxisContributionBar", () => {
  it("寄与のある軸が無ければ、凡例の軸や詳細があっても何も描かない", () => {
    const { container } = renderBar({ contributions: { axis_a: 0 }, legendAxes: [A, B] });

    expect(container).toBeEmptyDOMElement();
  });

  it("寄与のある軸だけを`axes`の順に帯へ積み、長さと名前・値を添える", () => {
    renderBar({ contributions: { axis_c: 12.34, axis_b: 0, axis_a: 30 } });

    expect(segments().map((segment) => [segment.title, segment.style.width])).toEqual([
      ["軸A 30.0", "30%"],
      ["軸C 12.3", "12.34%"],
    ]);
  });

  it("帯の長さと添える値は0〜100へ寄せ、凡例の値は寄せずに出す", () => {
    renderBar({ contributions: { axis_a: 120, axis_b: -5 } });

    expect(segments().map((segment) => [segment.title, segment.style.width])).toEqual([
      ["軸A 100.0", "100%"],
      ["軸B 0.0", "0%"],
    ]);
    expect(chip("軸A")).toHaveTextContent("120.0");
    expect(chip("軸B")).toHaveTextContent("-5.0");
  });

  it("帯と凡例は軸の色で塗り、色の無い軸はどれも同じ色にする", () => {
    renderBar({ contributions: { axis_a: 10, axis_b: 20, axis_c: 30 }, axisColors: { axis_a: COLORS.axis_a } });

    const [a, b, c] = segments();
    expect(a.style.background).toBe(COLORS.axis_a);
    expect(chipColor(chip("軸A"))).toBe(COLORS.axis_a);
    expect(b.style.background).not.toBe("");
    expect(b.style.background).not.toBe(COLORS.axis_a);
    expect(c.style.background).toBe(b.style.background);
    expect(chipColor(chip("軸B"))).toBe(b.style.background);
  });

  it("凡例の軸を渡さなければ、帯に積んだ軸だけを詳細を開くチップにして値を出す", () => {
    renderBar({ contributions: { axis_a: 30, axis_c: 12.34 } });

    const chips = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(
      chips.map((item) => [within(item).getByRole("button").getAttribute("aria-label"), item.textContent]),
    ).toEqual([
      ["軸Aの詳細を表示", "30.0"],
      ["軸Cの詳細を表示", "12.3"],
    ]);
  });

  it("凡例の軸を渡すと、その順にすべて並べ、寄与の無い軸は値を出さない", () => {
    renderBar({ contributions: { axis_a: 30 }, legendAxes: [C, A, B] });

    const chips = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(
      chips.map((item) => [within(item).getByRole("button").getAttribute("aria-label"), item.textContent]),
    ).toEqual([
      ["軸Cの詳細を表示", ""],
      ["軸Aの詳細を表示", "30.0"],
      ["軸Bの詳細を表示", ""],
    ]);
  });

  it("詳細がnullの軸は凡例から落とす", () => {
    renderBar({
      contributions: { axis_a: 30, axis_b: 5 },
      legendAxes: [A, B, C],
      renderDetail: (axis) => (axis.axisId === "axis_b" ? null : `${axis.label}の中身`),
    });

    const chips = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(chips.map((item) => within(item).getByRole("button").getAttribute("aria-label"))).toEqual([
      "軸Aの詳細を表示",
      "軸Cの詳細を表示",
    ]);
  });
});
