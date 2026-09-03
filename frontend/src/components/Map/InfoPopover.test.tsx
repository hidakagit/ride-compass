import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import InfoPopover from "./InfoPopover";

// 改善計画T525: 軸チップの説明文・重み配分/地図の色分けの凡例一覧の4箇所で重複していた
// 「(i)アイコン→ポップオーバー」の外枠を共通化したコンポーネント。トリガーの見た目・
// アクセシブル名と、中身（children）がそのまま出ることだけを検証する（中身の実際の内容は
// 呼び出し側のテストが担う）。
describe("InfoPopover", () => {
  it("初期状態では中身を表示しない", () => {
    render(
      <InfoPopover triggerClassName="trigger" triggerAriaLabel="説明を表示" contentClassName="content">
        中身のテキスト
      </InfoPopover>
    );
    expect(screen.queryByText("中身のテキスト")).not.toBeInTheDocument();
  });

  it("トリガーをクリックするとchildrenがポップオーバーとして表示される", async () => {
    const user = userEvent.setup();
    render(
      <InfoPopover triggerClassName="trigger" triggerAriaLabel="説明を表示" contentClassName="content">
        中身のテキスト
      </InfoPopover>
    );
    await user.click(screen.getByRole("button", { name: "説明を表示" }));
    expect(await screen.findByText("中身のテキスト")).toBeInTheDocument();
  });
});
