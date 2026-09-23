// キキクル（気象庁 危険度分布：土砂・大雨・浸水）と線状降水帯予測マップ（sjfcstmap）の
// タイル・時刻取得クライアント。
//
// どちらも他の動的気象レイヤー（降水・風等）と異なり、**未来方向の複数フレームを持たない**
// ——気象庁側で実況と短時間予測を統合済みの「現在の危険度」単一値のみを配信する
// （targetTimes.jsonの全エントリでvalidtime===basetime）。フレーム列は
// 常に「現在」を表す最大1件のみ返す。**他の動的レイヤーと違い共有タイムライン・
// frameIndexForTimeには乗せない**——フレームのvalidtimeは実際の「今」から最大10分ほど
// 遅れるのが常態で、frameIndexForTimeの1秒の許容誤差には収まらない。
//
// キキクルと線状降水帯予測マップは扱いが分岐する（詳細は
// docs/modules/frontend/dynamic-weather-layers.md「キキクル・線状降水帯予測マップ
// （特殊系）」節参照）:
// - キキクル: 「災害」チップ配下の名前付きソースとして出す。配信が「現在の危険度」の
//   単一値のみのため、共有タイムラインとは連動しない。
// - 線状降水帯予測マップ: データソースがrisk系統ではなくrasrf系統（降水短時間予報と
//   同じ）のため「降水」チップの傘下に分類する。「今後3時間
//   以内におそれ」という予報の性質に合わせ、共有タイムラインが現在〜3時間先の範囲内の
//   ときだけ表示する（isWithinFutureWindow、dynamicWeather.ts参照）——キキクルと異なり
//   共有タイムラインと連動し続ける点に注意。
//
// **洪水キキクル（flood）**: 他と異なりvectorTile（.pbf）形式で配信される。
// - URLパターンは他3種と完全に同型（`.../risk/{basetime}/{member}/{validtime}/surf/
//   flood/{z}/{x}/{y}`）で、拡張子だけ`.pbf`（他3種は`.png`）。`targetTimes.json`も
//   共通（elements配列に`"flood"`が含まれる）で、追加のfetchは不要。
// - タイル内のsource-layer名は`flood`（配信元のタイルがこの名前で焼かれている）。
// - フィーチャーは河川をなぞるLINE形状で、プロパティ`level`（1〜4の危険度レベル、
//   本ファイルの`RISK_LEVEL_COLORS`と同じ配色）・`type`（"nation"=国管理河川等の
//   区分、当面未使用）を持つ。`level`が無い（=平常時）フィーチャーはJMA公式サイトでは
//   薄い水色の基準線として常時描画されるが、本アプリでは「危険情報のみ」を見せる方針
//   （他3種のラスタタイルも平常時は透明で何も見えない）に揃えるため、`level>=1`の
//   フィーチャーだけを表示する（`features/map/scene/groups/weather.ts`の洪水の要素の
//   `filter`）。
// - 同じtargetTimes.jsonのelementsには`flood_mesh`・`designated_river(_nation)`・
//   `inland_flood`（内水氾濫、`level`1〜2でtexture塗り）・`flood_riskline`も存在する
//   関連製品だが、洪水キキクルのみのスコープ外として未実装のまま残す。

import weatherScales from "@/types/generated/weather-scales.json";
import {
  jmaDelivery,
  fetchJmaTargetTimes,
  jmaTilePayload,
  parseValidtime,
  type JmaElementKey,
} from "@/components/Map/jmaNowcastFrames";
import type { DynamicWeatherFrame, DynamicWeatherRenderPayload } from "@/components/Map/dynamicWeather";

// 線状降水帯予測マップ(sjfcstmap)は降水短時間予報(rasrf)と同じtargetTimes.jsonに
// elements違いの別行として混在する（precipitationNowcast.tsも同じファイルを読むが、
// 見る行が違うため、それぞれが自分の要素の宣言から時刻一覧を引く）。

interface RawRiskTargetTime {
  basetime: string;
  validtime: string;
  member: string;
  elements: string[];
}

/** タイルURLを組み立てるのに必要な最小限の参照情報。frames配列でのindex探索が不要な
 * （常に高々1件のため）ぶん、他の動的レイヤーのref（indexや{source,index}）と異なり
 * これ自体がそのままpayload組み立てに使える。 */
