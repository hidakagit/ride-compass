/**
 * `SystemStatusPanel.tsx`——開いたときと「更新」のときだけ、フロントとbackendの版・外部サービスの
 * 呼び出しの集計・予報の同期の鮮度を取って出すこと。
 *
 * 日時の書式はOSの時間帯で変わるため、日時の文字列そのものは見ない（testing.md パターン10）。
 *
 * ここで見ないもの:
 * - 浮動パネルの開閉・移動 → `components/FloatingPanel`
 * - 叩く先 → `features/admin/adminApi.test.ts`
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DebugStats, FrontendVersion } from "@/features/admin/adminApi";

const api = vi.hoisted(() => ({ getDebugStats: vi.fn(), getFrontendVersion: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => ({
  getDebugStats: api.getDebugStats,
  getFrontendVersion: api.getFrontendVersion,
}));

import SystemStatusPanel from "./SystemStatusPanel";

type ExternalStats = DebugStats["external"][string];

function externalStats(overrides: Partial<ExternalStats> = {}): ExternalStats {
  return {
    calls: 0,
    errors: 0,
    cache_hits: 0,
    cache_misses: 0,
    total_ms: 0,
    max_ms: 0,
    avg_ms: 0,
    cache_hit_rate: null,
    error_types: {},
    last_error_type: null,
    last_error_at: null,
    last_success_at: null,
    retried_calls: 0,
    retry_attempts_total: 0,
    stale_fallback_used: 0,
    ...overrides,
  };
}

function debugStats(overrides: Partial<DebugStats> = {}): DebugStats {
  return {
    commit: null,
    started_at: "2026-09-24T00:00:00Z",
    debug_mode: false,
    external: {},
    rate_limit_rejections: {},
    msm: null,
    ...overrides,
  };
}

const frontendVersion: FrontendVersion = { commit: null, started_at: "2026-09-24T00:00:00Z" };

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => (resolve = res));
  return { promise, resolve };
}

beforeEach(() => {
  api.getDebugStats.mockReset();
  api.getFrontendVersion.mockReset();
});

function section(heading: string): HTMLElement {
  return screen.getByText(heading).parentElement!;
}

describe("SystemStatusPanel", () => {
  it("閉じている間は取りに行かない", () => {
    render(<SystemStatusPanel open={false} onClose={() => {}} />);
    expect(api.getDebugStats).not.toHaveBeenCalled();
    expect(api.getFrontendVersion).not.toHaveBeenCalled();
  });

  it("開くと両方を取り、どちらも届くまでは取得中と出す", async () => {
    api.getDebugStats.mockReturnValue(new Promise(() => {}));
    api.getFrontendVersion.mockReturnValue(new Promise(() => {}));
    render(<SystemStatusPanel open onClose={() => {}} />);

    expect(screen.getByText("取得中…")).toBeInTheDocument();
    await waitFor(() => expect(api.getDebugStats).toHaveBeenCalledTimes(1));
    expect(api.getFrontendVersion).toHaveBeenCalledTimes(1);
  });

  it("「更新」は、遅い方（backend）が届くまで押せないままにする", async () => {
    const backend = deferred<DebugStats>();
    api.getDebugStats.mockReturnValue(backend.promise);
    api.getFrontendVersion.mockResolvedValue(frontendVersion);
    render(<SystemStatusPanel open onClose={() => {}} />);

    expect(await screen.findByText("(ローカル)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更新中…" })).toBeDisabled();

    backend.resolve(debugStats());
    expect(await screen.findByRole("button", { name: "更新" })).toBeEnabled();
  });

  it("「更新」で取り直し、新しい値に置き換える", async () => {
    api.getDebugStats.mockResolvedValueOnce(debugStats({ commit: "aaa111" }));
    api.getFrontendVersion.mockResolvedValue(frontendVersion);
    const user = userEvent.setup();
    render(<SystemStatusPanel open onClose={() => {}} />);
    expect(await screen.findByText("aaa111")).toBeInTheDocument();

    api.getDebugStats.mockResolvedValueOnce(debugStats({ commit: "bbb222" }));
    await user.click(screen.getByRole("button", { name: "更新" }));

    expect(await screen.findByText("bbb222")).toBeInTheDocument();
    expect(screen.queryByText("aaa111")).not.toBeInTheDocument();
  });

  it("版はcommitを出し、無ければローカルと出す。backendはdebug_modeの状態も出す", async () => {
    api.getDebugStats.mockResolvedValue(debugStats({ commit: "backend-sha", debug_mode: true }));
    api.getFrontendVersion.mockResolvedValue({ ...frontendVersion, commit: null });
    render(<SystemStatusPanel open onClose={() => {}} />);

    const backend = await waitFor(() => section("バックエンド"));
    expect(within(backend).getByText("backend-sha")).toBeInTheDocument();
    expect(within(backend).getByText("debug_mode ON")).toBeInTheDocument();
    expect(within(section("フロントエンド")).getByText("(ローカル)")).toBeInTheDocument();
  });

  it("片方だけ失敗したら、その側にだけ理由を出し、もう片方は出す。取り直して成功すれば理由は消える", async () => {
    api.getDebugStats.mockRejectedValueOnce(new Error("システム状況の取得に失敗しました"));
    api.getFrontendVersion.mockResolvedValue({ ...frontendVersion, commit: "front-sha" });
    const user = userEvent.setup();
    render(<SystemStatusPanel open onClose={() => {}} />);

    expect(await screen.findByText("取得失敗: システム状況の取得に失敗しました")).toBeInTheDocument();
    expect(within(section("バックエンド")).getByText(/取得失敗/)).toBeInTheDocument();
    expect(within(section("フロントエンド")).getByText("front-sha")).toBeInTheDocument();
    expect(screen.queryByText("取得中…")).not.toBeInTheDocument();

    api.getDebugStats.mockResolvedValueOnce(debugStats());
    await user.click(await screen.findByRole("button", { name: "更新" }));
    await waitFor(() => expect(screen.queryByText(/取得失敗/)).not.toBeInTheDocument());
  });

  it.each([
    ["Error以外の値", "offline", "offline"],
    [
      "Error",
      new Error("フロントエンドのバージョンの取得に失敗しました"),
      "フロントエンドのバージョンの取得に失敗しました",
    ],
  ])("フロント側が%sで失敗したら、その理由をフロント側に出す", async (_kind, reason, shown) => {
    api.getDebugStats.mockResolvedValue(debugStats());
    api.getFrontendVersion.mockRejectedValue(reason);
    render(<SystemStatusPanel open onClose={() => {}} />);

    expect(await screen.findByText(`取得失敗: ${shown}`)).toBeInTheDocument();
    expect(within(section("フロントエンド")).getByText(`取得失敗: ${shown}`)).toBeInTheDocument();
  });

  it("backend側がError以外の値で失敗しても、その値を理由に出す", async () => {
    api.getDebugStats.mockRejectedValue("timeout");
    api.getFrontendVersion.mockResolvedValue(frontendVersion);
    render(<SystemStatusPanel open onClose={() => {}} />);

    expect(await screen.findByText("取得失敗: timeout")).toBeInTheDocument();
    expect(within(section("バックエンド")).getByText("取得失敗: timeout")).toBeInTheDocument();
  });

  it("予報の同期は、backendが鮮度を返したときだけ出し、滞っていれば警告する", async () => {
    api.getFrontendVersion.mockResolvedValue(frontendVersion);
    api.getDebugStats.mockResolvedValueOnce(debugStats({ msm: null }));
    const user = userEvent.setup();
    render(<SystemStatusPanel open onClose={() => {}} />);
    await screen.findByText("バックエンド");
    await waitFor(() => expect(screen.getByRole("button", { name: "更新" })).toBeEnabled());
    expect(screen.queryByText("予報（MSM）")).not.toBeInTheDocument();

    const msm = {
      last_run_at: "2026-09-24T00:00:00Z",
      data_end_at: "2026-09-26T00:00:00Z",
      run_age_hours: 3,
      remaining_hours: 45,
    };
    api.getDebugStats.mockResolvedValueOnce(debugStats({ msm: { ...msm, healthy: true } }));
    await user.click(screen.getByRole("button", { name: "更新" }));
    const healthy = (await screen.findByText("予報（MSM）")).parentElement!;
    expect(healthy).toHaveAttribute("data-healthy", "true");
    expect(healthy).toHaveTextContent("3時間前");
    expect(healthy).toHaveTextContent("予報の残り 45時間");
    expect(screen.queryByText(/配信が滞っています/)).not.toBeInTheDocument();

    api.getDebugStats.mockResolvedValueOnce(debugStats({ msm: { ...msm, healthy: false } }));
    await user.click(screen.getByRole("button", { name: "更新" }));
    expect(await screen.findByText(/配信が滞っています/)).toBeInTheDocument();
    expect(screen.getByText("予報（MSM）").parentElement).toHaveAttribute("data-healthy", "false");
  });

  it("外部サービスの集計は、呼び出しのあったカテゴリごとに1行で出し、無ければ表を出さない", async () => {
    api.getFrontendVersion.mockResolvedValue(frontendVersion);
    api.getDebugStats.mockResolvedValueOnce(debugStats({ external: {} }));
    const user = userEvent.setup();
    render(<SystemStatusPanel open onClose={() => {}} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "更新" })).toBeEnabled());
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    api.getDebugStats.mockResolvedValueOnce(
      debugStats({
        external: {
          "jma-tile": externalStats({ calls: 12, errors: 0, cache_hit_rate: 0.456, avg_ms: 30, max_ms: 120 }),
          msm: externalStats({ calls: 3, cache_hit_rate: null }),
        },
      }),
    );
    await user.click(screen.getByRole("button", { name: "更新" }));

    const rows = within(await screen.findByRole("table"))
      .getAllByRole("row")
      .slice(1);
    expect(rows).toHaveLength(2);
    const cells = rows.map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    );
    expect(cells[0]).toEqual(["jma-tile", "12", "0", "—", "46%", "30ms", "120ms"]);
    expect(cells[1][4]).toBe("—");
  });

  it("失敗のあったカテゴリの行はエラーとして目立たせ、失敗の内訳・再試行・古いキャッシュでの代用をエラー件数に添える", async () => {
    api.getFrontendVersion.mockResolvedValue(frontendVersion);
    api.getDebugStats.mockResolvedValue(
      debugStats({
        external: {
          failing: externalStats({
            calls: 10,
            errors: 3,
            error_types: { TimeoutError: 2, HTTP429: 1 },
            retried_calls: 2,
            retry_attempts_total: 5,
            stale_fallback_used: 1,
            last_error_type: "TimeoutError",
            last_error_at: "2026-09-24T01:00:00Z",
          }),
          healthy: externalStats({ calls: 5 }),
        },
      }),
    );
    render(<SystemStatusPanel open onClose={() => {}} />);

    const failing = (await screen.findByText("failing")).closest("tr")!;
    expect(failing).toHaveAttribute("data-level", "error");
    const [, , errorsCell, lastErrorCell] = within(failing).getAllByRole("cell");
    expect(errorsCell).toHaveAttribute(
      "title",
      "TimeoutError:2 / HTTP429:1 / 再試行あり 2件(延べ5回) / 古いキャッシュで代用 1件",
    );
    expect(lastErrorCell.textContent).toMatch(/^TimeoutError \(.+\)$/);

    const healthy = screen.getByText("healthy").closest("tr")!;
    expect(healthy).not.toHaveAttribute("data-level");
    expect(within(healthy).getAllByRole("cell")[2]).not.toHaveAttribute("title");
  });

  it("429で拒否した件数を、カテゴリごとに出す", async () => {
    api.getFrontendVersion.mockResolvedValue(frontendVersion);
    api.getDebugStats.mockResolvedValue(debugStats({ rate_limit_rejections: { "route-generate": 4, weather: 1 } }));
    render(<SystemStatusPanel open onClose={() => {}} />);

    expect(await screen.findByText("429拒否: route-generate 4件")).toBeInTheDocument();
    expect(screen.getByText("429拒否: weather 1件")).toBeInTheDocument();
  });
});
