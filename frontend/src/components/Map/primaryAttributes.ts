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
};

// 一次属性→表示レイヤーIDの対応（Partial: キーが無い＝表示レイヤー無し）。改善計画T163の
// 確定命名表どおり。highway/surfaceは現状「道路情報」レイヤー（road、1レイヤーに2属性が
// 同居）を指すが、T165で「道路の種類」「路面の種類」の論理2レイヤーへ分割される予定
// （分割後にこの2行を更新する）。
export const PRIMARY_ATTRIBUTE_LAYER_IDS: Partial<Record<string, MapLayerId>> = {
  highway: "road",
  surface: "road",
  cycleway: "bicycleInfra",
  designation: "designation",
  elevation: "elevation",
  stop_poi: "stopPoi",
  accident_point: "accidents",
  supply_poi: "supplyPoi",
};

// 表示レイヤーを意図的に持たない一次属性（改善計画T163の確定命名表で「なし」と明示した5件、
// +評価軸から参照されないbicycle_access・区間の共通コンテキストgeometry）。
// PRIMARY_ATTRIBUTE_LAYER_IDSにキーが無いことが「未対応（漏れ）」なのか「意図的にレイヤー
// 無し」なのかを区別できないため、後者をここへ明示する（ドリフト検知テスト参照）。
export const PRIMARY_ATTRIBUTES_WITHOUT_LAYER: ReadonlySet<string> = new Set([
  "lanes",
  "maxspeed",
  "lit",
  "tunnel",
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
 * （T167: 推定指標レイヤーON時の観測データレイヤー連動ON用）。highway/surfaceが
 * どちらも"road"を指す等、複数属性が同じレイヤーに集約される場合は1件にまとめる。 */
export function axisMaterialLayerIds(axisId: string): readonly MapLayerId[] {
  const layerIds = axisMaterials(axisId)
    .map((attrId) => PRIMARY_ATTRIBUTE_LAYER_IDS[attrId])
    .filter((layerId): layerId is MapLayerId => layerId !== undefined);
  return Array.from(new Set(layerIds));
}
