// 地図タイル（MapLibreのvectorソース、路面・POI・事故）を取りに行くオリジン。
//
// `NEXT_PUBLIC_TILE_BASE_URL`が設定されていればそのオリジン（backendへ直接。フロントの
// ホスティング経由の往復を省く）、未設定ならフロント自身のオリジン（next.config.tsの
// rewritesでbackendへプロキシ）を使う。直接配信にする場合、API呼び出し（apiBaseUrl.ts）と
// 同じオリジンにタイルが載るため、backend側のnginxがHTTP/2以上（多重化）で応答できることが
// 前提——HTTP/1.1のままだとブラウザのオリジン単位の同時接続数上限（6本程度）を
// タイル要求が埋め、API呼び出しが詰まる（docs/architecture.md「同時接続数上限との競合」）。
//
// ベクタタイルはMapLibreがWeb Worker内でfetchするため相対パスでは解決できず、常に絶対URLを
// 返す必要がある。`window`はクライアント側でのみ存在するため、モジュール読み込み時の定数
// ではなく呼び出し時に評価する関数として提供する（SSR時にwindowを参照しない）。
export function tileBaseUrl(): string {
  return resolveTileBaseUrl(
    process.env.NEXT_PUBLIC_TILE_BASE_URL,
    typeof window !== "undefined" ? window.location.origin : null,
  );
}

/**
 * 上記の判断そのもの。`process.env`と`window`を引数で受け、どちらにも触らない。
 *
 * 判断をこちら側へ出すのは、`process.env`がテストファイルをまたいで共有される
 * （vitestの`pool: "vmThreads"`）ため——環境変数を立てて検証すると、並行実行中の別ファイルが
 * 同じ変数を読んで期待値が変わる（docs/testing.md参照）。`tileBaseUrl`側には分岐を残さない。
 */
export function resolveTileBaseUrl(configured: string | undefined, origin: string | null): string {
  if (configured) {
    return configured.replace(/\/+$/, "");
  }
  return origin ?? "";
}
