// FastAPIのエラーレスポンス`detail`は、HTTPExceptionからは文字列で返るが、
// リクエストバリデーション失敗時（422）はPydanticの`[{loc, msg, type, input}, ...]`という
// オブジェクト配列になる。呼び出し元がdetailを常に文字列として組み立てると、422時に
// `new Error(detail)`が配列を`String()`で強制変換して"[object Object],..."という
// 意味の無いメッセージになる（distance_kmが範囲外等の入力検証エラーで発生しうる）。
export function formatErrorDetail(detail: unknown): string | undefined {
  if (detail == null) return undefined;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) =>
      item && typeof item === "object" && "msg" in item ? [String(item.msg)] : [],
    );
    if (messages.length > 0) return messages.join(" / ");
  }
  return JSON.stringify(detail);
}

/** 捕まえた例外を画面へ出す文言にする（`Error`以外が投げられても文字列にする）。 */
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
