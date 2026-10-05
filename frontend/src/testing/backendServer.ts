// backendとの通信を網の層で差し替える足場（msw）。口（`services/*Api.ts`・`features/**/*Api.ts`）も、通信を包むフックも
// 本物を通し、`lib/apiClient.ts`が`fetch`へ出した要求にここで応える（docs/conventions/testing.md「確かめる高さ」）。
// serverの起動・テストごとの応答の片付け・停止は`vitest.setup.ts`が受け持ち、応答の無い要求はテストを落とす。
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { expect, vi } from "vitest";

import { API_BASE_URL } from "@/lib/apiBaseUrl";
import type { AxisCatalogResponse } from "@/types/route";

export const backendServer = setupServer();

export interface SentRequest {
  method: string;
  /** オリジンを除いたパス（backendのオリジンは環境変数で変わるため、テストは見ない）。 */
  path: string;
  query: Record<string, string>;
  /** JSONの本文。本文の無い要求は`undefined`。 */
  body: unknown;
}

type Method = "GET" | "POST" | "PUT" | "DELETE";

/** 応答を返す。網の失敗（応答が届かない）は`HttpResponse.error()`を返す。 */
type Reply = (request: SentRequest) => Response | Promise<Response>;

const HANDLER = { GET: http.get, POST: http.post, PUT: http.put, DELETE: http.delete } as const;

function answer(method: Method, url: string, reply: Reply): SentRequest[] {
  const sent: SentRequest[] = [];
  backendServer.use(
    HANDLER[method](url, async ({ request }) => {
      const requestUrl = new URL(request.url);
      const text = await request.text();
      const recorded: SentRequest = {
        method: request.method,
        path: requestUrl.pathname,
        query: Object.fromEntries(requestUrl.searchParams),
        body: text === "" ? undefined : JSON.parse(text),
      };
      sent.push(recorded);
      return reply(recorded);
    }),
  );
  return sent;
}

/**
 * backendの`path`（`/api/...`。`:name`でパスの一部を受ける）への`method`の要求に`reply`で応え、届いた要求を順に積む配列を返す。
 * 後から渡した応答が先に当たる。
 */
export function onBackend(method: Method, path: string, reply: Reply): SentRequest[] {
  return answer(method, `${API_BASE_URL}${path}`, reply);
}

/**
 * 同じオリジンの`path`（管理APIの口`/admin/api/...`・フロントのroute handler）への要求に応える。ほかは`onBackend`と同じ。
 * 口は相対パスで呼ぶので、相対パスを画面のオリジンへ解決するDOMの環境（既定のhappy-dom）のテストで使う。
 */
export function onSameOrigin(method: Method, path: string, reply: Reply): SentRequest[] {
  return answer(method, path, reply);
}

/** 軸カタログの取得に`response`を返す（多くの画面が描くと同時に取る）。 */
export function serveAxisCatalog(response: AxisCatalogResponse): void {
  onBackend("GET", "/api/axis-catalog", () => Response.json(response));
}

/** 届いた順に`responses`を返す（尽きたら最後のものを返し続ける）。 */
export function inTurn(...responses: Response[]): Reply {
  let next = 0;
  return () => responses[Math.min(next++, responses.length - 1)].clone();
}

/** まだ応えていない要求と、テストの終わりにそれを閉じる応答。`closeHeldReplies`が閉じる。 */
const unanswered = new Map<(response: Response) => void, () => Response>();

/**
 * 届いた要求に、テストが応えるまで応答を返さない。`reply`を`onBackend`等へ渡し、`answer(番目, 応答)`で、届いた順の
 * その番目に応える（届くまで待つ）。応えなかった要求は、テストの終わりに`closeWith`（既定は網の失敗）で閉じる。
 */
export function heldReplies(closeWith: () => Response = () => HttpResponse.error()) {
  const pending: ((response: Response) => void)[] = [];
  return {
    reply: () =>
      new Promise<Response>((settle) => {
        pending.push(settle);
        unanswered.set(settle, closeWith);
      }),
    answer: async (index: number, response: Response) => {
      // 間をおいて出る要求（ルート生成の2回目からの問い合わせは1.5秒あとに出る）も待てる長さにする。
      await vi.waitFor(() => expect(pending.length).toBeGreaterThan(index), { timeout: 5000 });
      unanswered.delete(pending[index]);
      pending[index](response);
    },
    arrived: () => pending.length,
  };
}

/**
 * 応えていない要求を、それぞれの閉じる応答で閉じる（`vitest.setup.ts`がテストの終わりに呼ぶ）。開いたまま残すと、serverを
 * 止めたときにmswが本物の網へ流す。
 */
export function closeHeldReplies(): void {
  for (const [settle, closeWith] of unanswered) settle(closeWith());
  unanswered.clear();
}
