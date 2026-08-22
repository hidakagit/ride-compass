// 気象庁 雷ナウキャスト・竜巻発生確度ナウキャストのタイル・時刻一覧クライアント（改善計画T204）。
//
// precipitationNowcast.ts（T171）と同じbosai/jmatile/data/nowc/系だが、降水がN1（実況）/
// N2（予測）の2ファイルに分かれているのに対し、雷・竜巻はtargetTimes_N3.json 1本に
// 実況〜60分先の予測が同居する（実機確認2026-08-22: 古いbasetimeの行はvalidtime===basetimeの
// 実況のみ、最新basetimeの行だけvalidtime>basetimeの予測が10分刻みで複数並ぶ）。
// elements配列に雷（thns/thns_nd）・竜巻（trns/trns_nd）の両方が含まれるため、時刻一覧の
// 取得は1回で両方をカバーする（thunderFrames/tornadoFramesは同じ時刻一覧を共有する）。
//
// 雷・竜巻は「回避一択」の危険（T170〜T178節の設計判断参照）のため評価軸には組み込まず、
// rasterTile表現（気象庁が生成した画像をそのまま重ねる）のみを持つ警告表示として扱う。
// T171の実装メモが「プロダクトコード未確認のため別レイヤー・別調査として残す」としていた
// 宿題（雷）と、その調査過程で判明した竜巻発生確度ナウキャスト（同じN3・同じタイル構造）を
// あわせて実装する。

import type { DynamicWeatherFrame, DynamicWeatherRenderPayload } from "@/components/Map/dynamicWeather";
import { fetchJmaTargetTimes, parseValidtime, type JmaNowcastFrame } from "@/components/Map/jmaNowcastFrames";

export type ThunderNowcastFrame = JmaNowcastFrame;

const TARGET_TIMES_N3_URL = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N3.json";

/** 雷・竜巻共通の時刻一覧を取得する（1回のfetchで両方をカバー）。 */
export async function fetchThunderNowcastFrames(): Promise<ThunderNowcastFrame[]> {
  const raw = await fetchJmaTargetTimes(TARGET_TIMES_N3_URL, "雷ナウキャスト");
  const frames: ThunderNowcastFrame[] = raw.map((t) => ({ ...t, isForecast: t.validtime > t.basetime }));
  frames.sort((a, b) => a.validtime.localeCompare(b.validtime));
  return frames;
}

/** dynamicWeather.tsの共通フレーム列へ変換する（windFrames/windRenderPayloadと同型、
 * refはframes内のindex）。雷・竜巻のどちらの表示もこの同じフレーム列を共有する。 */
export function thunderFrames(frames: readonly ThunderNowcastFrame[]): DynamicWeatherFrame<number>[] {
  return frames.map((frame, index) => ({ time: parseValidtime(frame.validtime), ref: index }));
}

function tileUrlTemplate(frame: ThunderNowcastFrame, product: "thns" | "trns"): string {
  return `https://www.jma.go.jp/bosai/jmatile/data/nowc/${frame.basetime}/none/${frame.validtime}/surf/${product}/{z}/{x}/{y}.png`;
}

/** thunderFramesが返したref（frames内のindex）から、雷ナウキャストの描画ペイロードを
 * 組み立てる（rasterTile、気象庁配信の画像タイルをそのまま重ねる）。 */
export function thunderRenderPayload(frames: readonly ThunderNowcastFrame[], ref: number): DynamicWeatherRenderPayload | undefined {
  const frame = frames[ref];
  return frame ? { kind: "rasterTile", tileUrlTemplate: tileUrlTemplate(frame, "thns") } : undefined;
}

/** thunderFramesと同じフレーム列・同じrefで、竜巻発生確度ナウキャストの描画ペイロードを
 * 組み立てる（プロダクトコードのみthnsからtrnsへ差し替え）。 */
export function tornadoRenderPayload(frames: readonly ThunderNowcastFrame[], ref: number): DynamicWeatherRenderPayload | undefined {
  const frame = frames[ref];
  return frame ? { kind: "rasterTile", tileUrlTemplate: tileUrlTemplate(frame, "trns") } : undefined;
}

// 雷活動度1〜4の凡例（地図チップ）。気象庁の解説
// （https://www.jma.go.jp/jma/kishou/know/toppuu/thunder2-1.html・thunder3-1.html、
// 2026-08-22確認）に基づく要約: 活動度1=雷雲に発達する可能性（1時間以内に発雷のおそれ）、
// 活動度2〜4=既に積乱雲が発生し落雷の可能性がある状態（検知数が多いほど活動度が高い）。
// 色そのものは気象庁がタイル配色のカラーコードを公開していないため、同庁のナウキャスト系
// 地図で一般的な「弱い＝黄→強い＝紫」の配色慣習に沿った近似値であり、実際のタイル画像の
// 色と厳密には一致しない（precipitationNowcast.tsのPRECIPITATION_COLOR_STOPSと同じ扱い）。
export const THUNDER_ACTIVITY_LEVELS: readonly { key: string; label: string; color: string }[] = [
  { key: "level1", label: "活動度1: 雷雲発達の可能性（1時間以内に発雷のおそれ）", color: "#fde047" },
  { key: "level2", label: "活動度2: 雷雲発生、落雷の可能性", color: "#fb923c" },
  { key: "level3", label: "活動度3: 落雷が発生中", color: "#ef4444" },
  { key: "level4", label: "活動度4: 激しい雷（雹に注意）", color: "#9333ea" },
];

// 竜巻発生確度1・2の凡例。気象庁の解説
// （https://www.jma.go.jp/jma/kishou/know/toppuu/tornado3-3.html、2026-08-22確認）に基づく
// 要約: 発生確度1は見逃しを減らすよう広め・低い的中率（1〜7%）、発生確度2は気象庁の
// 「竜巻注意」情報につながる絞り込んだ予測（的中率7〜14%）。数字は「切迫度」ではなく
// 「可能性の程度」の違いを表す（気象庁の注記どおり）。色は雷と区別できる寒色系の近似値。
export const TORNADO_POTENTIAL_LEVELS: readonly { key: string; label: string; color: string }[] = [
  { key: "potential1", label: "発生確度1: 広く注意（見逃しを減らす、的中率1〜7%）", color: "#38bdf8" },
  { key: "potential2", label: "発生確度2: 重点警戒（気象庁「竜巻注意」相当、的中率7〜14%）", color: "#1d4ed8" },
];
