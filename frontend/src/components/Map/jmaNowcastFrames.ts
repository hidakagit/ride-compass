// 気象庁ナウキャスト系（bosai/jmatile/data/nowc/配下、降水T171・雷/竜巻T204）に共通する
// 時刻一覧の取得・整形（改善計画T204、雷ナウキャストという2つ目の消費者が現れたため
// precipitationNowcast.tsから汎用部分を切り出した）。JMAのタイムスタンプ形式
// （YYYYMMDDHHmmss）・「実況フレームは現在より前を切り捨てる」というトリミング方針は
// bosai/nowc APIファミリー全体の性質であり降水固有の判断ではないため、変更理由が同じもの
// として共通化する（設計原則6）。降水・雷それぞれ固有のURL構造（降水はN1実況/N2予測の
// 2ファイル、雷/竜巻はN3の1ファイルに実況・予測が同居）は呼び出し元に残す。

export interface JmaNowcastFrame {
  basetime: string;
  validtime: string;
  /** true: 予測フレーム（validtime > basetime）。false: 実況（validtime === basetime）。 */
  isForecast: boolean;
}

export interface RawJmaTargetTime {
  basetime: string;
  validtime: string;
}

/** 気象庁の時刻一覧JSON（targetTimes_*.json）を取得する。labelはエラーメッセージに使う
 * 対象名（例:「降水ナウキャスト」「雷ナウキャスト」）。 */
export async function fetchJmaTargetTimes(url: string, label: string): Promise<RawJmaTargetTime[]> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${label}の時刻一覧取得に失敗しました[${response.status}]`);
  }
  const data: unknown = await response.json();
  if (!Array.isArray(data)) throw new Error(`${label}の時刻一覧の形式が想定と異なります`);
  return data as RawJmaTargetTime[];
}

/** 実況の最新フレーム（＝「現在」に最も近い実況値）のindex。無ければ末尾（最新フレーム）。 */
function latestObservedFrameIndex(frames: readonly JmaNowcastFrame[]): number {
  for (let i = frames.length - 1; i >= 0; i--) {
    if (!frames[i].isForecast) return i;
  }
  return Math.max(0, frames.length - 1);
}

/** 実況フレームは現在時刻より前（過去〜現在）ぶんを多く含む。サイクリング向けアプリの
 * 性質上過去を振り返る用途は無いため（実機フィードバック「過去の風、雨を気にすることは
 * アプリの性質上ない、デフォルト位置を左端に」）、「現在」より前のフレームをすべて
 * 切り捨て、スライダーの左端（index 0）が常に「現在」になるようにする。 */
export function trimToCurrentAndFuture<T extends JmaNowcastFrame>(frames: readonly T[]): T[] {
  if (frames.length === 0) return [];
  return frames.slice(latestObservedFrameIndex(frames));
}

/** "YYYYMMDDHHmmss"（UTC）形式のvalidtime → Date。 */
export function parseValidtime(validtime: string): Date {
  const y = validtime.slice(0, 4);
  const mo = validtime.slice(4, 6);
  const d = validtime.slice(6, 8);
  const h = validtime.slice(8, 10);
  const mi = validtime.slice(10, 12);
  const s = validtime.slice(12, 14);
  return new Date(`${y}-${mo}-${d}T${h}:${mi}:${s}Z`);
}
