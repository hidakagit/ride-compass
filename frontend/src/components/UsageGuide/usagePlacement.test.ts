// @vitest-environment node
/**
 * `components/UsageGuide/usagePlacement.ts`——説明の面を、ほかの部品に重ねない位置へ出す。
 *
 * ここで見ないもの:
 * - 選んだ置き方のとおりにRadixが面を置くこと・実際の画面で重ならないこと → e2e（`e2e/usage-guide.spec.ts`）
 * - 避ける部品の集め方 → `UsageGuide.tsx`（実寸とヒットテストが要り、e2eが通す）
 */
import { describe, expect, it } from "vitest";

import { chooseUsagePlacement } from "./usagePlacement";

const VIEWPORT = { width: 400, height: 800 };
const PANEL = { width: 200, height: 80 };
const OFFSET = 6;
const PADDING = 8;

function box(left: number, top: number, width: number, height: number) {
  return { left, top, width, height };
}

describe("chooseUsagePlacement", () => {
  it("避けるものが無ければ、部品の下に中央を揃えて出す", () => {
    expect(chooseUsagePlacement(box(100, 100, 40, 30), PANEL, VIEWPORT, [], OFFSET, PADDING)).toEqual({
      side: "bottom",
      sideOffset: OFFSET,
      alignOffset: (40 - PANEL.width) / 2,
    });
  });

  it("すぐ下に部品があれば、上に出す", () => {
    const below = box(100, 136, 40, 30);

    expect(chooseUsagePlacement(box(100, 100, 40, 30), PANEL, VIEWPORT, [below], OFFSET, PADDING)).toEqual({
      side: "top",
      sideOffset: OFFSET,
      alignOffset: (40 - PANEL.width) / 2,
    });
  });

  it("画面の右端に縦に並んだ部品は、列の上下を避けて左に出す", () => {
    const anchor = box(352, 100, 40, 30);
    const column = [box(352, 60, 40, 30), box(352, 140, 40, 30)];

    expect(chooseUsagePlacement(anchor, PANEL, VIEWPORT, column, OFFSET, PADDING)).toEqual({
      side: "left",
      sideOffset: OFFSET,
      alignOffset: (30 - PANEL.height) / 2,
    });
  });

  it("部品の周りがほかの部品で埋まっていれば、重ならない所まで離して出す", () => {
    const anchor = box(100, 95, 40, 40);
    const around = [box(0, 0, 400, 95), box(0, 135, 400, 165), box(0, 95, 100, 40), box(140, 95, 260, 40)];

    const placement = chooseUsagePlacement(anchor, PANEL, VIEWPORT, around, OFFSET, PADDING);

    expect(placement.side).toBe("bottom");
    // 埋まった所（下端300）より下で、いちばん近い位置。
    expect(anchor.top + anchor.height + placement.sideOffset).toBeGreaterThanOrEqual(300);
    expect(anchor.top + anchor.height + placement.sideOffset).toBeLessThan(300 + PADDING);
  });

  it("どこに置いても重なるなら、重なるものがいちばん少ない位置に出す", () => {
    // 画面を幅100の縦の帯4本で埋める。幅200の面は、左端を帯の境目（100）に揃えたときだけ2本で済み、ほかは3本にかかる。
    const bands = [0, 100, 200, 300].map((left) => box(left, 0, 100, 800));
    const anchor = box(180, 380, 40, 40);

    expect(chooseUsagePlacement(anchor, PANEL, VIEWPORT, bands, OFFSET, PADDING)).toEqual({
      side: "bottom",
      sideOffset: OFFSET,
      alignOffset: 100 - anchor.left,
    });
  });

  it("面が画面に収まらなければ、既定の下・中央揃えにする（Radixが画面の端へ寄せる）", () => {
    const tall = { width: 200, height: 900 };

    expect(chooseUsagePlacement(box(100, 100, 40, 30), tall, VIEWPORT, [], OFFSET, PADDING)).toEqual({
      side: "bottom",
      sideOffset: OFFSET,
      alignOffset: (40 - tall.width) / 2,
    });
  });
});
