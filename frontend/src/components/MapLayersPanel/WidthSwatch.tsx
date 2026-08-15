import styles from "./WidthSwatch.module.css";

interface WidthSwatchProps {
  /** 地図のline-widthに使う実際の太さ(px)。roadFilterAxes.tsのHIGHWAY_GROUPS参照。 */
  width: number;
  /** trueなら破線プレビュー（roadFilterAxes.tsのdashArrayExpression参照。「不明・他」用）。 */
  dashed?: boolean;
}

// 「道路の種類」は色ではなく太さ（line-width）・線種（line-dasharray）で地図に反映するため
// （roadFilterAxes.ts参照）、チェックボックスや凡例のプレビューも色スウォッチではなく
// 実際の太さ・線種を示すバーにする（色スウォッチのままだと「この色が地図に出る」という
// 誤った期待を持たせてしまうため）。地図上の実寸（1.75〜6px）のままだと一覧内での差が
// 分かりにくいので、拡大して見せる。
const DISPLAY_SCALE = 1.8;
const BAR_LENGTH_PX = 18;

export default function WidthSwatch({ width, dashed = false }: WidthSwatchProps) {
  const height = Math.max(2, width * DISPLAY_SCALE);
  return (
    <span
      className={dashed ? `${styles.bar} ${styles.barDashed}` : styles.bar}
      style={{ height: `${height}px`, width: `${BAR_LENGTH_PX}px` }}
      aria-hidden="true"
    />
  );
}
