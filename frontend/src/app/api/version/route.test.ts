// @vitest-environment node
/**
 * `app/api/version/route.ts`——フロントのサーバーが今どのコミットで動いているかを返す口。入口はNext.jsが呼ぶ`GET`、
 * 確かめるのは応答の本文。デプロイの反映を、手元のコミットと見比べて確かめるために読まれる。直近の変更の件名は
 * GitHubのAPIから取るので、GitHubは網の層（msw）で差し替える。
 *
 * ここで見ないもの:
 * - 応答をビルド時に固めない指定（`dynamic`）→ Next.jsの規約の宣言で、振る舞いはフレームワークが持つ
 * - この口を読んで画面に出すこと → `features/admin/SystemStatusPanel/SystemStatusPanel.test.tsx`・
 *   `components/HeaderMenu/HeaderMenu.test.tsx`
 *
 * コミットの環境変数はこの口だけが読むので、`vi.stubEnv`で立てて入口を呼ぶ（docs/conventions/testing.md パターン7）。
 */
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FrontendVersion } from "@/services/versionApi";
import { backendServer } from "@/testing/backendServer";

import { GET } from "./route";

async function body() {
  return (await (await GET()).json()) as FrontendVersion & { status: string };
}

/** GitHubのコミットの一覧の口に`reply`で答え、届いた要求の`sha`を記録する。 */
function serveGitHubCommits(reply: () => Response) {
  const asked: (string | null)[] = [];
  backendServer.use(
    http.get("https://api.github.com/repos/owner/repo/commits", ({ request }) => {
      asked.push(new URL(request.url).searchParams.get("sha"));
      return reply();
    }),
  );
  return asked;
}

const githubCommit = (message: string, date: string) => ({ sha: "x", commit: { message, committer: { date } } });

describe("GET /api/version", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("デプロイされたコミットを返し、注入されていない環境（手元）ではnullを返す", async () => {
    vi.stubEnv("RENDER_GIT_COMMIT", "0123456789abcdef0123456789abcdef01234567");
    expect(await body()).toMatchObject({ status: "ok", commit: "0123456789abcdef0123456789abcdef01234567" });

    vi.stubEnv("RENDER_GIT_COMMIT", undefined);
    expect((await body()).commit).toBeNull();
  });

  it("起動の時刻は呼ぶたびに変わらず、プロセスが起きた時点（呼んだ時より前）を指す", async () => {
    const first = await body();
    await new Promise((resolve) => setTimeout(resolve, 5));
    const second = await body();

    expect(second.started_at).toBe(first.started_at);
    expect(new Date(first.started_at).toISOString()).toBe(first.started_at);
    expect(Date.parse(first.started_at)).toBeLessThan(Date.now());
  });

  describe("直近の変更", () => {
    it("版のコミットから新しい順に、件名（メッセージの1行目）とmasterへ入った時刻を返し、同じ版では問い合わせ直さない", async () => {
      vi.stubEnv("RENDER_GIT_COMMIT", "aaaa1111");
      vi.stubEnv("RENDER_GIT_REPO_SLUG", "owner/repo");
      const asked = serveGitHubCommits(() =>
        HttpResponse.json([
          githubCommit("tasks#2: 後の変更\n\n背景: …", "2026-10-08T21:58:00Z"),
          githubCommit("tasks#1: 前の変更", "2026-10-08T21:00:00Z"),
        ]),
      );

      expect((await body()).recent).toEqual([
        { subject: "tasks#2: 後の変更", committed_at: "2026-10-08T21:58:00Z" },
        { subject: "tasks#1: 前の変更", committed_at: "2026-10-08T21:00:00Z" },
      ]);
      await body();
      expect(asked).toEqual(["aaaa1111"]);
    });

    it("GitHubから取れなければ空を返し、同じ版では問い合わせ直さない（毎時の回数の上限を使い切らない）", async () => {
      vi.stubEnv("RENDER_GIT_COMMIT", "bbbb2222");
      vi.stubEnv("RENDER_GIT_REPO_SLUG", "owner/repo");
      const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
      const asked = serveGitHubCommits(() => HttpResponse.json({ message: "rate limit" }, { status: 403 }));

      const first = await body();
      await body();

      expect(first).toMatchObject({ commit: "bbbb2222", recent: [] });
      expect(asked).toEqual(["bbbb2222"]);
      expect(warn).toHaveBeenCalledTimes(1);
    });

    it("コミットが注入されていない環境（手元）では、問い合わせずに空を返す", async () => {
      vi.stubEnv("RENDER_GIT_COMMIT", undefined);
      vi.stubEnv("RENDER_GIT_REPO_SLUG", "owner/repo");

      expect((await body()).recent).toEqual([]);
    });
  });
});
