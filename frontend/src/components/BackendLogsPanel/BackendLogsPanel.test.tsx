import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import BackendLogsPanel from "./BackendLogsPanel";
import { getRecentLogs } from "@/services/debugAdminApi";

vi.mock("@/services/debugAdminApi", () => ({
  getRecentLogs: vi.fn(),
}));

describe("BackendLogsPanel", () => {
  it("取得ボタン押下でgetRecentLogsを呼び、返ってきた行を表示する", async () => {
    vi.mocked(getRecentLogs).mockResolvedValue(["2026-09-01 [WARNING] a", "2026-09-01 [WARNING] b"]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "取得" }));
    });

    expect(getRecentLogs).toHaveBeenCalledWith({ contains: undefined, minLevel: "WARNING", limit: 200 });
    expect(screen.getByText(/2026-09-01 \[WARNING\] a/)).toBeInTheDocument();
    expect(screen.getByText(/2026-09-01 \[WARNING\] b/)).toBeInTheDocument();
  });

  it("絞り込みテキストを入力してから取得すると、containsを渡す", async () => {
    vi.mocked(getRecentLogs).mockResolvedValue([]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.type(screen.getByPlaceholderText("絞り込み（部分一致、例: jma-tile）"), "jma-tile");
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "取得" }));
    });

    expect(getRecentLogs).toHaveBeenCalledWith({ contains: "jma-tile", minLevel: "WARNING", limit: 200 });
    expect(screen.getByText("該当するログはありません。")).toBeInTheDocument();
  });

  it("最小レベルのプルダウンで選択した値をminLevelとして渡す", async () => {
    vi.mocked(getRecentLogs).mockResolvedValue([]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.selectOptions(screen.getByLabelText("最小レベル"), "ERROR");
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "取得" }));
    });

    expect(getRecentLogs).toHaveBeenCalledWith({ contains: undefined, minLevel: "ERROR", limit: 200 });
  });

  it("ログ全体をコピーボタンで表示中の全行をクリップボードへコピーする", async () => {
    vi.mocked(getRecentLogs).mockResolvedValue(["2026-09-01 [WARNING] a", "2026-09-01 [WARNING] b"]);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<BackendLogsPanel />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "取得" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "ログ全体をコピー" }));
    });

    expect(writeText).toHaveBeenCalledWith("2026-09-01 [WARNING] a\n2026-09-01 [WARNING] b");
    expect(await screen.findByRole("button", { name: "コピーしました" })).toBeInTheDocument();
  });

  it("取得失敗時はエラーメッセージを表示する", async () => {
    vi.mocked(getRecentLogs).mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "取得" }));
    });

    expect(screen.getByText("取得失敗: boom")).toBeInTheDocument();
  });
});
