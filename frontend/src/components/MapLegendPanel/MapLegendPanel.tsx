"use client";

import {
  ROAD_LINE_COLOR_AXIS_ID,
  ROAD_LINE_WIDTH_AXIS_ID,
  getRoadFilterAxis,
  type RoadFilterAxisId,
} from "@/components/Map/roadFilterAxes";
import { ROUTE_STYLE_MODES, getRouteStyleMode, type RouteStyleModeId } from "@/components/Map/routeStyleModes";
import type { LegendEntry } from "@/components/Map/legendFilter";
import WidthSwatch from "@/components/MapOverlayControls/WidthSwatch";
import styles from "./MapLegendPanel.module.css";

interface MapLegendPanelProps {
  showRoad: boolean;
  /** 路面の2軸（路面の種類・道路の種類）それぞれの非表示カテゴリキー */
  roadHiddenKeysByMode: Record<RoadFilterAxisId, readonly string[]>;
  regionZoomTooWide: boolean;
  routeLayerOn: boolean;
  onRouteLayerToggle: (on: boolean) => void;
  routeStyleModeId: RouteStyleModeId;
  onRouteStyleModeChange: (id: RouteStyleModeId) => void;
  hiddenRouteLegendKeys: readonly string[];
  onRouteLegendToggle: (key: string) => void;
  hasDetail: boolean;
}

// 地図に何が描かれているか（色・太さの意味、絞り込み状態、ルートの色分け選択）を
// まとめて見せるサイドバー内パネル。以前は地図の上に凡例・絞り込み文言・モード選択パネルを
// 積み重ねていたが、地図自体が狭く見づらくなるという指摘を受けてサイドバーへ移した。
// 地図の上（MapOverlayControls）に残るのは、チップの押下状態と絞り込み中を示す小さな
// ドットだけで、「これが何を意味するか」はすべてここで説明する。
//
// 路面（roadFilterAxes.ts）は「路面の種類」を色・「道路の種類」を太さで同時に地図へ反映する。
// 色を2軸掛け合わせると細い線では判別できなくなるため、道路の種類には太さという別の
// 視覚チャンネルを割り当てている。凡例のプレビューもentry.widthの有無で自動的に
// 色スウォッチ/太さバーを切り替える（WidthSwatch参照）。
export default function MapLegendPanel({
  showRoad,
  roadHiddenKeysByMode,
  regionZoomTooWide,
  routeLayerOn,
  onRouteLayerToggle,
  routeStyleModeId,
  onRouteStyleModeChange,
  hiddenRouteLegendKeys,
  onRouteLegendToggle,
  hasDetail,
}: MapLegendPanelProps) {
  const roadColorAxis = getRoadFilterAxis(ROAD_LINE_COLOR_AXIS_ID);
  const roadWidthAxis = getRoadFilterAxis(ROAD_LINE_WIDTH_AXIS_ID);
  const routeStyleMode = getRouteStyleMode(routeStyleModeId);

  function handleRouteModeSelect(id: RouteStyleModeId) {
    onRouteStyleModeChange(id);
    if (!routeLayerOn) onRouteLayerToggle(true);
  }

  // 参照用の凡例（タップでは操作しない）。太さ軸（entry.widthを持つ）は太さバー、
  // それ以外は色スウォッチでプレビューする。非表示中のカテゴリは薄く+取り消し線にする。
  function renderLegendDisplay(legend: readonly LegendEntry[], hiddenKeys: readonly string[]) {
    return (
      <div className={styles.legendRow}>
        {legend.map((entry) => {
          const visible = !hiddenKeys.includes(entry.key);
          return (
            <span
              key={entry.key}
              className={visible ? styles.legendItem : `${styles.legendItem} ${styles.legendItemHidden}`}
            >
              {entry.width !== undefined ? (
                <WidthSwatch width={entry.width} dashed={entry.dashed} />
              ) : (
                <span className={styles.swatch} style={{ background: entry.color }} />
              )}
              {entry.label}
            </span>
          );
        })}
      </div>
    );
  }

  // ルート側は1モード・1系統のみで組み合わせ絞り込みの需要が無いため、凡例そのものを
  // チェックボックスにして参照表示と絞り込み操作を1つのリストで兼ねる（即時反映）。
  function renderLegendCheckboxes(
    legend: readonly LegendEntry[],
    hiddenKeys: readonly string[],
    onToggle: (key: string) => void
  ) {
    return (
      <div className={styles.legendCheckboxList}>
        {legend.map((entry) => {
          const visible = !hiddenKeys.includes(entry.key);
          return (
            <label key={entry.key} className={styles.legendCheckboxRow}>
              <input type="checkbox" checked={visible} onChange={() => onToggle(entry.key)} />
              {entry.width !== undefined ? (
                <WidthSwatch width={entry.width} dashed={entry.dashed} />
              ) : (
                <span className={styles.swatch} style={{ background: entry.color }} />
              )}
              {entry.label}
            </label>
          );
        })}
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      <section>
        <h2 className={styles.sectionTitle}>路面</h2>
        {!showRoad && <p className={styles.mutedHint}>「路面」をONにすると地図に表示されます</p>}
        {showRoad && regionZoomTooWide && (
          <p className={styles.zoomWarning}>表示範囲が広すぎます。ズームインしてください。</p>
        )}
        {showRoad && !regionZoomTooWide && (
          <>
            <p className={styles.legendCaption}>色：{roadColorAxis.label}</p>
            {renderLegendDisplay(roadColorAxis.legend, roadHiddenKeysByMode[ROAD_LINE_COLOR_AXIS_ID] ?? [])}
            <p className={styles.legendCaption}>太さ：{roadWidthAxis.label}</p>
            {renderLegendDisplay(roadWidthAxis.legend, roadHiddenKeysByMode[ROAD_LINE_WIDTH_AXIS_ID] ?? [])}
          </>
        )}
      </section>

      <section>
        <h2 className={styles.sectionTitle}>ルート</h2>
        {!hasDetail ? (
          <p className={styles.mutedHint}>ルートを生成・選択すると使えます</p>
        ) : (
          <>
            <div role="radiogroup" aria-label="ルートの色分け" className={styles.modeGroup}>
              {ROUTE_STYLE_MODES.map((mode) => (
                <button
                  key={mode.id}
                  type="button"
                  role="radio"
                  aria-checked={mode.id === routeStyleModeId}
                  onClick={() => handleRouteModeSelect(mode.id)}
                  className={
                    mode.id === routeStyleModeId ? `${styles.modeItem} ${styles.modeItemActive}` : styles.modeItem
                  }
                >
                  {mode.label}
                </button>
              ))}
            </div>
            {renderLegendCheckboxes(routeStyleMode.legend, hiddenRouteLegendKeys, onRouteLegendToggle)}
          </>
        )}
      </section>
    </div>
  );
}
