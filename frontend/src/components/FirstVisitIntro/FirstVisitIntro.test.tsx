/**
 * `components/FirstVisitIntro/FirstVisitIntro.tsx`——初めて開いたときだけ地図の上に出す案内。
 *
 * 見るもの: 閉じたことが無ければ見出しを名前に持つ案内を出すこと、最初の一手の場所をスマホとPCで言い分けること、
 * 位置が分からないと分かったら出発地の行を「出発地を地図で選ぶ」の手順にすること、
 * ✕と「はじめる」のどちらで閉じても消え、この端末では次に開いても出ないこと。
 *
 * ここで見ないもの:
 * - 目的・出発地の印・使い方の場所の文言——部品の宣言で、書き写して突き合わせるだけになる
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
  it("閉じたことが無ければ、見出しを名前に持つ案内を出す", () => {
    render(<FirstVisitIntro isMobile={false} locationUnknown={false} />);

    expect(intro()).toBeInTheDocument();
  });

  it.each([
    [true, "下の「ルート設定」を開いて距離を決め、ルート生成を押すと、ルートの候補が地図に出ます。"],
    [false, "左の「ルート設定」で距離を決め、ルート生成を押すと、ルートの候補が地図に出ます。"],
  ])("スマホ（%s）かで、最初の一手の場所を言い分ける", (isMobile, firstStep) => {
    render(<FirstVisitIntro isMobile={isMobile} locationUnknown={false} />);

    expect(screen.getByText(/ルートの候補が地図に出ます/)).toHaveTextContent(firstStep);
  });

  it.each([
    [false, "この印が出発地です（はじめは現在地）。地図の上でつかんで動かせます。"],
    [
      true,
      // 地図で置く操作はアイコンだけなので、名前はかぎ括弧ごとアイコン（読み上げの名前）に替わる。
      "現在地が分からないため、この灰色の印は仮の地点です。「ルート設定」の出発地を地図で選ぶを押して地図をタップすると、そこが出発地になります。",
    ],
  ])("位置が分からないと分かったか（%s）で、出発地の行を言い分ける", (locationUnknown, originLine) => {
    render(<FirstVisitIntro isMobile={false} locationUnknown={locationUnknown} />);

    expect(screen.getByText(/が出発地/)).toHaveTextContent(originLine);
  });

  it.each(["案内を閉じる", "はじめる"])("「%s」を押すと消え、次に開いても出ない", async (name) => {
    const view = render(<FirstVisitIntro isMobile={false} locationUnknown={false} />);

    await userEvent.click(screen.getByRole("button", { name }));

    expect(intro()).not.toBeInTheDocument();
    view.unmount();
    render(<FirstVisitIntro isMobile={false} locationUnknown={false} />);
    expect(intro()).not.toBeInTheDocument();
  });
});
