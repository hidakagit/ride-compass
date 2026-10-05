/**
 * `app/admin/page.tsx`——管理画面の入口の状態: 開いたときのタブ、システム状況の開閉、
 * デバッグモード中の案内。
 *
 * 各タブのパネルは本物を描き、パネルが取りに行く backend への要求には応えないまま止めておく（中身の振る舞いは
 * それぞれのファイルが持つ）。どのタブにどのパネルを置くかは画面の宣言で、ここでは書き写さない。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { heldReplies, onBackend, onSameOrigin } from "@/testing/backendServer";

import AdminPage from "./page";

beforeEach(() => {
  onSameOrigin("GET", "/admin/api/axis-definitions", heldReplies().reply);
  onBackend("GET", "/api/axis-catalog", heldReplies().reply);
  onBackend("GET", "/health", heldReplies().reply);
  onBackend("GET", "/api/debug/stats", heldReplies().reply);
  onSameOrigin("GET", "/api/version", heldReplies().reply);
});

async function openDeveloperTab() {
  const user = userEvent.setup();
  render(<AdminPage />);
  await user.click(screen.getByRole("tab", { name: "開発者" }));
  return user;
}

describe("AdminPage", () => {
  it("開くと軸スタジオのタブが選ばれる", () => {
    render(<AdminPage />);

    expect(screen.getByRole("tab", { name: "軸スタジオ" })).toHaveAttribute("aria-selected", "true");
  });

  it("システム状況は閉じた状態で始まり、ボタンで開閉し、パネル側から閉じても戻る", async () => {
    const user = await openDeveloperTab();

    await user.click(screen.getByRole("button", { name: "システム状況を表示" }));
    expect(screen.getByRole("button", { name: "システム状況を閉じる" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "システム状況を隠す" }));
    expect(screen.queryByRole("button", { name: "システム状況を閉じる" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "システム状況を表示" }));
    await user.click(screen.getByRole("button", { name: "システム状況を閉じる" }));
    expect(screen.queryByRole("button", { name: "システム状況を閉じる" })).not.toBeInTheDocument();
  });

  it("デバッグモード中だけ、ログの表示はトップページで行うと案内する", async () => {
    const user = await openDeveloperTab();
    const debugMode = screen.getByRole("checkbox", { name: "デバッグログを表示" });

    await user.click(debugMode);
    expect(screen.getByText(/トップページ/)).toBeInTheDocument();

    await user.click(debugMode);
    expect(screen.queryByText(/トップページ/)).not.toBeInTheDocument();
  });
});
