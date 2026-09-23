/** 地図の見え方として`MapView`へ渡す値。**状態そのものだけを持つ**——軸カタログ・タイル世代の
 * ような共有の源泉から導けるもの、ここにある値の組み合わせから導けるもの（どのレイヤーを出すか・
 * 家族ごとの隠した行・下敷き）は地図の側で導く。 */
import type { DynamicWeatherGroupState, DynamicWeatherLayerId } from "@/components/Map/dynamicWeather";
import type { LayerDataStatusByLayer, MapLayerVisibility } from "@/components/Map/mapLayers";
import type { LensId } from "@/components/Map/routeStyleModes";
import type { MapViewport } from "@/components/Map/windLayer";
import type { DedicatedWayValuesResult } from "@/hooks/useDedicatedWayValues";

/** 凡例の保存先id → 隠した行の鍵。空になった鍵は持たない。 */
export type HiddenLegendKeys = Readonly<Record<string, readonly string[]>>;

export interface MapLook {
  layerVisibility: MapLayerVisibility;
  dynamicWeather: Partial<Record<DynamicWeatherLayerId, DynamicWeatherGroupState>>;
  /** ルート線の色分けのモード。 */
  lens: LensId;
  /** 全道路を塗っている軸（塗っていなければnull）。 */
  paintedAxisId: LensId | null;
  /** 専用配信軸ごとの取得結果（値と取得中か）。 */
  dedicatedWayValues: ReadonlyMap<string, DedicatedWayValuesResult>;
  /** 地図の絞り込みへ当てる、隠した行。 */
  hiddenLegendKeys: HiddenLegendKeys;
  /** 増えるたびに地図を描き直す。 */
  refreshToken: number;
  onViewportChange: (viewport: MapViewport) => void;
  onLayerDataStatusChange: (status: LayerDataStatusByLayer) => void;
}
