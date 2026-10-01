// backendを呼ぶ口（`services/*Api.ts`）のテストが、網（`fetch`）を差し替えるための代役。口は`lib/apiClient.ts`を経て
// `fetch`へ出るので、ここで応答を与え、口が送った要求（メソッド・パス・問い合わせ・本文）を記録する。
// 差し替えは`vi.stubGlobal`なので、使うテストは`afterEach`で`vi.unstubAllGlobals()`を呼ぶ。
import { vi } from "vitest";

export interface SentRequest {
  method: string;
  /** オリジンを除いたパス（backendのオリジンは環境変数で変わるため、テストは見ない）。 */
  path: string;
  query: Record<string, string>;
  /** JSONの本文。本文の無い要求は`undefined`。 */
  body: unknown;
}

/** 応答を返す。`Error`を返すと、網の失敗（応答が届かない）として投げる。 */
type Reply = (request: SentRequest) => Response | Error;

/** `fetch`を差し替え、送った要求を順に積む配列を返す。 */
export function stubBackend(reply: Reply): SentRequest[] {
  const sent: SentRequest[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      const url = new URL(request.url);
      const text = await request.text();
      const recorded: SentRequest = {
        method: request.method,
        path: url.pathname,
        query: Object.fromEntries(url.searchParams),
        body: text === "" ? undefined : JSON.parse(text),
      };
      sent.push(recorded);
      const outcome = reply(recorded);
      if (outcome instanceof Error) throw outcome;
      return outcome;
    }),
  );
  return sent;
}
