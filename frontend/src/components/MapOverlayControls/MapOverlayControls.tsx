"use client";

import styles from "./MapOverlayControls.module.css";

interface MapOverlayControlsProps {
  showElevation: boolean;
  onShowElevationToggle: (on: boolean) => void;
  showRoad: boolean;
  onShowRoadToggle: (on: boolean) => void;
  dynamicLayerOn: boolean;
  onDynamicLayerToggle: (on: boolean) => void;
  hasDetail: boolean;
  regionZoomTooWide: boolean;
}

// 地図レイヤーのON/OFFは「地図を見ながら頻繁に切り替える」操作のため、サイドバー内の
// チェックボックスではなく地図上のトグルチップとして重ね描きする（サイドバーを開閉せずに
// 操作できるようにする）。凡例・ズーム警告も対象レイヤーがONのときだけ地図上に出すことで、
// サイドバー側の常設の説明文を不要にしている。
export default function MapOverlayControls({
  showElevation,
  onShowElevationToggle,
  showRoad,
  onShowRoadToggle,
  dynamicLayerOn,
  onDynamicLayerToggle,
  hasDetail,
  regionZoomTooWide,
}: MapOverlayControlsProps) {
  const showRoadLegend = showRoad && !regionZoomTooWide;
  const showWindLegend = dynamicLayerOn && hasDetail;

  return (
    <div className={styles.wrapper}>
      <div className={styles.chipRow}>
        <button
          type="button"
          aria-pressed={showElevation}
          onClick={() => onShowElevationToggle(!showElevation)}
          className={showElevation ? styles.chipActive : styles.chip}
          title="国土地理院の色別標高図を重ねる"
        >
          標高
        </button>
        <button
          type="button"
          aria-pressed={showRoad}
          onClick={() => onShowRoadToggle(!showRoad)}
          className={showRoad ? styles.chipActive : styles.chip}
          title="路面（舗装/未舗装）で道路を色分けする"
        >
          路面
        </button>
        <button
          type="button"
          aria-pressed={dynamicLayerOn && hasDetail}
          disabled={!hasDetail}
          onClick={() => onDynamicLayerToggle(!dynamicLayerOn)}
          className={dynamicLayerOn && hasDetail ? styles.chipActive : styles.chip}
          title={hasDetail ? "選択中ルートの風の影響を色分けする" : "ルートを生成・選択すると使えます"}
        >
          風
        </button>
      </div>

      {showRoad && regionZoomTooWide && (
        <p className={styles.zoomWarning}>表示範囲が広すぎます。ズームインしてください。</p>
      )}

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
    </div>
  );
}
