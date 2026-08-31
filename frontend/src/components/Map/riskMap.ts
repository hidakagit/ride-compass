// キキクル（気象庁 危険度分布：土砂・大雨・浸水）と線状降水帯予測マップ（sjfcstmap）の
// タイル・時刻取得クライアント（改善計画T410、T387「無償範囲で追加できるJMAデータの調査」の
// 続き）。
//
// どちらも他の動的気象レイヤー（降水・風等）と異なり、**未来方向の複数フレームを持たない**
// ——気象庁側で実況と短時間予測を統合済みの「現在の危険度」単一値のみを配信する
// （実機確認2026-08-30: targetTimes.jsonの全エントリでvalidtime===basetime）。フレーム列は
// 常に「現在」を表す最大1件のみ返す。**他の動的レイヤーと違い共有タイムライン・
// frameIndexForTimeには乗せない**——フレームのvalidtimeは実際の「今」から最大10分ほど
// 遅れるのが常態で、frameIndexForTimeの1秒の許容誤差には収まらない。
//
// **改善計画T432でキキクル3種と線状降水帯予測マップは扱いが分岐した**（当初T410は両者を
// 「現在の防災リスク」として一括りにしていたが、データソースの系統（risk vs rasrf）と
// 予報の性質が異なると判明したため訂正）:
// - キキクル3種（土砂・大雨・浸水）: 「防災」カテゴリとしてWarningBadgeと同様の常時
//   マウント（チップ無し・時刻スライダーとも無関係）へ変更した。以前は「12時間後の雷が
//   常時マップに警告されているのは嫌」という実機フィードバックを受け「スライダーが
//   『現在』位置にある間だけ表示」（isAtNow判定）にしていたが、チップ・スライダーの
//   どちらとも接続しない独立表示になったことで当時の懸念は構造的に発生しなくなり、
//   isAtNowゲーティング自体を撤回した（frontend/src/hooks/useDynamicWeatherLayers.ts参照）。
// - 線状降水帯予測マップ: データソースが実はrisk系統ではなくrasrf系統（降水短時間予報と
//   同じ）と判明したため「降水」チップの傘下（4つ目のソース）へ再分類した。「今後3時間
//   以内におそれ」という予報の性質に合わせ、共有タイムラインが現在〜3時間先の範囲内の
//   ときだけ表示する（isWithinFutureWindow、dynamicWeather.ts参照）——キキクルと異なり
//   共有タイムラインと連動し続ける点に注意。
//
// **洪水キキクル（flood）**: 改善計画T416で実装（当初T410は`.pbf`形式のため本基盤の
// 対応外として見送っていたが、dynamicWeather.tsへvectorTile kindを追加し対応した）。
// 実機確認（Browserペインで`https://www.jma.go.jp/bosai/risk/`の実際の通信・
// `risk.properties.xml`の`vectorTileLayerStyles`定義を観測）の結果:
// - URLパターンは他3種と完全に同型（`.../risk/{basetime}/{member}/{validtime}/surf/
//   flood/{z}/{x}/{y}`）で、拡張子だけ`.pbf`（他3種は`.png`）。`targetTimes.json`も
//   共通（elements配列に`"flood"`が含まれる）で、追加のfetchは不要。
// - タイル内のsource-layer名は`flood`（`vectorTileLayerStyles`のプロパティキーが
//   Leaflet.VectorGrid.Protobufの仕様上そのままsource-layer名になる）。
// - フィーチャーは河川をなぞるLINE形状で、プロパティ`level`（1〜4の危険度レベル、
//   本ファイルの`RISK_LEVEL_COLORS`と同じ配色）・`type`（"nation"=国管理河川等の
//   区分、当面未使用）を持つ。`level`が無い（=平常時）フィーチャーはJMA公式サイトでは
//   薄い水色の基準線として常時描画されるが、本アプリでは「危険情報のみ」を見せる方針
//   （他3種のラスタタイルも平常時は透明で何も見えない）に揃えるため、`level>=1`の
//   フィーチャーだけを表示する（MapView.tsx: DYNAMIC_WEATHER_RENDERERS.floodRiskの
//   `minValueToShow`フィルタ参照）。
// - 同じtargetTimes.jsonのelementsには`flood_mesh`・`designated_river(_nation)`・
//   `inland_flood`（内水氾濫、`level`1〜2でtexture塗り）・`flood_riskline`も存在する
//   関連製品だが、本タスク（洪水キキクルのみ）のスコープ外として未実装のまま残す。

import { fetchJson } from "@/lib/fetchJson";
import { JMA_TILE_BASE_URL, parseValidtime } from "@/components/Map/jmaNowcastFrames";
import type { DynamicWeatherFrame, DynamicWeatherRenderPayload } from "@/components/Map/dynamicWeather";

const RISK_TARGET_TIMES_URL = `${JMA_TILE_BASE_URL}/jmatile/data/risk/targetTimes.json`;
// 線状降水帯予測マップ(sjfcstmap)は降水短時間予報(rasrf)と同じtargetTimes.jsonに
// elements違いの別行として混在する（改善計画T407実装メモ参照）。
const RASRF_TARGET_TIMES_URL = `${JMA_TILE_BASE_URL}/jmatile/data/rasrf/targetTimes.json`;

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

