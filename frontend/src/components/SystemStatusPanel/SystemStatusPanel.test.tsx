import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { getDebugStats, type DebugStats } from "@/services/debugStatsApi";
import { getFrontendVersion, type FrontendVersion } from "@/services/versionApi";
import SystemStatusPanel from "./SystemStatusPanel";

vi.mock("@/services/debugStatsApi");
vi.mock("@/services/versionApi");

const mockedGetDebugStats = vi.mocked(getDebugStats);
const mockedGetFrontendVersion = vi.mocked(getFrontendVersion);

const BACKEND_STATS: DebugStats = {
  commit: "abc1234",
  started_at: "2026-08-16T10:00:00+00:00",
  engine: "road_graph",
  debug_mode: false,
  external: {
    "weather:open-meteo": {
      calls: 10,
      errors: 1,
      cache_hits: 8,
      cache_misses: 2,
      total_ms: 500,
      max_ms: 200,
      avg_ms: 50,
      cache_hit_rate: 0.8,
      error_types: { http_429: 1 },
      last_error_type: "http_429",
      last_error_at: "2026-08-16T10:05:00+00:00",
      last_success_at: "2026-08-16T10:06:00+00:00",
      retried_calls: 1,
      retry_attempts_total: 2,
      stale_fallback_used: 0,
    },
  },
  rate_limit_rejections: { "routes:generate": 2 },
};

const FRONTEND_VERSION: FrontendVersion = { commit: "def5678", started_at: "2026-08-16T09:00:00+00:00" };

describe("SystemStatusPanel", () => {
  it("open:falseのときは何も描画しない", () => {
    mockedGetDebugStats.mockReturnValue(new Promise(() => {}));
    mockedGetFrontendVersion.mockReturnValue(new Promise(() => {}));
    const { container } = render(<SystemStatusPanel open={false} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("open:trueでフロント/バックのcommit・起動日時・外部呼出サマリ・429拒否を表示する", async () => {
    mockedGetDebugStats.mockResolvedValue(BACKEND_STATS);
    mockedGetFrontendVersion.mockResolvedValue(FRONTEND_VERSION);

    render(<SystemStatusPanel open onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText("abc1234")).toBeInTheDocument());
    expect(screen.getByText("def5678")).toBeInTheDocument();
    expect(screen.getByText("weather:open-meteo")).toBeInTheDocument();
    expect(screen.getByText(/429拒否: routes:generate 2件/)).toBeInTheDocument();
  });

  it("失敗の主な理由（最終失敗の種類・時刻・内訳）を表示する", async () => {
    mockedGetDebugStats.mockResolvedValue(BACKEND_STATS);
    mockedGetFrontendVersion.mockResolvedValue(FRONTEND_VERSION);

    render(<SystemStatusPanel open onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText(/http_429/)).toBeInTheDocument());
    const errorCell = screen.getByText("1", { selector: "td" });
    expect(errorCell).toHaveAttribute("title", expect.stringContaining("http_429:1"));
    expect(errorCell.getAttribute("title")).toContain("再試行あり 1件(延べ2回)");
  });

  it("取得失敗時はエラーメッセージを表示する", async () => {
    mockedGetDebugStats.mockRejectedValue(new Error("boom"));
    mockedGetFrontendVersion.mockResolvedValue(FRONTEND_VERSION);

    render(<SystemStatusPanel open onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText("取得失敗: boom")).toBeInTheDocument());
  });

  // 改善計画T471: 以前はloading解除がgetFrontendVersion()側の.finally()にしか紐付いて
  // おらず、getDebugStats()（バックエンド）がまだ取得中でもgetFrontendVersion()
  // （フロント自身、実質即時）が先に解決すると「更新中…」表示が消えていた。両方の完了を
  // 待ってから解除されることを確認する。
  it("frontendの取得が先に完了しても、backendが完了するまで「更新中…」表示を維持する", async () => {
    mockedGetFrontendVersion.mockResolvedValue(FRONTEND_VERSION);
    let resolveBackend: (value: DebugStats) => void = () => {};
    mockedGetDebugStats.mockReturnValue(
      new Promise((resolve) => {
        resolveBackend = resolve;
      }),
    );

    render(<SystemStatusPanel open onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText("def5678")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "更新中…" })).toBeInTheDocument();

    resolveBackend(BACKEND_STATS);

    await waitFor(() => expect(screen.getByRole("button", { name: "更新" })).toBeInTheDocument());
  });

  it("閉じるボタンでonCloseが呼ばれる", async () => {
    mockedGetDebugStats.mockResolvedValue(BACKEND_STATS);
    mockedGetFrontendVersion.mockResolvedValue(FRONTEND_VERSION);
    const onClose = vi.fn();
    render(<SystemStatusPanel open onClose={onClose} />);

    await waitFor(() => expect(screen.getByText("abc1234")).toBeInTheDocument());
    screen.getByRole("button", { name: "システム状況を閉じる" }).click();
    expect(onClose).toHaveBeenCalledOnce();
  });
});
