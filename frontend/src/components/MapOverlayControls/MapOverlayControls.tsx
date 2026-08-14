"use client";

import { useRef, useState } from "react";
import { ROAD_FILTER_AXES, type RoadFilterAxisId } from "@/components/Map/roadFilterAxes";
import RoadFilterDialog from "./RoadFilterDialog";
import styles from "./MapOverlayControls.module.css";

interface MapOverlayControlsProps {
  showElevation: boolean;
  onShowElevationToggle: (on: boolean) => void;
  showRoad: boolean;
  onShowRoadToggle: (on: boolean) => void;
  /** 路面の2軸（路面の種類・道路の種類）それぞれの非表示カテゴリキー（page.tsxが軸別に保持）。
   * ここでは「保存済みの絞り込みがあるか」（チップのドット表示）にしか使わない。
   * 実際の絞り込み内容はサイドバー側（MapLegendPanel）で見せる。 */
  roadHiddenKeysByMode: Record<RoadFilterAxisId, readonly string[]>;
  /** RoadFilterDialog（別ウィンドウ）で「保存」を押したときにまとめて呼ばれる */
  onRoadSettingsSave: (hiddenKeysByMode: Record<RoadFilterAxisId, string[]>) => void;
  routeLayerOn: boolean;
  onRouteLayerToggle: (on: boolean) => void;
  hasDetail: boolean;
}

// 地図の上に重ねるのは「地図を見ながら頻繁に切り替える」トグルチップ（レイヤーのON/OFF）と、
// 路面の絞り込みを開く⚙ボタンだけにする。凡例・絞り込み内容の詳細・ルートの色分け選択は
// すべてサイドバー側のMapLegendPanelにまとめてあり、ここは「サイドバーの何を見ているか」の
// 最小限の紐づけ（チップの押下状態・絞り込み中を示す小さなドット）だけを担当する
// （地図上部に凡例や絞り込み文言まで積み上げると地図自体が狭くなり見づらいという指摘を受けて、
// 表示系の詳細情報は全てサイドバーへ移した）。
export default function MapOverlayControls({
  showElevation,
  onShowElevationToggle,
  showRoad,
  onShowRoadToggle,
  roadHiddenKeysByMode,
  onRoadSettingsSave,
  routeLayerOn,
  onRouteLayerToggle,
  hasDetail,
}: MapOverlayControlsProps) {
  const [roadDialogOpen, setRoadDialogOpen] = useState(false);
  const roadDialogButtonRef = useRef<HTMLButtonElement>(null);

  // 保存済みの絞り込みがあるかどうか（2軸合計）。チップ上のドット表示にのみ使う。
  const roadHiddenCount = ROAD_FILTER_AXES.reduce(
    (sum, axis) => sum + (roadHiddenKeysByMode[axis.id]?.length ?? 0),
    0
  );

  function handleRoadDialogClose() {
    setRoadDialogOpen(false);
    // ダイアログを開いた起点（⚙ボタン）へフォーカスを戻す（キーボード/スクリーンリーダー
    // 利用時に、閉じた後の操作起点を見失わないようにするため。page.tsxのモバイル
    // ドロワーclose処理と同じ考え方）
    roadDialogButtonRef.current?.focus();
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
          {/* ルート指標の「獲得標高」と紛らわしいため、地図レイヤー側は「標高図」と呼び分ける */}
          標高図
        </button>
        <div className={styles.chipGroup}>
          <button
            type="button"
            aria-pressed={showRoad}
            onClick={() => onShowRoadToggle(!showRoad)}
            className={showRoad ? styles.chipActive : styles.chip}
            title="道路を路面材質・種類で色分け表示（詳細はサイドバー参照）"
          >
            路面
            {/* 絞り込み中であることだけを示す最小限の印。実際の内容はサイドバーの凡例
                （dimmed表示）で分かるため、ここでは件数も文章も持たない。 */}
            {roadHiddenCount > 0 && <span className={styles.filterDot} aria-hidden="true" />}
          </button>
          <button
            ref={roadDialogButtonRef}
            type="button"
            aria-haspopup="dialog"
            aria-label={roadHiddenCount > 0 ? "路面の表示設定を開く（絞り込み中）" : "路面の表示設定を開く"}
            onClick={() => setRoadDialogOpen(true)}
            className={styles.modeMenuButton}
            title="路面の表示設定を開く（絞り込み）"
          >
            ⚙
          </button>
        </div>
        <button
          type="button"
          aria-pressed={routeLayerOn && hasDetail}
          disabled={!hasDetail}
          onClick={() => onRouteLayerToggle(!routeLayerOn)}
          className={routeLayerOn && hasDetail ? styles.chipActive : styles.chip}
          title={hasDetail ? "選択中ルート沿いの情報を色分け表示（詳細はサイドバー参照）" : "ルートを生成・選択すると使えます"}
        >
          ルート
        </button>
      </div>

      <RoadFilterDialog
        open={roadDialogOpen}
        onClose={handleRoadDialogClose}
        roadHiddenKeysByMode={roadHiddenKeysByMode}
        onSave={onRoadSettingsSave}
      />
    </div>
  );
}
