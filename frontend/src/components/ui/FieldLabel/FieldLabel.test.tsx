/**
 * `components/ui/FieldLabel/FieldLabel.tsx`——項目の名前と、その脇の(i)から開く説明。
 *
 * 見るもの: (i)の名前が項目の名前から作られること。
 *
 * ここで見ないもの:
 * - 名前を出すこと・押すと説明が出ること・(i)の開閉で名前が「表示」「隠す」に変わること・浮きパネルの置き方
 *   → `components/ui/InfoPopover/InfoPopover.tsx`（この部品は名前と説明をそのまま渡し、開閉の状態を持たない）
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FieldLabel } from "./FieldLabel";

describe("FieldLabel", () => {
  it("脇の(i)の名前を、項目の名前から作る", () => {
    render(<FieldLabel label="平均速度" description="信号待ちを含まない巡航の速さ" />);

    expect(screen.getByRole("button", { name: "平均速度の説明を表示" })).toBeInTheDocument();
  });
});