export interface RiskFrameRef {
  basetime: string;
  validtime: string;
  member: string;
}

/** rawの中から、その要素の配信要素idを含む最新の1件を返す（無ければnull）。全エントリが
 * validtime===basetimeの単一時点データのため、basetime降順の先頭が「現在」にあたる。 */
function latestEntry(raw: readonly RawRiskTargetTime[], key: JmaElementKey): RawRiskTargetTime | null {
  const elementId = jmaDelivery(key).id;
  const entries = raw.filter((e) => e.elements.includes(elementId));
  if (entries.length === 0) return null;
  return [...entries].sort((a, b) => b.basetime.localeCompare(a.basetime))[0];
}

function toFrames(entry: RawRiskTargetTime | null): DynamicWeatherFrame<RiskFrameRef>[] {
  if (!entry) return [];
  return [{ time: parseValidtime(entry.validtime), ref: entry }];
}

export interface CurrentRiskFrames {
  /** 土砂キキクル。 */
  land: DynamicWeatherFrame<RiskFrameRef>[];
  /** 大雨キキクル。 */
  heavyRain: DynamicWeatherFrame<RiskFrameRef>[];
  /** 浸水キキクル。 */
  inundation: DynamicWeatherFrame<RiskFrameRef>[];
  /** 洪水キキクル（他3種と異なりvectorTile）。 */
  flood: DynamicWeatherFrame<RiskFrameRef>[];
}

async function currentFrames(key: JmaElementKey, label: string): Promise<DynamicWeatherFrame<RiskFrameRef>[]> {
  const raw = await fetchJmaTargetTimes<RawRiskTargetTime>(jmaDelivery(key), label);
  return toFrames(latestEntry(raw, key));
}

/** キキクル4種（土砂・大雨・浸水・洪水）の「現在」フレームをまとめて取得する。要素ごとに時刻一覧を
 * 引くが、同じファイルに載る要素どうしは同時に取りに行くため往復は1回に畳まれる。 */
export async function fetchCurrentRiskFrames(): Promise<CurrentRiskFrames> {
  const label = "危険度分布（キキクル）";
  const [land, heavyRain, inundation, flood] = await Promise.all([
    currentFrames("disaster/landslide", label),
    currentFrames("disaster/heavyRain", label),
    currentFrames("disaster/inundation", label),
    currentFrames("disaster/flood", label),
  ]);
  return { land, heavyRain, inundation, flood };
}

/** 線状降水帯予測マップの「現在」フレームを取得する。 */
export async function fetchLinearRainbandFrames(): Promise<DynamicWeatherFrame<RiskFrameRef>[]> {
  return currentFrames("precipitationNowcast/linearRainband", "線状降水帯予測マップ");
}

export function landRenderPayload(ref: RiskFrameRef): DynamicWeatherRenderPayload {
  return jmaTilePayload("disaster/landslide", ref);
}

export function heavyRainRenderPayload(ref: RiskFrameRef): DynamicWeatherRenderPayload {
  return jmaTilePayload("disaster/heavyRain", ref);
}

export function inundationRenderPayload(ref: RiskFrameRef): DynamicWeatherRenderPayload {
  return jmaTilePayload("disaster/inundation", ref);
}

/** 洪水キキクル。他3種と異なりvectorTile——source-layer名・色分けは描き方の宣言
 * （`features/map/scene/groups/weather.ts`）が持つ。 */
export function floodRenderPayload(ref: RiskFrameRef): DynamicWeatherRenderPayload {
  return jmaTilePayload("disaster/flood", ref);
}

export function linearRainbandRenderPayload(ref: RiskFrameRef): DynamicWeatherRenderPayload {
  return jmaTilePayload("precipitationNowcast/linearRainband", ref);
}

// キキクル各層共通の5段階色（白/黄/赤/紫/黒、気象庁公式の危険度分布配色）。凡例HTML
// （legend_jp_normal_*.svg）が公式カラーコードを公開していないため、実機で確認した
// グラデーション近似値（precipitationNowcast.tsのPRECIPITATION_COLOR_STOPSと同じ扱い、
// 実際のタイル画像の色と厳密には一致しない）。危険度が上がるほど白→黄→赤→紫→黒と変化する。
export const RISK_LEVEL_COLORS: readonly { key: string; label: string; color: string }[] = weatherScales.risk_levels;
