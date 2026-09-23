// 評価軸のカタログ（単一ソース）。mapLayers.tsと同じ「カタログ＋汎用列挙」の型。
// 軸のid・重みキー・表示名をここへ一本化し、他のUI（RouteSettingsPanel等）へ
// 手作業で分散させない。
//
// RoutePreferenceWeightsはaxis_idキーの辞書で、キーの綴り違いは型検査で落ちない。キーは
// 実行時の軸カタログ（`defaultWeights`）からだけ作り、送る前に`syncRoutePreferenceKeys`で
// カタログのキー集合へ揃える。
import type { CatalogAxis } from "@/components/Map/axisLayers";
import type { MapValueKind } from "@/components/Map/valueScale";
import type { AxisMaterialBreakdown } from "@/components/Map/secondaryAxes";
import { materialBreakdownFromCatalog } from "@/components/Map/secondaryAxes";

export interface PreferenceAxisDef {
  /** route_preference（axis_idキーの重み辞書）のキー。backend
   * domain/axis_definitions.py: AXIS_DEFINITIONSのaxis_idと一致する。 */
  axisId: string;
  /** 区間の色分け・RouteSettingsPanelの入力欄ラベルに共通で使う表示名 */
  label: string;
  /** 軸自身が持つアイコン（`icon_id`）。地図チップと内訳の凡例が同じ意匠を引く
   * （`components/Map/axisIconPalette.tsx: axisIconFor`）。 */
  iconId?: string | null;
  /** 地図チップと同じ略名（`chip_label`、最大4文字）。狭い幅で軸を並べる場所が使う。
   * 未設定の軸はlabelをそのまま使う（4文字以内のため略す必要がない）。 */
  chipLabel?: string | null;
  description: string;
  /** この軸が専用のway_id→値配信レイヤー（Redis経由、ルート未確定時から地図上で
   * 視界内の全道路を線色分け表示できる）を持つかの宣言（domain/axis_definitions.py:
   * AxisDefinition.dedicated_way_value_layer参照）。`page.tsx`が、axis_idの
   * ハードコード比較ではなくこのフィールドでレンズ選択肢の`routeOnly`判定を行う。 */
  dedicatedWayValueLayer: boolean;
  /** 地図がこの軸について塗る値の種類・単位（GET /api/axis-catalogのmap_value_kind/
   * map_value_unit）。軸スタジオのしきい値プレビューが、地図と同じ配色・単位で段を描くのに使う。 */
  mapValueKind?: MapValueKind;
  mapValueUnit?: string;
  /** 折れ点を通す前の生値の単位（GET /api/axis-catalogのraw_value_unit）。単位が定まる
   * 軸だけが持つ。ルート結果が得点の隣に生値を出すために使う（軸単体で経路を判断できる
   * ようにするため。得点は目盛りの引き方に依存する相対評価でしかない）。 */
  rawValueUnit?: string | null;
  /** 生値へ走行距離を掛けた総量の単位（GET /api/axis-catalogのraw_value_total_unit）。
   * 総量を出しても読み手の判断が変わらない軸はnull。 */
  rawValueTotalUnit?: string | null;
  /** 生値の単位が定まらない軸の内訳（GET /api/axis-catalogのmaterial_breakdown）。
   * 材料まで分解した絶対量の並びで、正規化重みの降順。単位が定まる軸は空配列。 */
  materialBreakdown?: readonly AxisMaterialBreakdown[];
}

// 重み一覧は公開軸すべてを対象にし、カタログの並び順のまま並べる。地図チップの一覧
// （secondaryAxes.ts）はshow_map_icon=falseの軸を落とすが、**地図チップに出すかどうかと、
// 重みを設定できるかどうかは別の判断**のため、重み一覧はそこから作らない——前者の都合で
// 後者を落とすと、軸スタジオで地図アイコンをOFFにした軸が重み一覧からも消える。

/** カタログ1件を重み一覧の1行へ。 */
export function preferenceAxisFromCatalog(axis: CatalogAxis): PreferenceAxisDef {
  return {
    axisId: axis.axis_id,
    label: axis.label,
    iconId: axis.icon_id ?? null,
    chipLabel: axis.chip_label ?? null,
    description: axis.description ?? "",
    dedicatedWayValueLayer: axis.dedicated_way_value_layer ?? false,
    mapValueKind: axis.map_value_kind,
    mapValueUnit: axis.map_value_unit,
    rawValueUnit: axis.raw_value_unit ?? null,
    rawValueTotalUnit: axis.raw_value_total_unit ?? null,
    materialBreakdown: materialBreakdownFromCatalog(axis.material_breakdown),
  };
}

// 軸の分類（観測/推定/動的）は一般向けルート設定画面（RouteSettingsPanel）の表示では
// 使わず、公開済みの軸をフラットな1本のリストとして扱う。分類データ自体（backend側の
// `category`フィールド、GET /api/axis-catalogのAxisCatalogEntry.category）は他用途の
// ため引き続き存在する。
