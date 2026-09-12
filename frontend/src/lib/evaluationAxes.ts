// 評価軸のカタログ（単一ソース）。mapLayers.tsと同じ「カタログ＋汎用列挙」の型。
// 軸のid・重みキー・表示名をここへ一本化し、他のUI（RouteSettingsPanel等）へ
// 手作業で分散させない。
//
// RoutePreferenceWeightsはindex signature型（axis_idキーの辞書）のためコンパイル時の
// キー照合はできず、代わりにevaluationAxes.test.tsがaxis-catalog.jsonの
// preference_defaultsとキー集合を突き合わせる。
import type { RoutePreferenceWeights } from "@/types/route";
import type { MapValueKind } from "@/components/Map/valueScale";
import type { CatalogAxis } from "@/components/Map/axisLayers";
import { SECONDARY_AXES } from "@/components/Map/secondaryAxes";
import type { AxisMaterialBreakdown } from "@/components/Map/secondaryAxes";
import { materialBreakdownFromCatalog } from "@/components/Map/secondaryAxes";
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


// 重み一覧は公開軸すべてを対象にする。並び順はSECONDARY_AXES（secondaryAxes.ts、
// 地図チップ・地図の見え方パネルの推定グループが共有する単一ソース）をそのままなぞり、
// 「この重みは地図のどの軸に対応するか」が名前と並びだけで分かるようにする（片側import）。
//
// SECONDARY_AXESは地図チップに出す軸だけへ絞り込まれている（show_map_icon=false の軸が
// 落ちる）。**地図チップに出すかどうかと、重みを設定できるかどうかは別の判断**のため、
// 落ちた公開軸はカタログの並び順のまま後ろへ足す——前者の都合で後者を落とすと、
// 軸スタジオで地図アイコンをOFFにした軸が重み一覧からも消える。
//
// **SECONDARY_AXESからは並び順だけを取り、中身は必ずカタログから組み立てる**。
// 並びの由来ごとに別の組み立てを書くと、片方にだけフィールドを書き足した状態が
// 型検査を通ってしまう（`PreferenceAxisDef`のフィールドはすべてoptionalのため）。

/** カタログ1件を重み一覧の1行へ。実行時API経路（useAxisCatalog）と共有する唯一の変換。 */
export function preferenceAxisFromCatalog(axis: CatalogAxis): PreferenceAxisDef {
  return {
    axisId: axis.axis_id,
    label: axis.label,
    description: axis.description ?? "",
    dedicatedWayValueLayer: axis.dedicated_way_value_layer ?? false,
    displayThresholdsOverride: axis.display_thresholds_override ?? undefined,
    displayBandLabelsOverride: axis.display_band_labels_override ?? undefined,
    mapValueKind: axis.map_value_kind as MapValueKind | undefined,
    mapValueUnit: axis.map_value_unit,
    rawValueUnit: axis.raw_value_unit ?? null,
    materialBreakdown: materialBreakdownFromCatalog(axis.material_breakdown),
  };
}

const SECONDARY_AXIS_ORDER = new Map(SECONDARY_AXES.map((axis, index) => [axis.axisId, index]));

export const PREFERENCE_AXES: readonly PreferenceAxisDef[] = (axisCatalog.axes as CatalogAxis[])
  .map((axis, catalogIndex) => ({ axis, catalogIndex }))
  .sort((a, b) => {
    const orderA = SECONDARY_AXIS_ORDER.get(a.axis.axis_id);
    const orderB = SECONDARY_AXIS_ORDER.get(b.axis.axis_id);
    if (orderA !== undefined && orderB !== undefined) return orderA - orderB;
    if (orderA !== undefined) return -1;
    if (orderB !== undefined) return 1;
    return a.catalogIndex - b.catalogIndex;
  })
  .map(({ axis }) => preferenceAxisFromCatalog(axis));

// 軸の分類（観測/推定/動的）は一般向けルート設定画面（RouteSettingsPanel）の表示では
// 使わず、公開済みの軸をフラットな1本のリストとして扱う。分類データ自体（backend側の
// `category`フィールド、GET /api/axis-catalogのAxisCatalogEntry.category）は他用途の
// ため引き続き存在する。
