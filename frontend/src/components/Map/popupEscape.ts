// 地図ポップアップのHTML文字列へ、OSMタグ由来の値を埋め込むためのエスケープ。
//
// ポップアップに出る値は`osm_raw_ways`/`osm_raw_pois`のタグ由来＝**第三者が編集できる
// データ**で、対訳表に載らない値は生のまま文字列へ入る。組み立てた文字列は
// `Popup.setHTML()`へ渡り、そこでMapLibreの`DOM.sanitize()`が走る。
//
// そのサニタイザには**バイパスが報告されている**（XSS Sanitizer Bypass in DOM.sanitize()
// via Live NamedNodeMap Removal Skip、CVSS 10。修正版はsemver majorのv6系で、Next.jsの
// バンドラがWorkerのスクリプトURLを解決できず地図が描画されないため上げられない
// ——docs/architecture.md「フロントエンド実装上の注意」）。
//
// ライブラリのサニタイザ1枚に依存するのをやめ、埋め込む前にこちらでエスケープする。
// バージョンを上げなくても到達経路が消える。

/** HTMLの文字列リテラルへ安全に埋め込めるようエスケープする。 */
export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * 対訳表を引き、無ければ生値をエスケープして返す。
 *
 * 対訳表に載る値は固定の文言なのでそのまま使える。**エスケープが要るのは
 * `?? 生値`のフォールバック側だけ**で、ここを1関数に集約して3箇所が同じものを使う。
 */
export function labelOrEscapedRaw(labels: Record<string, string>, value: string): string {
  return labels[value] ?? escapeHtml(value);
}
