"use client";

import type { Coordinates, LocationSource } from "@/types/route";
import styles from "./LocationControl.module.css";

const SOURCE_LABEL: Record<LocationSource, string> = {
  geolocation: "現在地[取得済み]",
  // 「デフォルト」は開発用語のため、初見でも意味が取れる表現にする（T30）
  default: "初期地点[東京・王子]",
};

interface LocationControlProps {
  location: Coordinates;
  source: LocationSource;
}

// 出発地点の表示のみを行う（緯度経度の手動入力は改善計画T35で撤去。現在地の再取得は
// 地図上の「現在地に移動」ボタン、page.tsxのhandleLocateMeが担う）。
export default function LocationControl({ location, source }: LocationControlProps) {
  return (
    <div className={styles.wrapper}>
      {/* ルート生成の入力（周回の起点）であることが伝わるよう「位置情報」から言い換える（T30） */}
      <span>
        出発地点: {SOURCE_LABEL[source]}
        <br />
        {location.latitude.toFixed(5)}, {location.longitude.toFixed(5)}
      </span>
    </div>
  );
}
