// 気象のレイヤーのテストが、配信要素（コマのパスのテンプレート・更新間隔等）を源泉の宣言（`mapDisplay.weatherElements`）の
// 本物から取るための口。

import type { JmaDelivery } from "@/features/map/layers/jmaDelivery";
import { mapDisplay } from "@/types/generated/mapDisplay";

/** 源泉が宣言する配信要素（宣言の順）。 */
export const JMA_DELIVERIES: readonly JmaDelivery[] = mapDisplay.weatherElements.flatMap(
  (element): readonly JmaDelivery[] => element.jmaElements,
);

/** 時刻の段1つぶんの配信要素を、要素idで引く。 */
export const jmaDeliveryOf = (id: string): JmaDelivery => JMA_DELIVERIES.find((delivery) => delivery.id === id)!;

/** 地図ライブラリがタイルのテンプレートへタイル座標を埋めたURL。 */
export const jmaTileUrlAt = (template: string, z: number, x: number, y: number): string =>
  template.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));
