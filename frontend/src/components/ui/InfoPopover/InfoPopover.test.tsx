/**
 * `components/ui/InfoPopover/InfoPopover.tsx`——見出し脇の(i)から開く短い説明の外枠。
 *
 * 見るもの: (i)の名前が開閉に合わせて「◯◯を表示」「◯◯を隠す」になること、押すと中身が出てもう一度押すと消えること、
 * 見出しの文言をトリガーの手前に出すこと。
 *
 * ここで見ないもの: トリガーの中身の差し替え（`triggerContent`）——ボタンの中へそのまま置くだけ。
 * 浮きパネルの置き方（`side`）——Radix Popoverの振る舞いで、テスト環境に実寸が無い。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import InfoPopover from "./InfoPopover";

describe("InfoPopover", () => {
  it("押すと中身を出して名前を「隠す」に変え、もう一度押すと消して「表示」に戻す", async () => {
    render(<InfoPopover triggerAriaLabel="欠損割合の見方">説明の文</InfoPopover>);
    expect(screen.queryByText("説明の文")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "欠損割合の見方を表示" }));
    expect(await screen.findByText("説明の文")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "欠損割合の見方を隠す" }));

    expect(screen.queryByText("説明の文")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "欠損割合の見方を表示" })).toBeInTheDocument();
  });

  it("見出しを渡すと、トリガーの手前に出す", () => {
    render(
      <InfoPopover triggerAriaLabel="平均速度の説明" label="平均速度">
        説明の文
      </InfoPopover>,
    );

    const trigger = screen.getByRole("button", { name: "平均速度の説明を表示" });
    expect(trigger.parentElement).toHaveTextContent(/^平均速度/);
  });
});
