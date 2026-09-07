/**
 * fetchをスタブするテストが共有するレスポンスのフェイク。
 *
 * `vi.stubGlobal("fetch", ...)`へ渡す値を作る。実装側（lib/fetchJson.ts）が読むのは
 * ok・status・json()・headersの4つだけのため、フェイクもその4つで足りる。
 */
export function makeResponse(
  overrides: Partial<{ ok: boolean; status: number; json: () => Promise<unknown>; headers: Headers }>,
) {
  return {
    ok: true,
    status: 200,
    json: async () => ({}),
    headers: new Headers(),
    ...overrides,
  };
}
