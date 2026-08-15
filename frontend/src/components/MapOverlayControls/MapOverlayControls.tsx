"use client";

import type { ReactElement, ReactNode } from "react";
import type { MapLayerId } from "@/components/Map/mapLayers";
import { ElevationIcon, RoadIcon, TrafficStressIcon, BicycleInfraIcon, RouteIcon } from "@/components/Map/icons";
import styles from "./MapOverlayControls.module.css";

/** 地図上のチップ1つ分の表示状態。page.tsxがMAP_LAYERS（レイヤーカタログ）から組み立てる。 */
export interface OverlayLayerChip {
  id: MapLayerId;
  label: string;
  on: boolean;
  disabled?: boolean;
  /** チップのtitle（ONにすると何が出るか、disabledなら使えない理由） */
  title?: string;
  /** ONのレイヤーに適用中の条件・状態の1行要約（絞り込み・色分けモード・ズーム案内等）。
   * あればチップ行の下にサマリ行として表示する。無条件（既定のまま）ならnull。 */
  summary?: string | null;
}

/** レイヤー一覧の下に区切り線付きで足す追加ボタン（デバッグログ起動等）。地図上の
 * アイコン列を1本にまとめたいという要望向けの汎用スロットで、このコンポーネント自体は
 * 何のボタンかを知らない（レイヤー固有の知識を持たない、という既存方針を維持）。 */
export interface OverlayTrailingButton {
  icon: ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
  ariaLabel: string;
  title?: string;
}

interface MapOverlayControlsProps {
  layers: readonly OverlayLayerChip[];
  onToggle: (id: MapLayerId, on: boolean) => void;
  /** サマリ行のタップ。page.tsxがサイドバーを開いて該当レイヤーの設定セクションへ誘導する */
  onSummaryClick: (id: MapLayerId) => void;
  trailingButton?: OverlayTrailingButton;
}

// レイヤーIDごとの自作アイコン（icons.tsx）。地図上は文字だけのチップだとスペースを
// 圧迫するという実機フィードバックを受け、小さいアイコン+短いラベルの縦並びへ変更した。
const LAYER_ICONS: Record<MapLayerId, (props: { size?: number }) => ReactElement> = {
  elevation: ElevationIcon,
  road: RoadIcon,
  trafficStress: TrafficStressIcon,
  bicycleInfra: BicycleInfraIcon,
  route: RouteIcon,
};

// 地図の上に重ねるのは「地図を見ながら頻繁に切り替える」ON/OFFチップと、ONのレイヤーに
// どんな条件が効いているかの1行サマリだけ。凡例・絞り込みの編集・色分けモードの選択など
// 「細かな設定」はすべてサイドバー（MapLayersPanel）で行う（地図上に設定UIを積むと地図が
// 狭くなる、というこれまでの方針を徹底し、以前ここにあった⚙ボタン＋設定ダイアログも
// サイドバーへ移した）。このコンポーネントはレイヤー固有の知識を持たない汎用の描画係で、
// レイヤーが増えてもここは変更不要（mapLayers.tsのコメント参照）。
export default function MapOverlayControls({ layers, onToggle, onSummaryClick, trailingButton }: MapOverlayControlsProps) {
  const summaries = layers.filter((layer) => layer.on && !layer.disabled && layer.summary);

  return (
    <div className={styles.wrapper}>
      <div className={styles.chipRow}>
        {layers.map((layer) => {
          const Icon = LAYER_ICONS[layer.id];
          return (
            <button
              key={layer.id}
              type="button"
              aria-pressed={layer.on && !layer.disabled}
              disabled={layer.disabled}
              title={layer.title}
              onClick={() => onToggle(layer.id, !layer.on)}
              className={layer.on && !layer.disabled ? `${styles.iconChip} ${styles.iconChipActive}` : styles.iconChip}
            >
              <Icon />
              <span className={styles.iconLabel}>{layer.label}</span>
            </button>
          );
        })}

        {trailingButton && (
          <>
            <div className={styles.trailingDivider} aria-hidden="true" />
            <button
              type="button"
              aria-pressed={trailingButton.active}
              aria-label={trailingButton.ariaLabel}
              title={trailingButton.title}
              onClick={trailingButton.onClick}
              className={trailingButton.active ? `${styles.iconChip} ${styles.iconChipActive}` : styles.iconChip}
            >
              {trailingButton.icon}
              <span className={styles.iconLabel}>{trailingButton.label}</span>
            </button>
          </>
        )}
      </div>

      {summaries.map((layer) => (
        <button
          key={layer.id}
          type="button"
          onClick={() => onSummaryClick(layer.id)}
          className={styles.summaryButton}
          title="タップするとサイドバーで設定を変更できます"
        >
          <span className={styles.summaryLayerLabel}>{layer.label}:</span> {layer.summary}
          <span aria-hidden="true" className={styles.summaryArrow}>
            ▸
          </span>
        </button>
      ))}
    </div>
  );
}
