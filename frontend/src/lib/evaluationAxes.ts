// 重みを付けられる軸の一覧（公開軸すべて、カタログの並び順）。地図のチップの一覧（secondaryAxes.ts）からは作らない
// ——チップに出すかと重みを付けられるかは別の判断で、チップを消した軸が重みの一覧から消えてはいけない。
import type { AxisCatalogEntry } from "@/types/route";
import type { MapValueKind } from "@/lib/mapDisplay/valueScale";
import type { AxisMaterialBreakdown } from "@/lib/secondaryAxes";
import { materialBreakdownFromCatalog } from "@/lib/secondaryAxes";

export interface PreferenceAxisDef {
  /** 重みの辞書（`route_preference`）のキー。 */
  axisId: string;
  label: string;
  iconId?: string | null;
  /** 地図チップと同じ略名。狭い幅で軸を並べる場所が使う（無い軸は名前をそのまま使う）。 */
  chipLabel?: string | null;
  description: string;
  /** 専用の配信で、ルートの前から地図の道路を塗れるか。 */
  dedicatedWayValueLayer: boolean;
  mapValueKind?: MapValueKind;
  mapValueUnit?: string;
  /** 折れ点を通す前の生値の単位。単位が定まる軸だけが持ち、ルート結果は得点の隣に生値を出す（得点は目盛りの引き方で
   * 決まる相対の評価なので、軸だけで経路を判断できるように）。 */
  rawValueUnit?: string | null;
  /** 生値へ距離を掛けた総量の単位。総量を出しても判断が変わらない軸はnull。 */
  rawValueTotalUnit?: string | null;
  materialBreakdown?: readonly AxisMaterialBreakdown[];
}

/** カタログ1件を重み一覧の1行へ。 */
export function preferenceAxisFromCatalog(axis: AxisCatalogEntry): PreferenceAxisDef {
  return {
    axisId: axis.axis_id,
    label: axis.label,
    iconId: axis.icon_id,
    chipLabel: axis.chip_label,
    description: axis.description,
    dedicatedWayValueLayer: axis.dedicated_way_value_layer,
    mapValueKind: axis.map_value_kind,
    mapValueUnit: axis.map_value_unit,
    rawValueUnit: axis.raw_value_unit,
    rawValueTotalUnit: axis.raw_value_total_unit,
    materialBreakdown: materialBreakdownFromCatalog(axis.material_breakdown),
  };
}
