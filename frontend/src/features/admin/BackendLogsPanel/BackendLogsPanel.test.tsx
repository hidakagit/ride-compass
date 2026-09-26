/**
 * `BackendLogsPanel.tsx`——backendの直近ログを、押したときだけ絞り込み付きで取り、重さで色を分けて並べ、
 * まとめてコピーできること。
 *
 * ここで見ないもの:
 * - 絞り込みを問い合わせの項目へ組み立てること → `app/admin/adminApi.test.ts`
 * - クリップボードへの書き込みと失敗の文言 → `hooks/useCopyToClipboard.ts`
 * - 行の色そのもの → `components/ui/LogLine`（ここでは差し替えて、どの重さで描かせたかだけを見る）
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getRecentLogs: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => api);
vi.mock("@/components/ui/LogLine/LogLine", () => ({
  LogLine: ({ tone, children, ...rest }: { tone: string; children: React.ReactNode }) => (
    <div data-testid="log-line" data-tone={tone} {...rest}>
      {children}
    </div>
  ),
}));

import BackendLogsPanel from "./BackendLogsPanel";

beforeEach(() => {
  api.getRecentLogs.mockReset();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("BackendLogsPanel", () => {
  it("開いただけでは取りに行かない", () => {
    render(<BackendLogsPanel />);
    expect(api.getRecentLogs).not.toHaveBeenCalled();
  });

  it("既定はWARNING以上・200件・絞り込みなしで取る", async () => {
    api.getRecentLogs.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));

    expect(api.getRecentLogs).toHaveBeenCalledWith({ contains: undefined, min_level: "WARNING", limit: 200 });
  });

  it("部分一致は前後の空白を落とし、すべてのレベルを選ぶとレベルで絞らない", async () => {
    api.getRecentLogs.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.type(screen.getByPlaceholderText(/絞り込み/), "  jma-tile  ");
    await user.selectOptions(screen.getByRole("combobox", { name: "最小レベル" }), "すべてのレベル");
    await user.click(screen.getByRole("button", { name: "取得" }));

    expect(api.getRecentLogs).toHaveBeenCalledWith(
      expect.objectContaining({ contains: "jma-tile", min_level: undefined }),
    );
  });

  it("空白だけの部分一致は、絞り込みなしとして送る", async () => {
    api.getRecentLogs.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.type(screen.getByPlaceholderText(/絞り込み/), "   ");
    await user.click(screen.getByRole("button", { name: "取得" }));

    expect(api.getRecentLogs).toHaveBeenCalledWith(expect.objectContaining({ contains: undefined }));
  });

  it("選んだレベル以上で取る", async () => {
    api.getRecentLogs.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.selectOptions(screen.getByRole("combobox", { name: "最小レベル" }), "ERROR以上");
    await user.click(screen.getByRole("button", { name: "取得" }));
    expect(api.getRecentLogs).toHaveBeenCalledWith(expect.objectContaining({ min_level: "ERROR" }));
  });

  it.each([["0"], [""], ["-5"]])("件数が正の数でない（%j）ときは件数で絞らない", async (typed) => {
    api.getRecentLogs.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    const limit = screen.getByRole("spinbutton", { name: "件数" });
    await user.clear(limit);
    if (typed) await user.type(limit, typed);
    await user.click(screen.getByRole("button", { name: "取得" }));

    expect(api.getRecentLogs).toHaveBeenCalledWith(expect.objectContaining({ limit: undefined }));
  });

  it("取得中はボタンを押せず、終わると戻る", async () => {
    const pending = deferred<string[]>();
    api.getRecentLogs.mockReturnValue(pending.promise);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));
    expect(screen.getByRole("button", { name: "取得中…" })).toBeDisabled();

    pending.resolve([]);
    expect(await screen.findByRole("button", { name: "取得" })).toBeEnabled();
  });

  it("行ごとに、行の中の[LEVEL]から重さを決める（ERROR・CRITICALはエラー、WARNINGは警告、それ以外は通常）", async () => {
    api.getRecentLogs.mockResolvedValue([
      "2026-09-24 [ERROR] a",
      "2026-09-24 [CRITICAL] b",
      "2026-09-24 [WARNING] c",
      "2026-09-24 [INFO] d",
      "レベルの無い行",
    ]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));

    const rows = await screen.findAllByTestId("log-line");
    expect(rows.map((row) => [row.textContent, row.dataset.tone, row.dataset.level ?? null])).toEqual([
      ["2026-09-24 [ERROR] a", "error", "ERROR"],
      ["2026-09-24 [CRITICAL] b", "error", "CRITICAL"],
      ["2026-09-24 [WARNING] c", "warning", "WARNING"],
      ["2026-09-24 [INFO] d", "normal", "INFO"],
      ["レベルの無い行", "normal", null],
    ]);
  });

  it("該当が0件なら、そう言う", async () => {
    api.getRecentLogs.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));

    expect(await screen.findByText("該当するログはありません。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ログ全体をコピー" })).not.toBeInTheDocument();
  });

  it("取得に失敗したら理由を出し、0件の案内は出さない。取り直して成功すれば理由は消える", async () => {
    api.getRecentLogs.mockRejectedValueOnce(new Error("backendへの接続に失敗しました"));
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));
    expect(await screen.findByText("取得失敗: backendへの接続に失敗しました")).toBeInTheDocument();
    expect(screen.queryByText("該当するログはありません。")).not.toBeInTheDocument();

    api.getRecentLogs.mockResolvedValueOnce(["[INFO] ok"]);
    await user.click(screen.getByRole("button", { name: "取得" }));
    expect(await screen.findByText("[INFO] ok")).toBeInTheDocument();
    expect(screen.queryByText(/取得失敗/)).not.toBeInTheDocument();
  });

  it("Error以外で失敗しても、その値を理由として出す", async () => {
    api.getRecentLogs.mockRejectedValue("timeout");
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));
    expect(await screen.findByText("取得失敗: timeout")).toBeInTheDocument();
  });

  it("表示中の全行を改行でつないでコピーし、コピーしたことをボタンの名前で示す", async () => {
    api.getRecentLogs.mockResolvedValue(["[INFO] 1行目", "[ERROR] 2行目"]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));
    await user.click(await screen.findByRole("button", { name: "ログ全体をコピー" }));

    await expect(navigator.clipboard.readText()).resolves.toBe("[INFO] 1行目\n[ERROR] 2行目");
    expect(await screen.findByRole("button", { name: "ログ全体をコピーしました" })).toBeInTheDocument();
  });

  it("コピーに失敗したら、取得の失敗とは別の行で理由を出す", async () => {
    api.getRecentLogs.mockResolvedValue(["[INFO] 1行目"]);
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));
    await user.click(await screen.findByRole("button", { name: "ログ全体をコピー" }));

    await waitFor(() => expect(screen.getByText(/denied/)).toBeInTheDocument());
    expect(screen.queryByText(/取得失敗/)).not.toBeInTheDocument();
  });
});
