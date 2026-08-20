// Open-Meteo経由のJMA MSM風データ（気象庁モデル由来、Open-Meteo配信、改善計画T178）の
// 時刻一覧・矢印レイヤーURLクライアント。precipitationNowcast.tsと同じく、DOM/MapLibreを
// 一切知らない純粋なデータ層のみを持つ（実際のフェッチ・地図への反映はpage.tsx/MapView.tsxが
// 行う）。
//
// データソース: `https://openmeteo-data-spatial.b-cdn.net/jma_msm/latest.json`
// （2026-08-20実機確認: 200・日本域BBOX・wind_u/v_component_10m含む・reference_timeは
// 3時間毎更新、valid_timesはそこから1時間刻みで約39時間先まで）。矢印の実際の描画は
// `@openmeteo/weather-map-layer`のom://プロトコル（vector source、`arrows=true`、
// source-layer名`wind-arrows`）に委ねる（MapView.tsx側）。

export interface WindFrame {
  /** ISO8601（UTC）、例: "2026-08-20T03:00Z" */
  validTime: string;
  /** jma_msm/latest.jsonのvalid_times配列中のindex（om://URLのtime_step=valid_times_{index}に使う） */
  index: number;
}

const JMA_MSM_LATEST_URL = "https://openmeteo-data-spatial.b-cdn.net/jma_msm/latest.json";
// om://プロトコルへ渡す実URLのベース（風のu成分を指定するとweather-map-layerが対になる
// v成分も内部で解決する、公式サンプルexamples/vector/wind-arrows.htmlと同じ指定）。
const WIND_OM_VARIABLE = "wind_u_component_10m";

interface JmaMsmLatestResponse {
  reference_time?: unknown;
  valid_times?: unknown;
}

/** jma_msm/latest.jsonからvalid_times一覧を取得する。取得失敗・想定と異なる形式は例外。 */
export async function fetchWindFrames(): Promise<WindFrame[]> {
  const response = await fetch(JMA_MSM_LATEST_URL);
  if (!response.ok) {
    throw new Error(`風データの時刻一覧取得に失敗しました[${response.status}]`);
  }
  const data = (await response.json()) as JmaMsmLatestResponse;
  if (!Array.isArray(data.valid_times) || data.valid_times.length === 0) {
    throw new Error("風データの時刻一覧の形式が想定と異なります");
  }
  return data.valid_times.map((validTime, index) => ({ validTime: String(validTime), index }));
}

/** 現在時刻に最も近いフレームのindex。reference_timeが3時間毎更新のため配列の先頭が
 * 必ずしも「今」に近いとは限らず、降水ナウキャスト（latestObservedFrameIndex）と違い
 * 単純な末尾/先頭ではなく実際の時刻差で探す。空配列なら0。 */
export function nearestFrameIndexToNow(frames: readonly WindFrame[], now: Date = new Date()): number {
  if (frames.length === 0) return 0;
  const nowMs = now.getTime();
  let bestIndex = 0;
  let bestDiffMs = Infinity;
  for (let i = 0; i < frames.length; i++) {
    const diffMs = Math.abs(new Date(frames[i].validTime).getTime() - nowMs);
    if (diffMs < bestDiffMs) {
      bestDiffMs = diffMs;
      bestIndex = i;
    }
  }
  return bestIndex;
}

/** 矢印（vector source）用のom://ソースURL。ラスタ色分けは対応方針上「任意」のため
 * 本タスクでは実装せず矢印のみとする（地図の視界を圧迫しない、設計原則12）。 */
export function windVectorSourceUrl(frame: WindFrame): string {
  return `om://${JMA_MSM_LATEST_URL}?time_step=valid_times_${frame.index}&variable=${WIND_OM_VARIABLE}&arrows=true`;
}

/** ISO8601（UTC）のvalidTime → 表示用のJST時刻文字列。降水ナウキャスト（±60分、日付を
 * またがない）と異なり風は約39時間先まで日付をまたぐため、"M/D HH:mm"で日付も含める。 */
export function formatWindFrameTime(validTime: string): string {
  const date = new Date(validTime);
  const datePart = date.toLocaleDateString("ja-JP", { month: "numeric", day: "numeric", timeZone: "Asia/Tokyo" });
  const timePart = date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" });
  return `${datePart} ${timePart}`;
}
