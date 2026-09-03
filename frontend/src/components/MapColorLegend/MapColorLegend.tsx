"use client";

import type { MapColorLegendBand } from "@/components/Map/mapColorLegend";
import styles from "./MapColorLegend.module.css";

export interface MapColorLegendGroup {
  axisId: string;
  label: string;
  bands: readonly MapColorLegendBand[];
}

// ユーザー要望（2026-08-31、「地図上の色付の凡例が欲しい。例えば、勾配ONにした時に青くなる
// 道路は何なのか、その度合いが分かればいい」）: ルート設定パネルの「地図で色分け」を
// ONにしている軸ぶんだけ、地図上部中央に色→値の対応を常時小さく表示する（モバイルの
// BottomSheetが画面下側を覆っても隠れない配置）。OFFにすると消える（page.tsx側がgroupsを
// 空配列にする）。複数軸が同時にONの場合は縦に積む。
export default function MapColorLegend({ groups }: { groups: readonly MapColorLegendGroup[] }) {
  if (groups.length === 0) return null;
  return (
    <div className={styles.wrap}>
      {groups.map((group) => (
        <div key={group.axisId} className={styles.group}>
          <p className={styles.groupLabel}>{group.label}</p>
          <ul className={styles.bandList}>
            {group.bands.map((band) => (
              <li key={band.label} className={styles.bandRow}>
                <span aria-hidden="true" className={styles.swatch} style={{ background: band.color }} />
                <span className={styles.bandLabel}>{band.label}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
