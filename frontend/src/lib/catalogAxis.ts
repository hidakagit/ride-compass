// 軸カタログ（`GET /api/axis-catalog`）の1行を、画面が読む形へ移す。**行から移すのはここの1か所だけ**——
// 重みを付けられる軸の一覧・ramp軸・専用配信の軸・地図のチップの軸は、どれもこの形に自分の用途の項目を足した型で、
// 共通の項目（名前・略名・アイコン・説明・単位・内訳）を自前で写さない。写すと、同じ行の略名の補い方が型ごとに食い違う。
import type { MapValueKind } from "@/lib/mapDisplay/valueScale";
import type { AxisCatalogEntry } from "@/types/route";

/** 生値の単位が定まらない軸の内訳1件（材料と、軸の生値に占める割合。正規化重みの降順）。 */
interface AxisMaterialBreakdown {
  materialId: string;
  label: string;
  /** `numeric`＝距離加重平均＋単位、`boolean`＝該当区間の延長割合。 */
  dtype: string;
  /** numeric材料の単位。真偽値材料は空文字。 */
  unit: string;
  share: number;
  /** categorical材料の「タグ生値→論理名」対訳（他の型では空）。フロントは対応表を持たない。 */
  valueLabels?: Readonly<Record<string, string>>;
}

export interface CatalogAxis {
  /** 軸id。重みの辞書（`route_preference`）のキーでもある。 */
  axisId: string;
  label: string;
  /** 地図チップ（固定幅のタイル）の名前。略名が無い軸は名前そのもの。 */
  chipLabel: string;
  description: string;
  /** 軸のアイコン（`components/ui/icons/axisIconPalette.tsx: axisIconFor`が引く）。未設定は汎用のアイコン。 */
  iconId?: string;
  /** 表示の設定パネルでこの軸の行の(i)が出す、descriptionより詳しい説明。 */
  panelHint?: string;
  /** 専用の配信で、ルートの前から地図の道路を塗れるか（地図の表示の種類からは導けない）。 */
  dedicatedWayValueLayer: boolean;
  mapValueKind: MapValueKind;
  mapValueUnit: string;
  /** 折れ点を通す前の生値の単位。単位が定まる軸だけが持ち、ルート結果は得点の隣に生値を出す（得点は目盛りの引き方で
   * 決まる相対の評価なので、軸だけで経路を判断できるように）。 */
  rawValueUnit: string | null;
  /** 生値へ距離を掛けた総量の単位。総量を出しても判断が変わらない軸はnull。 */
  rawValueTotalUnit: string | null;
  materialBreakdown: readonly AxisMaterialBreakdown[];
  /** 軸が読む材料の一次属性id（地図のレイヤーを持つものは、レイヤーの名前と同じ）。 */
  primaryAttributeIds: readonly string[];
  /** 軸の材料の元データを描く気象のチップ（一次属性を持たない動的な材料の分）。 */
  weatherLayerGroups: readonly string[];
}

export function catalogAxisFromEntry(axis: AxisCatalogEntry): CatalogAxis {
  return {
    axisId: axis.axis_id,
    label: axis.label,
    chipLabel: axis.chip_label ?? axis.label,
    description: axis.description,
    iconId: axis.icon_id ?? undefined,
    panelHint: axis.panel_hint ?? undefined,
    dedicatedWayValueLayer: axis.dedicated_way_value_layer,
    mapValueKind: axis.map_value.kind,
    mapValueUnit: axis.map_value_unit,
    rawValueUnit: axis.raw_value_unit,
    rawValueTotalUnit: axis.raw_value_total_unit,
    materialBreakdown: axis.material_breakdown.map((entry) => ({
      materialId: entry.material_id,
      label: entry.label,
      dtype: entry.dtype,
      unit: entry.unit,
      share: entry.share,
      valueLabels: entry.value_labels,
    })),
    primaryAttributeIds: axis.primary_attribute_ids,
    weatherLayerGroups: axis.weather_layer_groups,
  };
}
