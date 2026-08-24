// 一次属性（生データ）のカタログと、二次軸との双方向導出（改善計画T163〜T168
// 「地図レイヤー階層の次数反転」）。
//
// backendのレジストリ（app/domain/registry_defaults.py）は、二次軸ごとに参照する一次属性
// （`inputs`、attr_idのリスト）を排他制約つきで宣言している（T137、domain/registry.py参照）。
// この属性単位の対応関係から、以下2方向の導出が同じ単一ソース（axis-catalog.json）だけで
// 機械的に得られる（片側import、設計原則2）。
//   - 2次→1次（地図）: 推定指標レイヤーをONにしたとき、材料になっている観測データレイヤーを
//     連動ONする（T167）・推定グループの展開UIに材料一覧を出す
//   - 1次→2次（評価側）: 研究タブの各軸の重み行の直下に、その軸が参照する材料一覧を出す
//     （T168）・区間インスペクタのラベル共通化
//
// 一次属性の正式名（label）はaxis-catalog.jsonのprimary_attributes[]（T163でbackendが
// 書き出し）が単一ソース。このファイルが独自に持つのは、UI固有の対応（地図チップの略名・
// 対応する表示レイヤーID）だけ（片側import）。

import type { MapLayerId } from "./mapLayers";
import axisCatalog from "@/types/generated/axis-catalog.json";

interface CatalogPrimaryAttribute {
  attr_id: string;
  label: string;
  shared: boolean;
}

interface CatalogAxisInputs {
  axis_id: string;
  inputs: string[];
}

export interface PrimaryAttribute {
  attrId: string;
  /** 正式名（サイドバー・研究タブで使う）。axis-catalog.json由来 */
  label: string;
  shared: boolean;
}

/** 一次属性の一覧（正式名付き）。axis-catalog.json: primary_attributes[]をそのまま反映する。 */
export const PRIMARY_ATTRIBUTES: readonly PrimaryAttribute[] = (
  axisCatalog.primary_attributes as CatalogPrimaryAttribute[]
).map((attr) => ({ attrId: attr.attr_id, label: attr.label, shared: attr.shared }));

/** attr_id→正式名の辞書（区間インスペクタ・研究タブが引く）。 */
export const PRIMARY_ATTRIBUTE_LABELS: Record<string, string> = Object.fromEntries(
  PRIMARY_ATTRIBUTES.map((attr) => [attr.attrId, attr.label]),
);

// 地図チップの略名（4文字以下、2026-08-19ユーザー承認の確定命名表）。正式名（上記）とは
// 別に、地図上は文字数に応じてチップ幅が伸びる制約（MapOverlayControls.module.css:
// .iconChip）があるため短縮する。全一次属性ぶんを持つ（レイヤーの有無に関わらず、T167の
// 材料一覧表示で薄字ラベルとして使うため）。
export const PRIMARY_ATTRIBUTE_CHIP_LABELS: Record<string, string> = {
  highway: "道路種別",
  lanes: "車線数",
  maxspeed: "制限速度",
  cycleway: "インフラ",
  surface: "路面",
  bicycle_access: "自転車",
  motor_vehicle_access: "車両可否",
  lit: "街灯",
  tunnel: "トンネル",
  designation: "指定路線",
  elevation: "標高",
  stop_poi: "停止要因",
  supply_poi: "補給休憩",
  accident_point: "事故地点",
  intersection: "交差点",
  geometry: "区間形状",
  oneway: "一方通行",
};

// 一次属性→表示レイヤーIDの対応（Partial: キーが無い＝表示レイヤー無し）。改善計画T163の
// 確定命名表どおり。highway/surfaceはT165で「道路情報」（road）から分割された論理2レイヤー
// （roadType/roadSurface、物理描画は1本の線レイヤーへ合成、mapLayers.ts参照）を指す。
export const PRIMARY_ATTRIBUTE_LAYER_IDS: Partial<Record<string, MapLayerId>> = {
  highway: "roadType",
  surface: "roadSurface",
  cycleway: "bicycleInfra",
  designation: "designation",
  elevation: "elevation",
  stop_poi: "stopPoi",
  accident_point: "accidents",
  supply_poi: "supplyPoi",
  // 改善計画: 地図上に描画可能な状態で保持している要素の洗い出しで判明した「観測配下に
  // レイヤーが無いまま」を解消（tunnelはタイルへの焼き込み自体はnight軸の材料として
  // 元々あったが、専用の色分けレイヤーは持っていなかった）。
  tunnel: "tunnel",
  // 改善計画T289: 一方通行はどの評価軸のinputsにも属さない（表示専用の一次属性）ため
  // axisMaterials経由の連動ON（T167）対象にはならないが、独立レイヤー自体は持つ。
  oneway: "oneway",
};

// 表示レイヤーを意図的に持たない一次属性（改善計画T163の確定命名表で「なし」と明示した4件、
// +評価軸から参照されないbicycle_access・区間の共通コンテキストgeometry）。tunnelは上記の
// 追加でこの一覧から外れた（litは引き続きレイヤー無し）。
// PRIMARY_ATTRIBUTE_LAYER_IDSにキーが無いことが「未対応（漏れ）」なのか「意図的にレイヤー
// 無し」なのかを区別できないため、後者をここへ明示する（ドリフト検知テスト参照）。
export const PRIMARY_ATTRIBUTES_WITHOUT_LAYER: ReadonlySet<string> = new Set([
  "lanes",
  "maxspeed",
  "lit",
  "intersection",
  "bicycle_access",
  "motor_vehicle_access",
  "geometry",
]);

const AXES_WITH_INPUTS = axisCatalog.axes as CatalogAxisInputs[];

/** 2次軸→材料の1次属性id一覧（axis-catalog.json: axes[].inputsをそのまま返す）。
 * 未知の軸idはT145bのRAMP_AXES同様、空配列を返す（存在しない軸を指すバグを早期に
 * 気づけるよう、呼び出し側でlength===0を「軸が無い」の判定に使わない設計は避けること）。 */
export function axisMaterials(axisId: string): readonly string[] {
  return AXES_WITH_INPUTS.find((axis) => axis.axis_id === axisId)?.inputs ?? [];
}

/** 1次属性→それを参照する2次軸id一覧（逆導出）。レジストリの排他制約（T137）により
 * shared=falseの属性は通常0または1件、shared=true（geometry等）は複数件になりうる。 */
export function attrConsumers(attrId: string): readonly string[] {
  return AXES_WITH_INPUTS.filter((axis) => axis.inputs.includes(attrId)).map((axis) => axis.axis_id);
}

/** 2次軸の材料のうち、表示レイヤーを持つものだけをMapLayerIdの重複無し配列で返す
 * （T167: 推定指標レイヤーON時の観測データレイヤー連動ON用）。複数の一次属性が同じ
 * 表示レイヤーへ集約される場合（1レイヤーが複数属性を表す場合）は1件にまとめる。 */
export function axisMaterialLayerIds(axisId: string): readonly MapLayerId[] {
  const layerIds = axisMaterials(axisId)
    .map((attrId) => PRIMARY_ATTRIBUTE_LAYER_IDS[attrId])
    .filter((layerId): layerId is MapLayerId => layerId !== undefined);
  return Array.from(new Set(layerIds));
}
