/** 取得に失敗した出所（警告に限らず、画面の前提になるデータも含む）。常設ヘッダーの「未取得」の印に並ぶ。 */
export interface FetchFailure {
  id: string;
  label: string;
  /** 失敗の文言（429の案内・`[通信エラー]`等）。文言を持たない取得では無い。 */
  detail?: string;
  /** 取れていない間に何が起きているか（利用者が何を当てにできないか）。 */
  effect: string;
  /** 取り直す操作。自動で取り直す出所では無い。 */
  onRetry?: () => void;
}
