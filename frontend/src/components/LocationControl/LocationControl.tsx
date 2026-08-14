"use client";

import type { Coordinates, LocationSource } from "@/types/route";
import styles from "./LocationControl.module.css";

const SOURCE_LABEL: Record<LocationSource, string> = {
  geolocation: "現在地（取得済み）",
  manual: "手動入力",
  default: "デフォルト（東京・王子）",
};

interface LocationControlProps {
  location: Coordinates;
  source: LocationSource;
  manualLat: string;
  manualLng: string;
  showManualInput: boolean;
  onManualLatChange: (value: string) => void;
  onManualLngChange: (value: string) => void;
  onToggleManualInput: () => void;
  onManualSubmit: (event: React.FormEvent) => void;
}

export default function LocationControl({
  location,
  source,
  manualLat,
  manualLng,
  showManualInput,
  onManualLatChange,
  onManualLngChange,
  onToggleManualInput,
  onManualSubmit,
}: LocationControlProps) {
  return (
    <div className={styles.wrapper}>
      <div className={styles.sourceRow}>
        <span>
          位置情報: {SOURCE_LABEL[source]}
          <br />
          {location.latitude.toFixed(5)}, {location.longitude.toFixed(5)}
        </span>
      </div>
      <button type="button" onClick={onToggleManualInput}>
        緯度経度を手動入力
      </button>

      {showManualInput && (
        <form onSubmit={onManualSubmit} className={styles.manualForm}>
          <label>
            緯度
            <input
              type="text"
              value={manualLat}
              onChange={(e) => onManualLatChange(e.target.value)}
              className={styles.manualInput}
            />
          </label>
          <label>
            経度
            <input
              type="text"
              value={manualLng}
              onChange={(e) => onManualLngChange(e.target.value)}
              className={styles.manualInput}
            />
          </label>
          <button type="submit">設定</button>
        </form>
      )}
    </div>
  );
}
