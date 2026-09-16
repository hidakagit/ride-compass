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
  /** 地図の面レイヤーで塗るか。falseでも区間インスペクタの割合には出る。 */
  painted: boolean;
}

export const LANDCOVER_CLASSES: readonly LandcoverClass[] = landcoverClassesJson.map((cls) => ({
  value: cls.value,
  percentField: cls.percent_field,
  label: cls.label,
  color: cls.color,
  painted: cls.painted,
}));

/** 地図の面レイヤーに実際に出るクラス。凡例はこちらを使う——塗らないクラスを凡例へ
 * 並べると、色見本があるのに地図のどこにも無い、という読み方のできない表になる。 */
export const LANDCOVER_PAINTED_CLASSES: readonly LandcoverClass[] = LANDCOVER_CLASSES.filter(
  (cls) => cls.painted,
);
