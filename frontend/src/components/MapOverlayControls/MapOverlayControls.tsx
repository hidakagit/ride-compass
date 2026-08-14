"use client";

import { useState } from "react";
import { ROAD_STYLE_MODES, getRoadStyleMode, type RoadStyleModeId } from "@/components/Map/roadStyleModes";
import { ROUTE_STYLE_MODES, getRouteStyleMode, type RouteStyleModeId } from "@/components/Map/routeStyleModes";
import type { LegendEntry } from "@/components/Map/legendFilter";
import styles from "./MapOverlayControls.module.css";

interface MapOverlayControlsProps {
  showElevation: boolean;
  onShowElevationToggle: (on: boolean) => void;
  showRoad: boolean;
  onShowRoadToggle: (on: boolean) => void;
  roadStyleModeId: RoadStyleModeId;
  onRoadStyleModeChange: (id: RoadStyleModeId) => void;
  /** 現在の路面モードで非表示にしている凡例カテゴリのキー（page.tsxがモード別に保持） */
  hiddenRoadLegendKeys: readonly string[];
  onRoadLegendToggle: (key: string) => void;
  routeLayerOn: boolean;
  onRouteLayerToggle: (on: boolean) => void;
  routeStyleModeId: RouteStyleModeId;
  onRouteStyleModeChange: (id: RouteStyleModeId) => void;
  hiddenRouteLegendKeys: readonly string[];
  onRouteLegendToggle: (key: string) => void;
  hasDetail: boolean;
  regionZoomTooWide: boolean;
}

