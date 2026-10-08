// 土地被覆のクラス（表示名・割合列）。backendのレジストリ（domain/landcover.py:
// LANDCOVER_CLASSES）をexport_openapi.pyが書き出した生成物をそのまま読む。
//
// 配列の順序も生成物のまま使う（割合が同率のときの並びがこれで決まる）。

import landcoverClassesJson from "@/types/generated/landcover-classes.json";

interface LandcoverClass {
  /** AxisInspectorResult.landcoverの対応する割合列の名前。 */
  percentField: string;
  label: string;
}

export const LANDCOVER_CLASSES: readonly LandcoverClass[] = landcoverClassesJson.map((cls) => ({
  percentField: cls.percent_field,
  label: cls.label,
}));
