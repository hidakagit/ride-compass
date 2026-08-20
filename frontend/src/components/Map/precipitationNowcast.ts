// 気象庁 降水ナウキャストのタイル・時刻一覧クライアント（改善計画T170/T171）。
//
// 実況（targetTimes_N1、basetime=validtime、5分毎更新）と60分先までの予測
// （targetTimes_N2、basetimeは最新実行時刻で固定・validtimeが5分刻みで先へ進む）を
// 1つの時系列へ束ね、「対象時刻に最も近いフレーム」を選ぶ・タイルURLを組み立てる、
// という2つの操作だけを提供する（このファイル自体はDOM/MapLibreを知らない純粋な
// データ層。実際のフェッチ・地図への反映はpage.tsx/MapView.tsxが行う）。
//
// タイルURLの構造はbosai系（気象庁の非公式API、公式サポート無し。政府標準利用規約
// 準拠・出典明記で利用可）の実際の通信を確認して得た（2026-08-20、Playwrightで
// https://www.jma.go.jp/bosai/nowc/ のネットワークリクエストを観測）。CORS設定が
// 無いためcanvas経由のピクセル読み取りはできないが、MapLibreのラスタタイルとして
// 表示するだけなら問題なく読み込める（同じくPlaywrightで実機確認済み）。

export interface NowcastFrame {
  basetime: string;
  validtime: string;
  /** true: 予測フレーム（targetTimes_N2由来、validtime > basetime）。false: 実況（N1由来） */
  isForecast: boolean;
}

const TARGET_TIMES_N1_URL = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json";
const TARGET_TIMES_N2_URL = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N2.json";

interface RawTargetTime {
  basetime: string;
  validtime: string;
}

async function fetchTargetTimes(url: string): Promise<RawTargetTime[]> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`降水ナウキャストの時刻一覧取得に失敗しました[${response.status}]`);
  }
  const data: unknown = await response.json();
  if (!Array.isArray(data)) throw new Error("降水ナウキャストの時刻一覧の形式が想定と異なります");
  return data as RawTargetTime[];
}

/** 実況・予測を合わせた時系列を、validtime昇順（過去→未来）で返す。片方の取得だけ
 * 失敗しても、もう片方が使えるなら部分的な時系列を返す（両方失敗したときだけ例外）。 */
export async function fetchNowcastFrames(): Promise<NowcastFrame[]> {
  const results = await Promise.allSettled([fetchTargetTimes(TARGET_TIMES_N1_URL), fetchTargetTimes(TARGET_TIMES_N2_URL)]);
  const [n1, n2] = results;
  if (n1.status === "rejected" && n2.status === "rejected") {
    throw n1.reason;
  }
  const frames: NowcastFrame[] = [
    ...(n1.status === "fulfilled" ? n1.value.map((t) => ({ ...t, isForecast: false })) : []),
    ...(n2.status === "fulfilled" ? n2.value.map((t) => ({ ...t, isForecast: true })) : []),
  ];
  frames.sort((a, b) => a.validtime.localeCompare(b.validtime));
  return frames;
}

/** 実況の最新フレーム（＝「現在」に最も近い実況値）のindex。無ければ末尾（最新フレーム）。
 * スライダーの初期位置に使う。 */
export function latestObservedFrameIndex(frames: readonly NowcastFrame[]): number {
  for (let i = frames.length - 1; i >= 0; i--) {
    if (!frames[i].isForecast) return i;
  }
  return Math.max(0, frames.length - 1);
}

/** "YYYYMMDDHHmmss"（UTC）形式のvalidtime → 表示用のJST時刻文字列（HH:mm）。 */
export function formatNowcastFrameTime(validtime: string): string {
  const y = validtime.slice(0, 4);
  const mo = validtime.slice(4, 6);
  const d = validtime.slice(6, 8);
  const h = validtime.slice(8, 10);
  const mi = validtime.slice(10, 12);
  const s = validtime.slice(12, 14);
  const date = new Date(`${y}-${mo}-${d}T${h}:${mi}:${s}Z`);
  return date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" });
}

/** 降水ナウキャストのラスタタイルURLテンプレート（{z}/{x}/{y}はMapLibreが実際の値へ
 * 展開するプレースホルダ、置換せずそのまま埋め込む）。 */
export function nowcastTileUrlTemplate(frame: NowcastFrame): string {
  return `https://www.jma.go.jp/bosai/jmatile/data/nowc/${frame.basetime}/none/${frame.validtime}/surf/hrpns/{z}/{x}/{y}.png`;
}
