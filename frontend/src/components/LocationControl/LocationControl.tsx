"use client";

import type { Coordinates, LocationSource } from "@/types/route";

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
    <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", fontSize: "0.85rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
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
        <form onSubmit={onManualSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
          <label>
            緯度
            <input
              type="text"
              value={manualLat}
              onChange={(e) => onManualLatChange(e.target.value)}
              style={{ marginLeft: "0.25rem", width: "8rem" }}
            />
          </label>
          <label>
            経度
            <input
              type="text"
              value={manualLng}
              onChange={(e) => onManualLngChange(e.target.value)}
              style={{ marginLeft: "0.25rem", width: "8rem" }}
            />
          </label>
          <button type="submit">設定</button>
        </form>
      )}
    </div>
  );
}
