/**
 * `SystemStatusPanel.tsx`——開いたときと「更新」のときだけ、フロントとbackendの版・外部サービスの
 * 呼び出しの集計・予報の同期の鮮度を取って出すこと。
 *
 * 日時の書式はOSの時間帯で変わるため、日時の文字列そのものは見ない（testing.md パターン10）。
 *
 * ここで見ないもの:
 * - 浮動パネルの開閉・移動 → `components/FloatingPanel`
 * - 叩く先 → `app/admin/adminApi.test.ts`
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { FrontendVersion, getDebugStats } from "@/features/admin/adminApi";
import { heldReplies, inTurn, onBackend, onSameOrigin } from "@/testing/backendServer";

import SystemStatusPanel from "./SystemStatusPanel";

type DebugStats = Awaited<ReturnType<typeof getDebugStats>>;
type ExternalStats = DebugStats["external"][string];

function externalStats(overrides: Partial<ExternalStats> = {}): ExternalStats {
  return {
    calls: 0,
    errors: 0,
    max_ms: 0,
    avg_ms: 0,
    cache_hit_rate: null,
    error_types: {},
    last_error: null,
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

const STATS = "/api/debug/stats";
const VERSION = "/api/version";

/** backendの稼働状況の取得に、届いた順に`stats`を返す（尽きたら最後のものを返し続ける）。 */
const serveStats = (...stats: DebugStats[]) =>
  onBackend("GET", STATS, inTurn(...stats.map((value) => Response.json(value))));
const serveVersion = (version: FrontendVersion) => onSameOrigin("GET", VERSION, () => Response.json(version));
const failure = (detail: string) => Response.json({ detail }, { status: 500 });

function section(heading: string): HTMLElement {
  return screen.getByText(heading).parentElement!;
}

