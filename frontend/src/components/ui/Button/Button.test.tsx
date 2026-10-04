/**
 * `components/ui/Button/Button.tsx`——押すと1回動く操作のボタン。
 *
 * 見るもの: 種類を指定しないとフォームを送らないこと、パネルの操作のボタン（アイコンだけ）は名前を吹き出し（`title`）にも出すこと。
 *
 * ここで見ないもの: 役割（`variant`）・大きさ（`size`）ごとの見た目——クラス文字列はこの部品の宣言で、
 * テスト環境はTailwindの規則を作らないため、書き写して突き合わせる以外に確かめようがない。
 * 使い方の文（`usage`）が説明を見る状態で出ること——読む側の`components/UsageGuide/UsageGuide.test.tsx`が本物のボタンで見る。
 * 指定した種類・それ以外の属性・参照（ref）——中のボタンへそのまま渡すだけ。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button";

describe("Button", () => {
  it("種類を指定しないと、フォームの中で押してもフォームを送らない", async () => {
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <Button>保存</Button>
      </form>,
    );

    await userEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("パネルの操作のボタンは、名前を吹き出しにも出す", () => {
    render(
      <Button size="panelIcon" aria-label="ルート生成">
        <svg />
      </Button>,
    );

    expect(screen.getByRole("button", { name: "ルート生成" })).toHaveAttribute("title", "ルート生成");
  });
});
