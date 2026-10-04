/**
 * `components/ui/GuideText/GuideText.tsx`——案内の文の中のボタンの名前を、アイコンにして描く。
 *
 * 見るもの: 知っているボタンの名前はかぎ括弧ごとアイコンに替わり、名前は読み上げと吹き出しに残ること、
 * 知らない名前はかぎ括弧ごと文字のまま残ること。
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GuideText } from "./GuideText";

describe("GuideText", () => {
  it("知っているボタンの名前だけをアイコンに替え、名前は読み上げと吹き出しに残す", () => {
    render(
      <p data-testid="guide">
        <GuideText text="「ルート設定」の「ルート生成」を押す" />
      </p>,
    );

    expect(screen.getByTestId("guide")).toHaveTextContent("「ルート設定」のルート生成を押す");
    expect(screen.getByTitle("ルート生成").querySelector("svg")).not.toBeNull();
  });
});
