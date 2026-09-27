import type { paths } from "@/types/generated/api";

type PathParams<P extends string> = P extends `${string}{${infer Name}}${infer Rest}` ? Name | PathParams<Rest> : never;

/**
 * backendが宣言したパス（OpenAPIの生成物`paths`のキー）の`{名前}`を`params`の値で埋めた、アプリ自身が呼ばないURLの
 * パス（地図ライブラリへ渡すタイル・スタイル）。値はそのまま埋める（区切りの`/`を含めてよい）。渡さなかった名前は
 * `{名前}`のまま残る——タイルの`{z}/{x}/{y}`は地図ライブラリが埋める。アプリ自身が呼ぶ口は`lib/apiClient.ts`で呼ぶ。
 */
export function apiPath<P extends keyof paths>(
  path: P,
  params: Partial<Record<PathParams<P>, string | number>> = {},
): string {
  const values: Partial<Record<string, string | number>> = params;
  return path.replace(/\{([^}]+)\}/g, (whole, name: string) => {
    const value = values[name];
    return value === undefined ? whole : String(value);
  });
}
