// @vitest-environment node
/**
 * `app/api/version/route.ts`——フロントのサーバーが今どのコミットで動いているかを返す口。入口はNext.jsが呼ぶ`GET`、
 * 確かめるのは応答の本文。デプロイの反映を、手元のコミットと見比べて確かめるために読まれる。
 *
 * ここで見ないもの:
 * - 応答をビルド時に固めない指定（`dynamic`）→ Next.jsの規約の宣言で、振る舞いはフレームワークが持つ
 * - この口を読んで画面に出すこと → `features/admin/SystemStatusPanel/SystemStatusPanel.test.tsx`・
 *   `components/HeaderMenu/HeaderMenu.test.tsx`
 *
 * コミットの環境変数はこの口だけが読むので、`vi.stubEnv`で立てて入口を呼ぶ（.claude/rules/testing.md パターン7）。
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FrontendVersion } from "@/services/versionApi";

import { GET } from "./route";

async function body() {
  return (await (await GET()).json()) as FrontendVersion & { status: string };
}

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
});
