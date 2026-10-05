/**
 * `BackendLogsPanel.tsx`——backendの直近ログを、押したときだけ絞り込み付きで取り、重さで色を分けて並べ、
 * まとめてコピーできること。
 *
 * ここで見ないもの:
 * - クリップボードへの書き込みと失敗の文言 → `hooks/useCopyToClipboard.ts`
 * - 行の色そのもの → `components/ui/LogLine`（ここでは、重さごとに`LogLine`が描く見た目と同じかだけを見る）
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { heldReplies, inTurn, onSameOrigin } from "@/testing/backendServer";

import { LogLine } from "@/components/ui/LogLine/LogLine";
import BackendLogsPanel from "./BackendLogsPanel";

const LOGS = "/admin/api/debug/logs";
const serveLogs = (lines: string[]) => onSameOrigin("GET", LOGS, () => Response.json(lines));

/** 届いた問い合わせの項目を1行のログとして返し、画面が送った絞り込みを出た行から読む。 */
function echoQuery() {
  onSameOrigin("GET", LOGS, ({ query }) => Response.json([JSON.stringify(query)]));
  return async () => JSON.parse((await screen.findByText(/^\{.*\}$/)).textContent ?? "");
}

describe("BackendLogsPanel", () => {
  // ログの口へ応答を与えないので、取りに行けば応答の無い要求としてテストが落ちる（`vitest.setup.ts`）。
  it("開いただけでは取りに行かない", () => {
    render(<BackendLogsPanel />);
    expect(screen.getByRole("button", { name: "取得" })).toBeInTheDocument();
  });

  it("既定はWARNING以上・200件・絞り込みなしで取る", async () => {
    const sentQuery = echoQuery();
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));

    expect(await sentQuery()).toEqual({ min_level: "WARNING", limit: "200" });
  });

  it.each([
    ["すべてのレベル", { contains: "jma-tile", limit: "200" }],
    ["ERROR以上", { contains: "jma-tile", min_level: "ERROR", limit: "200" }],
  ])(
    "部分一致は前後の空白を落とし、選んだレベル（%s）以上で取る。すべてのレベルならレベルで絞らない",
    async (level, query) => {
      const sentQuery = echoQuery();
      const user = userEvent.setup();
      render(<BackendLogsPanel />);

      await user.type(screen.getByPlaceholderText(/絞り込み/), "  jma-tile  ");
      await user.selectOptions(screen.getByRole("combobox", { name: "最小レベル" }), level);
      await user.click(screen.getByRole("button", { name: "取得" }));

      expect(await sentQuery()).toEqual(query);
    },
  );

  it("件数が正の数でないときは件数で絞らない", async () => {
    const sentQuery = echoQuery();
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    const limit = screen.getByRole("spinbutton", { name: "件数" });
    await user.clear(limit);
    await user.type(limit, "0");
    await user.click(screen.getByRole("button", { name: "取得" }));

    expect(await sentQuery()).not.toHaveProperty("limit");
  });

  it("取得中はボタンを押せず、終わると戻る", async () => {
    const held = heldReplies();
    onSameOrigin("GET", LOGS, held.reply);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));
    expect(screen.getByRole("button", { name: "取得中…" })).toBeDisabled();

    await held.answer(0, Response.json([]));
    expect(await screen.findByRole("button", { name: "取得" })).toBeEnabled();
  });

  it("行ごとに、行の中の[LEVEL]から重さを決める（ERROR・CRITICALはエラー、WARNINGは警告、それ以外は通常）", async () => {
    serveLogs(["2026-09-24 [ERROR] a", "2026-09-24 [CRITICAL] b", "2026-09-24 [WARNING] c", "レベルの無い行"]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));

    const rows = Array.from((await screen.findByText("レベルの無い行")).parentElement!.children) as HTMLElement[];
    const looks = (["error", "warning", "normal"] as const).map(
      (tone) => [tone, render(<LogLine tone={tone} />).container.firstElementChild!.className] as const,
    );
    const toneOf = (row: HTMLElement) => looks.find(([, look]) => look === row.className)?.[0];
    expect(rows.map((row) => [row.textContent, toneOf(row), row.dataset.level ?? null])).toEqual([
      ["2026-09-24 [ERROR] a", "error", "ERROR"],
      ["2026-09-24 [CRITICAL] b", "error", "CRITICAL"],
      ["2026-09-24 [WARNING] c", "warning", "WARNING"],
      ["レベルの無い行", "normal", null],
    ]);
  });

  it("該当が0件なら、そう言う", async () => {
    serveLogs([]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));

    expect(await screen.findByText("該当するログはありません。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ログ全体をコピー" })).not.toBeInTheDocument();
  });

  it("取得に失敗したら理由を出し、取り直して成功すれば理由は消える", async () => {
    onSameOrigin(
      "GET",
      LOGS,
      inTurn(Response.json({ detail: "backendへの接続に失敗しました" }, { status: 502 }), Response.json(["[INFO] ok"])),
    );
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));
    expect(await screen.findByText("取得失敗: backendへの接続に失敗しました")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "取得" }));
    expect(await screen.findByText("[INFO] ok")).toBeInTheDocument();
    expect(screen.queryByText(/取得失敗/)).not.toBeInTheDocument();
  });

  it("表示中の全行を改行でつないでコピーし、コピーしたことをボタンの名前で示す", async () => {
    serveLogs(["[INFO] 1行目", "[ERROR] 2行目"]);
    const user = userEvent.setup();
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));
    await user.click(await screen.findByRole("button", { name: "ログ全体をコピー" }));

    await expect(navigator.clipboard.readText()).resolves.toBe("[INFO] 1行目\n[ERROR] 2行目");
    expect(await screen.findByRole("button", { name: "ログ全体をコピーしました" })).toBeInTheDocument();
  });

  it("コピーに失敗したら、取得の失敗とは別の行で理由を出す", async () => {
    serveLogs(["[INFO] 1行目"]);
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
    render(<BackendLogsPanel />);

    await user.click(screen.getByRole("button", { name: "取得" }));
    await user.click(await screen.findByRole("button", { name: "ログ全体をコピー" }));

    await waitFor(() => expect(screen.getByText(/denied/)).toBeInTheDocument());
    expect(screen.queryByText(/取得失敗/)).not.toBeInTheDocument();
  });
});