describe("SystemStatusPanel", () => {
  it("閉じている間は取りに行かない", () => {
    render(<SystemStatusPanel open={false} onClose={() => {}} />);
    expect(screen.queryByText("取得中…")).not.toBeInTheDocument();
  });

  it("開くと両方を取り、どちらも届くまでは取得中と出す", () => {
    onBackend("GET", STATS, heldReplies().reply);
    onSameOrigin("GET", VERSION, heldReplies().reply);
    render(<SystemStatusPanel open onClose={() => {}} />);

    expect(screen.getByText("取得中…")).toBeInTheDocument();
  });

  it("「更新」は、遅い方（backend）が届くまで押せないままにする", async () => {
    const backend = heldReplies();
    onBackend("GET", STATS, backend.reply);
    serveVersion(frontendVersion);
    render(<SystemStatusPanel open onClose={() => {}} />);

    expect(await screen.findByText("(ローカル)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更新中…" })).toBeDisabled();

    await backend.answer(0, Response.json(debugStats()));
    expect(await screen.findByRole("button", { name: "更新" })).toBeEnabled();
  });

  it("「更新」で取り直し、新しい値に置き換える", async () => {
    serveStats(debugStats({ commit: "aaa111" }), debugStats({ commit: "bbb222" }));
    serveVersion(frontendVersion);
    const user = userEvent.setup();
    render(<SystemStatusPanel open onClose={() => {}} />);
    expect(await screen.findByText("aaa111")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "更新" }));

    expect(await screen.findByText("bbb222")).toBeInTheDocument();
    expect(screen.queryByText("aaa111")).not.toBeInTheDocument();
  });

  it("版はcommitを出し、無ければローカルと出す。backendはdebug_modeの状態も出す", async () => {
    serveStats(debugStats({ commit: "backend-sha", debug_mode: true }));
    serveVersion({ ...frontendVersion, commit: null });
    render(<SystemStatusPanel open onClose={() => {}} />);

    const backend = await waitFor(() => section("バックエンド"));
    expect(within(backend).getByText("backend-sha")).toBeInTheDocument();
    expect(within(backend).getByText("debug_mode ON")).toBeInTheDocument();
    expect(within(section("フロントエンド")).getByText("(ローカル)")).toBeInTheDocument();
  });

  it("片方だけ失敗したら、その側にだけ理由を出し、もう片方は出す。取り直して成功すれば理由は消える", async () => {
    onBackend("GET", STATS, inTurn(failure("システム状況の取得に失敗しました"), Response.json(debugStats())));
    serveVersion({ ...frontendVersion, commit: "front-sha" });
    const user = userEvent.setup();
    render(<SystemStatusPanel open onClose={() => {}} />);

    expect(await screen.findByText("取得失敗: システム状況の取得に失敗しました")).toBeInTheDocument();
    expect(within(section("バックエンド")).getByText(/取得失敗/)).toBeInTheDocument();
    expect(within(section("フロントエンド")).getByText("front-sha")).toBeInTheDocument();
    expect(screen.queryByText("取得中…")).not.toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "更新" }));
    await waitFor(() => expect(screen.queryByText(/取得失敗/)).not.toBeInTheDocument());
  });

  it("フロント側が失敗したら、その理由をフロント側に出す", async () => {
    serveStats(debugStats());
    onSameOrigin("GET", VERSION, () => failure("フロントエンドのバージョンの取得に失敗しました"));
    render(<SystemStatusPanel open onClose={() => {}} />);

    const shown = "取得失敗: フロントエンドのバージョンの取得に失敗しました";
    expect(await screen.findByText(shown)).toBeInTheDocument();
    expect(within(section("フロントエンド")).getByText(shown)).toBeInTheDocument();
  });

  it("予報の同期は、backendが鮮度を返したときだけ出し、滞っていれば警告する", async () => {
    const msm = {
      last_run_at: "2026-09-24T00:00:00Z",
      run_age_hours: 3,
      remaining_hours: 45,
    };
    serveVersion(frontendVersion);
    serveStats(
      debugStats({ msm: null }),
      debugStats({ msm: { ...msm, healthy: true } }),
      debugStats({ msm: { ...msm, healthy: false } }),
    );
    const user = userEvent.setup();
    render(<SystemStatusPanel open onClose={() => {}} />);
    await screen.findByText("バックエンド");
    await waitFor(() => expect(screen.getByRole("button", { name: "更新" })).toBeEnabled());
    expect(screen.queryByText("予報（MSM）")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "更新" }));
    const healthy = (await screen.findByText("予報（MSM）")).parentElement!;
    expect(healthy).toHaveAttribute("data-healthy", "true");
    expect(healthy).toHaveTextContent("3時間前");
    expect(healthy).toHaveTextContent("予報の残り 45時間");
    expect(screen.queryByText(/配信が滞っています/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "更新" }));
    expect(await screen.findByText(/配信が滞っています/)).toBeInTheDocument();
    expect(screen.getByText("予報（MSM）").parentElement).toHaveAttribute("data-healthy", "false");
  });

  it("外部サービスの集計は、呼び出しのあったカテゴリごとに1行で出し、無ければ表を出さない", async () => {
    serveVersion(frontendVersion);
    serveStats(
      debugStats({ external: {} }),
      debugStats({
        external: {
          "jma-tile": externalStats({ calls: 12, errors: 0, cache_hit_rate: 0.456, avg_ms: 30, max_ms: 120 }),
          msm: externalStats({ calls: 3, cache_hit_rate: null }),
        },
      }),
    );
    const user = userEvent.setup();
    render(<SystemStatusPanel open onClose={() => {}} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "更新" })).toBeEnabled());
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

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

  it("失敗のあったカテゴリの行はエラーとして目立たせ、失敗の内訳をエラー件数に添える", async () => {
    serveVersion(frontendVersion);
    serveStats(
      debugStats({
        external: {
          failing: externalStats({
            calls: 10,
            errors: 3,
            error_types: { TimeoutError: 2, HTTP429: 1 },
            last_error: { type: "TimeoutError", at: "2026-09-24T01:00:00Z" },
          }),
          healthy: externalStats({ calls: 5 }),
        },
      }),
    );
    render(<SystemStatusPanel open onClose={() => {}} />);

    const failing = (await screen.findByText("failing")).closest("tr")!;
    expect(failing).toHaveAttribute("data-level", "error");
    const [, , errorsCell, lastErrorCell] = within(failing).getAllByRole("cell");
    expect(Array.from(errorsCell.childNodes, (node) => node.textContent)).toEqual(["3", "TimeoutError:2", "HTTP429:1"]);
    expect(lastErrorCell.textContent).toMatch(/^TimeoutError \(.+\)$/);

    const healthy = screen.getByText("healthy").closest("tr")!;
    expect(healthy).not.toHaveAttribute("data-level");
  });

  it("429で拒否した件数を、カテゴリごとに出す", async () => {
    serveVersion(frontendVersion);
    serveStats(debugStats({ rate_limit_rejections: { "route-generate": 4, weather: 1 } }));
    render(<SystemStatusPanel open onClose={() => {}} />);

    expect(await screen.findByText("429拒否: route-generate 4件")).toBeInTheDocument();
    expect(screen.getByText("429拒否: weather 1件")).toBeInTheDocument();
  });
});
