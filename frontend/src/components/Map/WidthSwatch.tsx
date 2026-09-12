import styles from "./WidthSwatch.module.css";

interface WidthSwatchProps {
  /** 地図のline-widthに使う実際の太さ(px)。roadFilterAxes.tsのHIGHWAY_GROUPS参照。 */
  width: number;
  /** trueなら破線プレビュー（roadFilterAxes.tsのdashArrayExpression参照。「不明・他」用）。 */
  dashed?: boolean;
  /** バーの塗り色（未指定ならCSS既定の中立色）。改善計画: 「道路種別が支配的な場合、色が
   * すべて灰色で違和感がある」への対応で道路の種類にも濃淡パレット（COLOR_HIGHWAY_*）を
   * 持たせたため、凡例のバーも地図と同じ色で塗って対応関係を示す
   * （entry.colorをそのまま渡す、呼び出し側参照）。 */
  color?: string;
}

// 「道路の種類」は色ではなく太さ（line-width）・線種（line-dasharray）で地図に反映するため
// （roadFilterAxes.ts参照）、チェックボックスや凡例のプレビューも色スウォッチではなく
// 実際の太さ・線種を示すバーにする（色スウォッチのままだと「この色が地図に出る」という
// 誤った期待を持たせてしまうため）。地図上の実寸（1.75〜6px）のままだと一覧内での差が
// 分かりにくいので、拡大して見せる。
const DISPLAY_SCALE = 1.8;
const BAR_LENGTH_PX = 18;

export default function WidthSwatch({ width, dashed = false, color }: WidthSwatchProps) {
  const height = Math.max(2, width * DISPLAY_SCALE);
  // 破線は背景をrepeating-linear-gradientで描くため、colorがあればCSS変数
  // --width-swatch-color経由で渡す（module.cssのbackground/background-imageの両方が
  // この変数を参照する。実線側はbackgroundColorの直接指定でも足りるが、変数を共有した方が
  // 実線/破線で色指定のロジックが1本化できる）。
  const style: React.CSSProperties & { "--width-swatch-color"?: string } = {
    height: `${height}px`,
    width: `${BAR_LENGTH_PX}px`,
  };
  if (color) style["--width-swatch-color"] = color;
  return (
    <span
      className={dashed ? `${styles.bar} ${styles.barDashed}` : styles.bar}
      style={style}
      aria-hidden="true"
    />
  );
}
