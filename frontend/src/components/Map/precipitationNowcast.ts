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

/** 実況フレーム（targetTimes_N1）は現在時刻より前（過去〜現在）ぶんを多く含む
 * （実機確認: 2026-08-20時点でN1=37件・約3時間分）。サイクリング向けアプリの性質上
 * 過去の降水を振り返る用途は無い（実機フィードバック「過去の風、雨を気にすることは
 * アプリの性質上ない、デフォルト位置を左端に」）ため、「現在」より前のフレームを
 * すべて切り捨て、スライダーの左端（index 0）が常に「現在」になるようにする。
 * 以前は実況側を予測側と同じ件数まで切り詰めて「現在」をトラック中央に置く方式
 * （centerFramesAroundLatestObserved）だったが、過去を見る用途が無い以上、過去分自体を
 * 残す理由が無いため置き換えた。 */
export function trimToCurrentAndFuture(frames: readonly NowcastFrame[]): NowcastFrame[] {
  if (frames.length === 0) return [];
  return frames.slice(latestObservedFrameIndex(frames));
}

/** "YYYYMMDDHHmmss"（UTC）形式のvalidtime → Date。formatNowcastFrameTime・
 * nearestFrameIndexByTimeの両方から使う共通パース処理。 */
export function parseValidtime(validtime: string): Date {
  const y = validtime.slice(0, 4);
  const mo = validtime.slice(4, 6);
  const d = validtime.slice(6, 8);
  const h = validtime.slice(8, 10);
  const mi = validtime.slice(10, 12);
  const s = validtime.slice(12, 14);
  return new Date(`${y}-${mo}-${d}T${h}:${mi}:${s}Z`);
}

/** "YYYYMMDDHHmmss"（UTC）形式のvalidtime → 表示用のJST時刻文字列（HH:mm）。 */
export function formatNowcastFrameTime(validtime: string): string {
  return parseValidtime(validtime).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" });
}

/** 指定時刻に最も近いフレームのindex（windLayer.tsのnearestFrameIndexToNowと同型、
 * 「現在時刻」ではなく任意の対象時刻で探せる版）。下部バー2本の時刻連動（改善計画、
 * 実機フィードバック「同じ日時を示した状態で連動させ」）で、風スライダー側の対象時刻を
 * こちら側のフレーム列に写像するために使う。空配列なら0。 */
export function nearestFrameIndexByTime(frames: readonly NowcastFrame[], targetTime: Date): number {
  if (frames.length === 0) return 0;
  const targetMs = targetTime.getTime();
  let bestIndex = 0;
  let bestDiffMs = Infinity;
  for (let i = 0; i < frames.length; i++) {
    const diffMs = Math.abs(parseValidtime(frames[i].validtime).getTime() - targetMs);
    if (diffMs < bestDiffMs) {
      bestDiffMs = diffMs;
      bestIndex = i;
    }
  }
  return bestIndex;
}

// 降水強度の凡例（地図チップ、page.tsx、実機フィードバック「風と雨の凡例も欲しい」）。
// 階級の名称・境界値（mm/h）は気象庁公式の「雨の強さと降り方」の分類
// （https://www.jma.go.jp/jma/kishou/know/yougo_hp/amehyo.html、2026-08-20確認）と同じ
// （10mm/h未満は同ページに公式区分が無いため「弱い雨」とだけ表現）。一方で色そのものは
// 気象庁がタイル配色のカラーコードを公開していないため、同庁のナウキャスト・レーダー系
// 地図で一般的な「弱い＝青→強い＝紫」の配色慣習に沿った近似値であり、実際のタイル画像の
// 色と厳密には一致しない（凡例としての目安）。
export const PRECIPITATION_INTENSITY_LEVELS: readonly { key: string; label: string; color: string }[] = [
  { key: "light", label: "弱い雨（10mm/h未満）", color: "#7dd3fc" },
  { key: "somewhat-strong", label: "やや強い雨（10〜20mm/h）", color: "#3b82f6" },
  { key: "strong", label: "強い雨（20〜30mm/h）", color: "#eab308" },
  { key: "intense", label: "激しい雨（30〜50mm/h）", color: "#f97316" },
  { key: "very-intense", label: "非常に激しい雨（50〜80mm/h）", color: "#dc2626" },
  { key: "violent", label: "猛烈な雨（80mm/h以上）", color: "#9333ea" },
];

/** 降水ナウキャストのラスタタイルURLテンプレート（{z}/{x}/{y}はMapLibreが実際の値へ
 * 展開するプレースホルダ、置換せずそのまま埋め込む）。 */
export function nowcastTileUrlTemplate(frame: NowcastFrame): string {
  return `https://www.jma.go.jp/bosai/jmatile/data/nowc/${frame.basetime}/none/${frame.validtime}/surf/hrpns/{z}/{x}/{y}.png`;
}
