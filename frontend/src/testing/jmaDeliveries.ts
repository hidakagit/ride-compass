// 気象のレイヤーのテストが、配信要素（コマのパスのテンプレート・更新間隔等）を源泉の宣言（`mapDisplay.weatherElements`）の
// 本物から取るための口。

import type { JmaDelivery } from "@/features/map/layers/jmaDelivery";
import { mapDisplay } from "@/types/generated/mapDisplay";

/** 時刻の段1つぶんの配信要素を、要素idで引く。 */
export const jmaDeliveryOf = (id: string): JmaDelivery =>
  mapDisplay.weatherElements
    .flatMap((element): readonly JmaDelivery[] => element.jmaElements)
    .find((delivery) => delivery.id === id)!;