async function fetchTargetTimes(url: string, label: string): Promise<RawRiskTargetTime[]> {
  const data = await fetchJson<unknown>(url, { timeoutMs: 15000, category: "api:jma-nowcast-times", errorLabel: label });
  if (!Array.isArray(data)) throw new Error(`${label}の形式が想定と異なりません`);
  return data as RawRiskTargetTime[];
}

/** rawの中から指定elementIdを含む最新の1件を返す（無ければnull）。全エントリが
 * validtime===basetimeの単一時点データのため、basetime降順の先頭が「現在」にあたる。 */
function latestEntry(raw: readonly RawRiskTargetTime[], elementId: string): RawRiskTargetTime | null {
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
  /** 大雨キキクル（タイル要素id="rain_mesh"、properties.xmlのimageType定義に準拠）。 */
  heavyRain: DynamicWeatherFrame<RiskFrameRef>[];
  /** 浸水キキクル。 */
  inundation: DynamicWeatherFrame<RiskFrameRef>[];
  /** 洪水キキクル（改善計画T416、タイル要素id="flood"、他3種と異なりvectorTile）。 */
  flood: DynamicWeatherFrame<RiskFrameRef>[];
}

/** キキクル4種（土砂・大雨・浸水・洪水）の「現在」フレームをまとめて取得する（1回のfetchで
 * targetTimes.json自体は4種共通、要素ごとに最新エントリを個別に選ぶ）。 */
export async function fetchCurrentRiskFrames(): Promise<CurrentRiskFrames> {
  const raw = await fetchTargetTimes(RISK_TARGET_TIMES_URL, "危険度分布（キキクル）の時刻一覧");
  return {
    land: toFrames(latestEntry(raw, "land")),
    heavyRain: toFrames(latestEntry(raw, "rain_mesh")),
    inundation: toFrames(latestEntry(raw, "inund")),
    flood: toFrames(latestEntry(raw, "flood")),
  };
}

/** 線状降水帯予測マップの「現在」フレームを取得する。 */
export async function fetchLinearRainbandFrames(): Promise<DynamicWeatherFrame<RiskFrameRef>[]> {
  const raw = await fetchTargetTimes(RASRF_TARGET_TIMES_URL, "線状降水帯予測マップの時刻一覧");
  return toFrames(latestEntry(raw, "sjfcstmap"));
}

function tileUrlTemplate(
  group: "risk" | "rasrf",
  elementId: string,
  ref: RiskFrameRef,
  // 洪水キキクル（flood）だけ配信元がMapbox Vector Tile（.pbf）のため拡張子が異なる
  // （改善計画T416）。他はすべてラスタタイル（.png）。
  extension: "png" | "pbf" = "png"
): string {
  return `${JMA_TILE_BASE_URL}/jmatile/data/${group}/${ref.basetime}/${ref.member}/${ref.validtime}/surf/${elementId}/{z}/{x}/{y}.${extension}`;
}

export function landRenderPayload(ref: RiskFrameRef): DynamicWeatherRenderPayload {
  return { kind: "rasterTile", tileUrlTemplate: tileUrlTemplate("risk", "land", ref) };
}

export function heavyRainRenderPayload(ref: RiskFrameRef): DynamicWeatherRenderPayload {
  return { kind: "rasterTile", tileUrlTemplate: tileUrlTemplate("risk", "rain_mesh", ref) };
}

export function inundationRenderPayload(ref: RiskFrameRef): DynamicWeatherRenderPayload {
  return { kind: "rasterTile", tileUrlTemplate: tileUrlTemplate("risk", "inund", ref) };
}

/** 洪水キキクル（改善計画T416）。他3種と異なりvectorTile——source-layer名・色分けは
 * MapView.tsx: DYNAMIC_WEATHER_RENDERERS.floodRiskが持つ（本ファイル冒頭コメント参照）。 */
export function floodRenderPayload(ref: RiskFrameRef): DynamicWeatherRenderPayload {
  return { kind: "vectorTile", tileUrlTemplate: tileUrlTemplate("risk", "flood", ref, "pbf") };
}

export function linearRainbandRenderPayload(ref: RiskFrameRef): DynamicWeatherRenderPayload {
  return { kind: "rasterTile", tileUrlTemplate: tileUrlTemplate("rasrf", "sjfcstmap", ref) };
}

// キキクル各層共通の5段階色（白/黄/赤/紫/黒、気象庁公式の危険度分布配色）。凡例HTML
// （legend_jp_normal_*.svg）が公式カラーコードを公開していないため、実機で確認した
// グラデーション近似値（precipitationNowcast.tsのPRECIPITATION_COLOR_STOPSと同じ扱い、
// 実際のタイル画像の色と厳密には一致しない）。危険度が上がるほど白→黄→赤→紫→黒と変化する。
export const RISK_LEVEL_COLORS: readonly { key: string; label: string; color: string }[] = [
  { key: "level0", label: "平常（危険度なし）", color: "#ffffff" },
  { key: "level1", label: "注意（黄）", color: "#f2e700" },
  { key: "level2", label: "警戒（赤）", color: "#ff2800" },
  { key: "level3", label: "危険（紫）", color: "#aa00aa" },
  { key: "level4", label: "災害切迫（黒）", color: "#0c000c" },
];
