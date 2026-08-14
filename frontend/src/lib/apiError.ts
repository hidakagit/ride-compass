// FastAPIのエラーレスポンス`detail`は、HTTPExceptionからは文字列で返るが、
// リクエストバリデーション失敗時（422）はPydanticの`[{loc, msg, type, input}, ...]`という
// オブジェクト配列になる。呼び出し元がdetailを常に文字列として組み立てると、422時に
// `new Error(detail)`が配列を`String()`で強制変換して"[object Object],..."という
// 意味の無いメッセージになる（実機確認: distance_kmが範囲外等で発生しうる）。
export function formatErrorDetail(detail: unknown): string | undefined {
  if (detail == null) return undefined;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : null))
      .filter((msg): msg is string => msg !== null);
    if (messages.length > 0) return messages.join(" / ");
  }
  return JSON.stringify(detail);
}
