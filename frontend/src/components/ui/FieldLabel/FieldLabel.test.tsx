/**
 * `components/ui/FieldLabel/FieldLabel.tsx`——項目の名前と、その脇の(i)から開く説明。
 *
 * 見るもの: 名前が出ること、(i)の名前が項目の名前から作られること、押すと説明が出ること。
 *
 * ここで見ないもの:
 * - (i)の開閉で名前が「表示」「隠す」に変わること・浮きパネルの置き方 → `components/ui/InfoPopover/InfoPopover.tsx`
 *   （この部品は開閉の状態を持たない）
 * - 名前を見た目だけ隠す指定（`hideLabel`）——隠すのはTailwindの`sr-only`で、テスト環境は規則を作らない。
 *   読み上げの名前は隠しても変わらない
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { FieldLabel } from "./FieldLabel";

describe("FieldLabel", () => {
  it("名前を出し、脇の(i)を押すと説明が出る", async () => {
    render(<FieldLabel label="平均速度" description="信号待ちを含まない巡航の速さ" />);

    expect(screen.getByText("平均速度")).toBeInTheDocument();
    expect(screen.queryByText("信号待ちを含まない巡航の速さ")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "平均速度の説明を表示" }));

    expect(await screen.findByText("信号待ちを含まない巡航の速さ")).toBeInTheDocument();
  });
});
