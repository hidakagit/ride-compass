"use client";

import styles from "./MapLayerControls.module.css";

interface MapLayerControlsProps {
  showElevation: boolean;
  onShowElevationToggle: (on: boolean) => void;
  showRoad: boolean;
  onShowRoadToggle: (on: boolean) => void;
  dynamicLayerOn: boolean;
  onDynamicLayerToggle: (on: boolean) => void;
  hasDetail: boolean;
  regionZoomTooWide: boolean;
  onRefresh: () => void;
}

export default function MapLayerControls({
  showElevation,
  onShowElevationToggle,
  showRoad,
  onShowRoadToggle,
  dynamicLayerOn,
  onDynamicLayerToggle,
  hasDetail,
  regionZoomTooWide,
  onRefresh,
}: MapLayerControlsProps) {
  const showRoadLegend = showRoad && !regionZoomTooWide;
  const showWindLegend = dynamicLayerOn && hasDetail;

  return (
    <div className={styles.wrapper}>
      <strong>地図レイヤー</strong>

      <div>
        <div className={styles.sectionLabel}>常時表示（表示中の地域全体・変わらないデータ、標高/路面は同時に重ね表示可）</div>
        <label className={styles.checkboxLabel}>
          <input type="checkbox" checked={showElevation} onChange={(e) => onShowElevationToggle(e.target.checked)} />
          標高（国土地理院 色別標高図）
        </label>
        <label className={styles.checkboxLabel}>
          <input type="checkbox" checked={showRoad} onChange={(e) => onShowRoadToggle(e.target.checked)} />
          路面で色分け
        </label>
        {showRoad && regionZoomTooWide && (
          <p className={styles.zoomWarning}>表示範囲が広すぎます。地図をズームインしてください。</p>
        )}
      </div>

      <div>
        <div className={styles.sectionLabel}>選択中ルートのみ（時間で変わるデータ）</div>
        <label className={hasDetail ? styles.checkboxLabel : styles.checkboxLabelMuted}>
          <input
            type="checkbox"
            checked={dynamicLayerOn}
            disabled={!hasDetail}
            onChange={(e) => onDynamicLayerToggle(e.target.checked)}
          />
          風の影響を表示
        </label>
      </div>

      {showRoadLegend && (
        <div className={styles.legendRow}>
          <span className={`${styles.swatch} ${styles.swatchGood}`} />
          舗装路
          <span className={`${styles.swatchSpaced} ${styles.swatchBad}`} />
          未舗装等
          <span className={`${styles.swatchSpaced} ${styles.swatchUnknown}`} />
          不明
        </div>
      )}

      {showWindLegend && (
        <div className={styles.legendRow}>
          <span className={`${styles.swatch} ${styles.swatchGood}`} />
          易しい
          <span className={`${styles.swatchSpaced} ${styles.swatchNormal}`} />
          普通
          <span className={`${styles.swatchSpaced} ${styles.swatchBad}`} />
          難しい
        </div>
      )}

      <button type="button" onClick={onRefresh} className={styles.refreshButton}>
        変わらないデータを更新
      </button>
    </div>
  );
}
