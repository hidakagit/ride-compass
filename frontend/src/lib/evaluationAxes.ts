// 評価軸のカタログ（単一ソース）。mapLayers.tsと同じ「カタログ＋汎用列挙」の型。
// 軸のid・重みキー・表示名をここへ一本化し、他のUI（RouteSettingsPanel等）へ
// 手作業で分散させない。
//
// RoutePreferenceWeightsはindex signature型（axis_idキーの辞書）のためコンパイル時の
// キー照合はできず、代わりにevaluationAxes.test.tsがaxis-catalog.jsonの
// preference_defaultsとキー集合を突き合わせる。
import type { RoutePreferenceWeights } from "@/types/route";
import type { MapValueKind } from "@/components/Map/valueScale";
import { SECONDARY_AXES } from "@/components/Map/secondaryAxes";
import type { AxisMaterialBreakdown } from "@/components/Map/secondaryAxes";
import axisCatalog from "@/types/generated/axis-catalog.json";

// 区間難易度の重み（route_preference）の既定値。「既定値に戻す」ボタンの起点、および
// 上書き有効化の直後に送る初期値として使う。axis-catalog.jsonのpreference_defaults
// （backend domain/axis_definitions.py: AXIS_DEFINITIONSのdefault_weightを生成物として
// 書き出したもの）から読むことで、軸の増減・既定値変更に自動追従する。
export const DEFAULT_ROUTE_PREFERENCE: RoutePreferenceWeights = axisCatalog.preference_defaults;

export interface PreferenceAxisDef {
  /** route_preference（axis_idキーの重み辞書）のキー。backend
   * domain/axis_definitions.py: AXIS_DEFINITIONSのaxis_idと一致する。 */
  axisId: string;
  /** 区間の色分け・RouteSettingsPanelの入力欄ラベルに共通で使う表示名 */
  label: string;
  description: string;
  /** この軸が専用のway_id→値配信レイヤー（Redis経由、ルート未確定時から地図上で
   * 視界内の全道路を線色分け表示できる）を持つかの宣言（domain/axis_definitions.py:
   * AxisDefinition.dedicated_way_value_layer参照）。`page.tsx`が、axis_idの
   * ハードコード比較ではなくこのフィールドで`dedicatedWayValueDisplays`
   * （軸id→表示宣言の汎用Map）・レンズ選択肢の`routeOnly`判定を行う。 */
  dedicatedWayValueLayer: boolean;
  /** 軸スタジオのdisplay_thresholds_override（未設定時はundefined）。
   * dedicatedWayValueLayer軸（現状windのみ）の評価軸グループ色分けしきい値に使う
   * （dedicatedWayValueLayer.ts: dedicatedWayValueColorExpression）。
   * SECONDARY_AXES由来の軸はkind="ramp"のためこのフィールドを使わない（常にundefined）。 */
  displayThresholdsOverride?: readonly number[] | null;
  /** displayThresholdsOverrideと対になる、段階ごとの体感ラベルの軽量な上書き。
   * SECONDARY_AXES由来の軸はkind="ramp"のためこのフィールドを使わない
   * （常にundefined、dedicatedWayValueLegendの消費者のみが対象）。 */
  displayBandLabelsOverride?: readonly string[] | null;
  /** 地図がこの軸について塗る値の種類・単位（GET /api/axis-catalogのmap_value_kind/
   * map_value_unit）。専用way値レイヤーの色式・凡例（dedicatedWayValueLayer.ts）が使う。 */
  mapValueKind?: MapValueKind;
  mapValueUnit?: string;
  /** 折れ点を通す前の生値の単位（GET /api/axis-catalogのraw_value_unit）。単位が定まる
   * 軸だけが持つ。ルート結果が得点の隣に生値を出すために使う（軸単体で経路を判断できる
   * ようにするため。得点は目盛りの引き方に依存する相対評価でしかない）。 */
  rawValueUnit?: string | null;
  /** 生値の単位が定まらない軸の内訳（GET /api/axis-catalogのmaterial_breakdown）。
   * 材料まで分解した絶対量の並びで、正規化重みの降順。単位が定まる軸は空配列。 */
  materialBreakdown?: readonly AxisMaterialBreakdown[];
}


// 重み一覧は公開軸すべてを対象にする。並び順・ラベルはSECONDARY_AXES（secondaryAxes.ts、
// 地図チップ・地図の見え方パネルの推定グループが共有する単一ソース）をそのままなぞり、
// 「この重みは地図のどの軸に対応するか」が名前と並びだけで分かるようにする（片側import）。
//
// SECONDARY_AXESは地図チップに出す軸だけへ絞り込まれている（category="動的"・
// show_map_icon=false の軸が落ちる）。**地図チップに出すかどうかと、重みを設定できるか
// どうかは別の判断**のため、落ちた公開軸はカタログの並び順のまま後ろへ足す——前者の都合で
// 後者を落とすと、軸スタジオで地図アイコンをOFFにした軸が重み一覧からも消える。
type CatalogAxisEntry = (typeof axisCatalog.axes)[number];

function preferenceAxisFromCatalog(axis: CatalogAxisEntry): PreferenceAxisDef {
  return {
    axisId: axis.axis_id,
    label: axis.label,
    description: axis.description ?? "",
    dedicatedWayValueLayer: axis.dedicated_way_value_layer ?? false,
    mapValueKind: axis.map_value_kind as MapValueKind | undefined,
    mapValueUnit: axis.map_value_unit,
    rawValueUnit: axis.raw_value_unit ?? null,
    materialBreakdown: (axis.material_breakdown ?? []).map((entry) => ({
      materialId: entry.material_id,
      label: entry.label,
      dtype: entry.dtype,
      unit: entry.unit,
      share: entry.share,
    })),
  };
}

export const PREFERENCE_AXES: readonly PreferenceAxisDef[] = [
  ...SECONDARY_AXES.map(
    (axis): PreferenceAxisDef => ({
      axisId: axis.axisId,
      label: axis.label,
      description: axis.description,
      // SECONDARY_AXESはkind='ramp'軸に限らない——gradientはkind="none"（材料がタイル
      // 非依存）でありながらdedicated_way_value_layer=trueという組み合わせが実在するため、
      // SECONDARY_AXES側のdedicatedWayValueLayerフィールドをそのまま引き継ぐ。
      dedicatedWayValueLayer: axis.dedicatedWayValueLayer ?? false,
      displayThresholdsOverride: axis.displayThresholdsOverride,
      displayBandLabelsOverride: axis.displayBandLabelsOverride,
      mapValueKind: axis.mapValueKind,
      mapValueUnit: axis.mapValueUnit,
      rawValueUnit: axis.rawValueUnit ?? null,
      materialBreakdown: axis.materialBreakdown ?? [],
    })
  ),
  ...axisCatalog.axes
    .filter((axis) => !SECONDARY_AXES.some((secondary) => secondary.axisId === axis.axis_id))
    .map(preferenceAxisFromCatalog),
];

// 軸の分類（観測/推定/動的）は一般向けルート設定画面（RouteSettingsPanel）の表示では
// 使わず、公開済みの軸をフラットな1本のリストとして扱う。分類データ自体（backend側の
// `category`フィールド、GET /api/axis-catalogのAxisCatalogEntry.category）は他用途の
// ため引き続き存在する。
