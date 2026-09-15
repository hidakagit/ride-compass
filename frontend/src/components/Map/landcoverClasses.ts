// 土地被覆のクラス（表示名・色・割合列）。backendのレジストリ（domain/landcover.py:
// LANDCOVER_CLASSES）をexport_openapi.pyが書き出した生成物をそのまま読む。地図タイルの
// 塗りと同じ値のため、凡例の色と地図の色は常に一致する。
//
// 配列の順序も生成物のまま使う（割合が同率のときの並びがこれで決まる）。

import landcoverClassesJson from "@/types/generated/landcover-classes.json";

export interface LandcoverClass {
  /** ラスタの画素値。 */
  value: number;
  /** AxisInspectorResult.landcoverの対応する割合列の名前。 */
  percentField: string;
  label: string;
  color: string;
}

export const LANDCOVER_CLASSES: readonly LandcoverClass[] = landcoverClassesJson.map((cls) => ({
  value: cls.value,
  percentField: cls.percent_field,
  label: cls.label,
  color: cls.color,
}));
