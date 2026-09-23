// 軸カタログの変換関数（`*FromCatalogAxes`）へ渡す軸を、テストが自分で組むためのビルダー。
//
// **実際の公開軸を入力に使わない。** 軸idは軸スタジオでユーザーが決める任意の値で、公開
// される集合もDBが持つ。実物を当てにしたテストは、変換の正しさではなく「いま何が公開されて
// いるか」を検証することになる。
//
// **既定値は型を満たすための空だけ。** しきい値・単位・入力のような「もっともらしい値」を
// 既定で持たせると、それに関心のないテストまでその値に依存し、無関係な変更で落ちる。
// 見たい性質は呼び出し側が書く。

import type { CatalogAxis } from "@/lib/mapDisplay/axisLayers";

type CatalogAxisDisplay = CatalogAxis["display"];

export function catalogAxis(
  overrides: Partial<Omit<CatalogAxis, "display">> & { display?: Partial<CatalogAxisDisplay> } = {},
): CatalogAxis {
  const { display, ...rest } = overrides;
  return {
    axis_id: "axis",
    label: "軸",
    description: "",
    category: "推定",
    show_map_icon: true,
    ...rest,
    display: {
      kind: "ramp",
      label: "軸",
      category: "roadCondition",
      tile_inputs: [],
      thresholds: [],
      ...display,
    },
  };
}