// 地図レイヤーのON/OFFは「地図を見ながら頻繁に切り替える」操作のため、サイドバー内の
// チェックボックスではなく地図上のトグルチップとして重ね描きする（サイドバーを開閉せずに
// 操作できるようにする）。凡例・ズーム警告も対象レイヤーがONのときだけ地図上に出すことで、
// サイドバー側の常設の説明文を不要にしている。
//
// チップは2系統の「入れ物」で、どちらも本体タップ=ON/OFF・▾=色分けモード選択の同じ型:
// - 路面▾: 無方向・地域固定データ（roadStyleModes.ts）。いつでも使える
// - ルート▾: 有向・選択中ルート基準のデータ（routeStyleModes.ts）。ルートが決まって
//   初めて意味を持つため、未選択時は本体・▾とも非活性にする（非表示にしないのは、
//   「ルートを作るとここに情報が出る」という機能の存在に気づけるようにするため）
// 凡例は選択中モードの定義から生成し、各項目はタップでそのカテゴリの表示/非表示を
// 切り替えるフィルタとして機能する（「砂利道だけ見たい」「きつい登りだけ光らせたい」
// といった取捨選択のため）。
export default function MapOverlayControls({
  showElevation,
  onShowElevationToggle,
  showRoad,
  onShowRoadToggle,
  roadStyleModeId,
  onRoadStyleModeChange,
  hiddenRoadLegendKeys,
  onRoadLegendToggle,
  routeLayerOn,
  onRouteLayerToggle,
  routeStyleModeId,
  onRouteStyleModeChange,
  hiddenRouteLegendKeys,
  onRouteLegendToggle,
  hasDetail,
  regionZoomTooWide,
}: MapOverlayControlsProps) {
  // 同時に開くメニューは1つだけ（もう片方の▾を押したら開き直す）
  const [openMenu, setOpenMenu] = useState<"road" | "route" | null>(null);

  const roadStyleMode = getRoadStyleMode(roadStyleModeId);
  const routeStyleMode = getRouteStyleMode(routeStyleModeId);
  const showRoadLegend = showRoad && !regionZoomTooWide;
  const showRouteLegend = routeLayerOn && hasDetail;

  function handleRoadModeSelect(id: RoadStyleModeId) {
    onRoadStyleModeChange(id);
    setOpenMenu(null);
    // モードを選んだ＝その色分けを見たい意思表示なので、レイヤーがOFFならONにする
    // （「メニューで選んだのに地図に何も出ない」を防ぐ）
    if (!showRoad) onShowRoadToggle(true);
  }

  function handleRouteModeSelect(id: RouteStyleModeId) {
    onRouteStyleModeChange(id);
    setOpenMenu(null);
    if (!routeLayerOn) onRouteLayerToggle(true);
  }

  function renderLegend(
    legend: readonly LegendEntry[],
    hiddenKeys: readonly string[],
    onToggle: (key: string) => void
  ) {
    return (
      <div className={styles.legendRow}>
        {legend.map((entry) => {
          const visible = !hiddenKeys.includes(entry.key);
          return (
            <button
              key={entry.key}
              type="button"
              aria-pressed={visible}
              onClick={() => onToggle(entry.key)}
              className={visible ? styles.legendItemButton : `${styles.legendItemButton} ${styles.legendItemHidden}`}
              title={visible ? `${entry.label}を非表示にする` : `${entry.label}を表示する`}
            >
              <span className={styles.swatch} style={{ background: entry.color }} />
              {entry.label}
            </button>
          );
        })}
      </div>
    );
  }

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
        <div className={styles.chipGroup}>
          <button
            type="button"
            aria-pressed={showRoad}
            onClick={() => onShowRoadToggle(!showRoad)}
            className={showRoad ? styles.chipActive : styles.chip}
            title={`道路を色分けする（${roadStyleMode.label}）`}
          >
            路面
          </button>
          <button
            type="button"
            aria-label="路面の色分けを選択"
            aria-expanded={openMenu === "road"}
            onClick={() => setOpenMenu(openMenu === "road" ? null : "road")}
            className={openMenu === "road" ? `${styles.modeMenuButton} ${styles.modeMenuButtonOpen}` : styles.modeMenuButton}
            title="路面の色分けを選択"
          >
            ▾
          </button>
        </div>
        <div className={styles.chipGroup}>
          <button
            type="button"
            aria-pressed={routeLayerOn && hasDetail}
            disabled={!hasDetail}
            onClick={() => onRouteLayerToggle(!routeLayerOn)}
            className={routeLayerOn && hasDetail ? styles.chipActive : styles.chip}
            title={
              hasDetail ? `選択中ルート沿いの情報を色分けする（${routeStyleMode.label}）` : "ルートを生成・選択すると使えます"
            }
          >
            ルート
          </button>
          <button
            type="button"
            aria-label="ルートの色分けを選択"
            aria-expanded={openMenu === "route"}
            disabled={!hasDetail}
            onClick={() => setOpenMenu(openMenu === "route" ? null : "route")}
            className={
              openMenu === "route" ? `${styles.modeMenuButton} ${styles.modeMenuButtonOpen}` : styles.modeMenuButton
            }
            title={hasDetail ? "ルートの色分けを選択" : "ルートを生成・選択すると使えます"}
          >
            ▾
          </button>
        </div>
      </div>

      {openMenu === "road" && (
        <div className={styles.modeMenu} role="radiogroup" aria-label="路面の色分け">
          {ROAD_STYLE_MODES.map((mode) => (
            <button
              key={mode.id}
              type="button"
              role="radio"
              aria-checked={mode.id === roadStyleModeId}
              onClick={() => handleRoadModeSelect(mode.id)}
              className={mode.id === roadStyleModeId ? `${styles.modeItem} ${styles.modeItemActive}` : styles.modeItem}
            >
              {mode.label}
            </button>
          ))}
        </div>
      )}

      {openMenu === "route" && (
        <div className={styles.modeMenu} role="radiogroup" aria-label="ルートの色分け">
          {ROUTE_STYLE_MODES.map((mode) => (
            <button
              key={mode.id}
              type="button"
              role="radio"
              aria-checked={mode.id === routeStyleModeId}
              onClick={() => handleRouteModeSelect(mode.id)}
              className={mode.id === routeStyleModeId ? `${styles.modeItem} ${styles.modeItemActive}` : styles.modeItem}
            >
              {mode.label}
            </button>
          ))}
        </div>
      )}

      {showRoad && regionZoomTooWide && (
        <p className={styles.zoomWarning}>表示範囲が広すぎます。ズームインしてください。</p>
      )}

      {showRoadLegend && renderLegend(roadStyleMode.legend, hiddenRoadLegendKeys, onRoadLegendToggle)}

      {showRouteLegend && renderLegend(routeStyleMode.legend, hiddenRouteLegendKeys, onRouteLegendToggle)}
    </div>
  );
}
