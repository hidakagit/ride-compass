import type { paths } from "@/types/generated/api";

/** backendが宣言したAPIのパス（OpenAPIの生成物`paths`のキー）。 */
export type ApiPath = keyof paths;

type PathParams<P extends string> = P extends `${string}{${infer Name}}${infer Rest}` ? Name | PathParams<Rest> : never;

/** `apiPath`が`P`から作ったパス。手で書いた文字列はこの型にならない——backendがパスを変えると、呼び出し元が型検査で落ちる。 */
export type DeclaredApiPath<P extends ApiPath = ApiPath> = string & { readonly __declared: P };

/**
 * 宣言されたパスの`{名前}`を`params`の値で埋める。値はそのまま埋める（区切りの`/`を含めてよい。1区切りの値は
 * 呼び出し側がエンコードする）。渡さなかった名前は`{名前}`のまま残る——タイルの`{z}/{x}/{y}`は地図ライブラリが埋める。
 */
export function apiPath<P extends ApiPath>(
  path: P,
  params: Partial<Record<PathParams<P>, string | number>> = {},
): DeclaredApiPath<P> {
  const values: Partial<Record<string, string | number>> = params;
  return path.replace(/\{([^}]+)\}/g, (whole, name: string) => {
    const value = values[name];
    return value === undefined ? whole : String(value);
  }) as DeclaredApiPath<P>;
}

/** `P`のGETが宣言した問い合わせの項目（生成物`paths`から引く）。`P`がパスの合併なら、パスごとの項目の合併。 */
export type ApiQuery<P extends ApiPath> = P extends ApiPath
  ? paths[P] extends { get: { parameters: { query?: infer Q } } }
    ? NonNullable<Q>
    : never
  : never;

/**
 * `P`への問い合わせの項目を`?`から始まる文字列にする（付ける項目が無ければ空文字）。値がnull・undefined・空文字の項目は
 * 付けない。項目の名前は`P`の宣言が決める——手で書いた名前はbackendが名前を変えても黙って無視されるが、ここを通すと
 * 生成物の更新で呼び出し元が型検査で落ちる。
 */
export function apiQuery<P extends ApiPath>(path: P, query: ApiQuery<P>): string {
  const entries = Object.entries(query as Record<string, unknown>).flatMap(([key, value]) =>
    value == null || value === "" ? [] : [[key, String(value)]],
  );
  return entries.length > 0 ? `?${new URLSearchParams(entries)}` : "";
}
