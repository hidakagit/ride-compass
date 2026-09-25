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
