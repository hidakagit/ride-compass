/**
 * `components/ui/Button/Button.tsx`——押すと1回動く操作のボタン。
 *
 * 見るもの: 種類を指定しないとフォームを送らないこと、指定した種類とそれ以外の属性がそのまま届くこと、
 * 参照（ref）が中のボタンへ届くこと（`asChild`で包む呼び出し側が位置と開閉を付けるのに使う）、
 * パネルの操作のボタン（アイコンだけ）は名前を吹き出し（`title`）にも出すこと。
 *
 * ここで見ないもの: 役割（`variant`）・大きさ（`size`）ごとの見た目——クラス文字列はこの部品の宣言で、
 * テスト環境はTailwindの規則を作らないため、書き写して突き合わせる以外に確かめようがない。
 * 使い方の文（`usage`）が説明を見る状態で出ること——読む側の`components/UsageGuide/UsageGuide.test.tsx`が本物のボタンで見る。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button";

function renderInForm(button: React.ReactNode) {
  const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
  render(<form onSubmit={onSubmit}>{button}</form>);
  return onSubmit;
}

describe("Button", () => {
  it("種類を指定しないと、フォームの中で押してもフォームを送らない", async () => {
    const onClick = vi.fn();
    const onSubmit = renderInForm(<Button onClick={onClick}>保存</Button>);

    await userEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("種類に送信を指定すると、押したときにフォームを送る", async () => {
    const onSubmit = renderInForm(<Button type="submit">送る</Button>);

    await userEvent.click(screen.getByRole("button", { name: "送る" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("押せない指定と名前の属性はそのまま届き、押せないときは押しても呼ばれない", async () => {
    const onClick = vi.fn();
    render(
      <Button aria-label="閉じる" disabled onClick={onClick}>
        ✕
      </Button>,
    );

    const button = screen.getByRole("button", { name: "閉じる" });
    await userEvent.click(button);

    expect(button).toBeDisabled();
    expect(onClick).not.toHaveBeenCalled();
  });

  it("パネルの操作のボタンは、名前を吹き出しにも出す", () => {
    render(
      <Button size="panelIcon" aria-label="ルート生成">
        <svg />
      </Button>,
    );

    expect(screen.getByRole("button", { name: "ルート生成" })).toHaveAttribute("title", "ルート生成");
  });

  it("参照は中のボタンを指す", () => {
    const ref = createRef<HTMLButtonElement>();
    render(<Button ref={ref}>押す</Button>);

    expect(ref.current).toBe(screen.getByRole("button", { name: "押す" }));
  });
});
