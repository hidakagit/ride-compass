// 凡例の1行。道路の線の分類とルートの色分けのモード（routeStyleModes.ts）が同じ凡例UI・
// 絞り込みの仕組みを共有するため、両方が読むこの層に置く。

export interface LegendEntry {
  /** カテゴリの安定識別子（表示/非表示状態のキー。ラベル文言の変更に影響されない） */
  key: string;
  color: string;
  label: string;
  /** 大きさで意味を示す行の見本の直径。持つ行は色ではなく大きさを見せる（地図の点と同じ大きさ）。 */
  diameterPx?: number;
  /** 地図で線として描く行か。見本を地図と同じ線の形で見せる（持たない行は点の形）。 */
  line?: true;
  /** この地物がカテゴリに属するときtrueになるMapLibre式（凡例フィルタ用の述語）。
   * 絞り込みを自分で持つレイヤー（scene のグループが宣言するもの）は持たない。 */
  filter?: unknown[];
  /** trueなら値が無いものの受け皿（不明・データなし）であり、他のカテゴリのような実際の判定値ではないことを示す。
   * 凡例の描画側（▶パネル・MapOverlayControls）が区切り線＋弱調表示にすることで、数値/順序段階と受け皿を
   * 視覚的に分離する（凡例が「1・2・3・4・不明」の5項目に見え「1〜5評価」と誤解されることを避ける）。
   * 色見本は地図の破線と同じく途切れた形にする（`legendSwatchBackground`）。 */
  isFallback?: boolean;
}

/** 凡例の色見本の塗り。値が無い行は、地図の破線と同じく途切れた見本にする。 */
export function legendSwatchBackground(entry: LegendEntry): string {
  if (entry.isFallback !== true) return entry.color;
  return `repeating-linear-gradient(90deg, ${entry.color} 0 3px, transparent 3px 5px)`;
}
