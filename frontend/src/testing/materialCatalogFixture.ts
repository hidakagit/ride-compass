import type { MaterialCatalogResponse } from "@/types/route";

/** 材料カタログの応答。性質（数値・真偽・分類）だけを表す材料で、実在の材料は使わない。
 *  軸スタジオの画面は「どの性質の材料が選べるか」でしか分岐しない。 */
export function materialCatalogFixture(): MaterialCatalogResponse {
  return {
    materials: [
      {
        material_id: "num_a",
        label: "数値の材料 - num_a",
        name: "数値の材料",
        description: "テスト用の数値材料。",
        dtype: "numeric",
        unit: "%",
        reference_points: [
          { label: "低い", value: 0 },
          { label: "高い", value: 10 },
        ],
      },
      {
        material_id: "num_b",
        label: "もう1つの数値の材料 - num_b",
        name: "もう1つの数値の材料",
        description: "テスト用の数値材料。",
        dtype: "numeric",
        unit: "回/km",
        reference_points: [],
      },
      {
        material_id: "bool_a",
        label: "真偽の材料 - bool_a",
        name: "真偽の材料",
        description: "テスト用の真偽材料。",
        dtype: "boolean",
        unit: "",
        reference_points: [],
      },
      {
        material_id: "bool_b",
        label: "もう1つの真偽の材料 - bool_b",
        name: "もう1つの真偽の材料",
        description: "テスト用の真偽材料。",
        dtype: "boolean",
        unit: "",
        reference_points: [],
      },
      {
        material_id: "cat_a",
        label: "分類の材料 - cat_a",
        name: "分類の材料",
        description: "テスト用の分類材料。",
        dtype: "categorical",
        unit: "",
        reference_points: [],
      },
    ],
  };
}
