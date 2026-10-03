/**
 * `components/FirstVisitIntro/FirstVisitIntro.tsx`——初めて開いたときだけ地図の上に出す案内。
 *
 * 見るもの: 閉じたことが無ければ見出しを名前に持つ案内を出すこと、最初の一手の場所をスマホとPCで言い分けること、
 * ✕と「はじめる」のどちらで閉じても消え、この端末では次に開いても出ないこと。
 *
 * ここで見ないもの:
 * - 保存値の読み書きと、読めない値を既定へ戻すこと → `hooks/useStoredState.ts`
 * - マウントするまで出さないこと（サーバーで描いたHTMLに載せない）——テスト環境の`render`はマウントまで同期で進み、
 *   マウント前の描画を取り出せない
 *
 * 閉じたことはテスト環境の`localStorage`に置く。テストをまたいで残るので、テストごとに空にする。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import FirstVisitIntro from "./FirstVisitIntro";

function intro() {
  return screen.queryByRole("region", { name: "RideCompass" });
}

afterEach(() => {
  localStorage.clear();
});

describe("FirstVisitIntro", () => {
  it("閉じたことが無ければ、見出しを名前に持つ案内に、目的・出発地の印・使い方の場所を出す", () => {
    render(<FirstVisitIntro isMobile={false} />);

    const region = intro();
    expect(region).toHaveTextContent("ロードバイクで走る周回ルートを、道の走りやすさを評価して作ります。");
    expect(region).toHaveTextContent("この印が出発地です（はじめは現在地）。地図の上でつかんで動かせます。");
    expect(region).toHaveTextContent("右上のメニュー（）の「使い方を見る」から、部品を押して見られます。");
    expect(screen.getByRole("img", { name: "メニュー" })).toBeInTheDocument();
  });

  it.each([
    [true, "下の「ルート設定」を開いて距離を決め、「生成」を押すと、ルートの候補が地図に出ます。"],
    [false, "左の「ルート設定」で距離を決め、「生成」を押すと、ルートの候補が地図に出ます。"],
  ])("スマホ（%s）かで、最初の一手の場所を言い分ける", (isMobile, firstStep) => {
    render(<FirstVisitIntro isMobile={isMobile} />);

    expect(screen.getByText(firstStep)).toBeInTheDocument();
  });

  it.each(["案内を閉じる", "はじめる"])("「%s」を押すと消え、次に開いても出ない", async (name) => {
    const view = render(<FirstVisitIntro isMobile={false} />);

    await userEvent.click(screen.getByRole("button", { name }));

    expect(intro()).not.toBeInTheDocument();
    view.unmount();
    render(<FirstVisitIntro isMobile={false} />);
    expect(intro()).not.toBeInTheDocument();
  });
});
