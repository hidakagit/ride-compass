/** 地図の見え方として`MapView`へ渡す値。状態そのもの（`SceneLook`）と、地図から見え方へ戻る
 * イベントだけを持つ——軸カタログ・タイル世代のような共有の源泉から導けるものは地図が自分で読む。 */
import type { LayerDataStatusByLayer } from "@/features/map/layers/mapLayers";
import type { MapViewport } from "@/features/map/layers/windLayer";
import type { HiddenLegendKeys, SceneLook } from "@/features/map/scene/applyToMap";

export type { HiddenLegendKeys };

export interface MapLook extends SceneLook {
  /** 増えるたびに地図を描き直す。 */
  readonly refreshToken: number;
  readonly onViewportChange: (viewport: MapViewport) => void;
  readonly onLayerDataStatusChange: (status: LayerDataStatusByLayer) => void;
}
