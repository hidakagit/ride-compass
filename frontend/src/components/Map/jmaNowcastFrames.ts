// 気象庁ナウキャスト系（bosai/jmatile/data/nowc/配下、降水T171・雷/竜巻T204）に共通する
// 時刻一覧の取得・整形（改善計画T204、雷ナウキャストという2つ目の消費者が現れたため
// precipitationNowcast.tsから汎用部分を切り出した）。JMAのタイムスタンプ形式
// （YYYYMMDDHHmmss）・「実況フレームは現在より前を切り捨てる」というトリミング方針は
// bosai/nowc APIファミリー全体の性質であり降水固有の判断ではないため、変更理由が同じもの
// として共通化する（設計原則6）。降水・雷それぞれ固有のURL構造（降水はN1実況/N2予測の
// 2ファイル、雷/竜巻はN3の1ファイルに実況・予測が同居）は呼び出し元に残す。

import { fetchJson } from "@/lib/fetchJson";

// JMA bosaiタイル系（時刻一覧JSON・ラスタタイルPNG）の共通ベースURL（改善計画T412）。
// 以前は各消費者（precipitationNowcast.ts/thunderNowcast.ts/riskMap.ts）が
// `https://www.jma.go.jp/bosai/...`へ直接fetchしており、利用者数に比例してJMAの非公式
// 内部APIへの負荷が線形に増える上、同一タイルの再取得もキャッシュされず毎回JMAへ
// 実問い合わせしていた。バックエンドのプロキシ＋キャッシュ
// （backend/app/infrastructure/jma_tile_client.py、`GET /api/jma-tile/{path}`）経由に
// 切り替え、同一オリジン（他のタイル系＝basemap/road-surface等と同じ理由、
// next.config.tsのrewritesコメント参照）で配信する。
export const JMA_TILE_BASE_URL = "/api/jma-tile/bosai";

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
 * 対象名（例:「降水ナウキャスト」「雷ナウキャスト」）。
 *
 * 改善計画T248の実機調査で判明した「fetch()自体の失敗（タイムアウト・通信エラー）が
 * どこにもログされない」という穴（他のAPIクライアントで繰り返し発生していたのと同じ
 * パターン）を踏まえ、共通のfetchJson（lib/fetchJson.ts、通信エラー・HTTPエラー・
 * 解析エラーを全てdebugLogへ記録する）経由にした。以前は素のfetch()でタイムアウトも
 * 指定していなかった。 */
export async function fetchJmaTargetTimes(url: string, label: string): Promise<RawJmaTargetTime[]> {
  const data = await fetchJson<unknown>(url, {
    timeoutMs: 15000,
    category: "api:jma-nowcast-times",
    errorLabel: `${label}の時刻一覧`,
  });
  if (!Array.isArray(data)) throw new Error(`${label}の時刻一覧の形式が想定と異なります`);
  return data as RawJmaTargetTime[];
}

/** 実況の最新フレーム（＝「現在」に最も近い実況値）のindex。実況フレームが1件も無ければ
 * 切り捨てるべき「過去」のフレーム自体が存在しないため、先頭(0)を返し全フレームを残す
 * （改善計画T425、ゼロベース網羅レビュー指摘: 以前は末尾[frames.length - 1]を返しており、
 * 実況0件時に最も未来の1フレームだけを残して残り全部を切り捨ててしまい、降水/雷/竜巻
 * ナウキャストが実質空になる逆転したフォールバックだった）。 */
function latestObservedFrameIndex(frames: readonly JmaNowcastFrame[]): number {
  for (let i = frames.length - 1; i >= 0; i--) {
    if (!frames[i].isForecast) return i;
  }
  return 0;
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
