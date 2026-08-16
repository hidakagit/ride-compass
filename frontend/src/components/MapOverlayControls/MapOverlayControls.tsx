"use client";

import type { ReactElement } from "react";
import type { MapLayerId } from "@/components/Map/mapLayers";
import type { LegendEntry } from "@/components/Map/legendFilter";
import {
  AccidentIcon,
  DesignationIcon,
  ElevationIcon,
  RoadIcon,
  TrafficStressIcon,
  BicycleInfraIcon,
  StopPoiIcon,
  IntersectionIcon,
  RouteIcon,
} from "@/components/Map/icons";
import styles from "./MapOverlayControls.module.css";

/** サマリ行の先頭に添える色スウォッチ1グループぶん。表示中カテゴリの一覧なら
 * excluded: false、除外カテゴリの一覧ならexcluded: true（薄く見せて区別する）。
 * legendFilter.tsのsummarizeLegendFilterSwatchesが軸ごとに作る内訳と対応する。 */
export interface SummarySwatchGroup {
  excluded: boolean;
  entries: readonly LegendEntry[];
}

/** 地図上のチップ1つ分の表示状態。page.tsxがMAP_LAYERS（レイヤーカタログ）から組み立てる。 */
export interface OverlayLayerChip {
  id: MapLayerId;
  label: string;
  /** アイコンチップ下に出す短縮表記（未指定ならlabelを使う）。サマリ行は引き続きlabelを使う */
  chipLabel?: string;
  on: boolean;
  disabled?: boolean;
  /** チップのtitle（ONにすると何が出るか、disabledなら使えない理由） */
  title?: string;
  /** ONのレイヤーに適用中の条件・状態の1行要約（絞り込み・色分けモード・ズーム案内等）。
   * あればチップ行の下にサマリ行として表示する。無条件（既定のまま）ならnull。 */
  summary?: string | null;
  /** summaryの先頭に添える色スウォッチ（絞り込みで個別カテゴリを名指しできた場合のみ）。
   * 文字だけでは「何かに絞られている」ことしか分からず、地図上の色との対応が
   * 一目で分からないという実機フィードバックを受けて追加した。 */
  summarySwatches?: readonly SummarySwatchGroup[];
}

interface MapOverlayControlsProps {
  layers: readonly OverlayLayerChip[];
  onToggle: (id: MapLayerId, on: boolean) => void;
  /** サマリ行のタップ。page.tsxがサイドバーを開いて該当レイヤーの設定セクションへ誘導する */
  onSummaryClick: (id: MapLayerId) => void;
}

// レイヤーIDごとの自作アイコン（icons.tsx）。地図上は文字だけのチップだとスペースを
// 圧迫するという実機フィードバックを受け、小さいアイコン+短いラベルの縦並びへ変更した。
const LAYER_ICONS: Record<MapLayerId, (props: { size?: number }) => ReactElement> = {
  elevation: ElevationIcon,
  road: RoadIcon,
  trafficStress: TrafficStressIcon,
  bicycleInfra: BicycleInfraIcon,
  designation: DesignationIcon,
  stopPoi: StopPoiIcon,
  intersections: IntersectionIcon,
  accidents: AccidentIcon,
  route: RouteIcon,
};

// サマリ行の先頭に添える色スウォッチ。太さ・線種で地図に反映するカテゴリ
// （entry.widthを持つ、例:「道路の種類」）は色スウォッチのままだと「この色が地図に出る」
// という誤った期待を持たせてしまう（WidthSwatch.tsxと同じ理由）ため、太さバーで示す。
// 除外側（excluded）の一覧は薄く見せ、地図に出ている色（表示中側）と見分けられるようにする。
function renderSummarySwatches(groups: readonly SummarySwatchGroup[]) {
  return (
    <span className={styles.summarySwatches} aria-hidden="true">
      {groups.flatMap((group, groupIndex) =>
        group.entries.map((entry) => (
          <span
            key={`${groupIndex}-${entry.key}`}
            className={group.excluded ? `${styles.swatch} ${styles.swatchExcluded}` : styles.swatch}
          >
            {entry.width !== undefined ? (
              <span
                className={entry.dashed ? `${styles.swatchBar} ${styles.swatchBarDashed}` : styles.swatchBar}
                style={{ height: `${Math.max(2, entry.width)}px` }}
              />
            ) : (
              <span className={styles.swatchDot} style={{ background: entry.color }} />
            )}
          </span>
        ))
      )}
    </span>
  );
}

// 地図の上に重ねるのは「地図を見ながら頻繁に切り替える」ON/OFFチップと、ONのレイヤーに
// どんな条件が効いているかの1行サマリだけ。凡例・絞り込みの編集・色分けモードの選択など
// 「細かな設定」はすべてサイドバー（MapLayersPanel）で行う（地図上に設定UIを積むと地図が
// 狭くなる、というこれまでの方針を徹底し、以前ここにあった⚙ボタン＋設定ダイアログも
// サイドバーへ移した）。このコンポーネントはレイヤー固有の知識を持たない汎用の描画係で、
// レイヤーが増えてもここは変更不要（mapLayers.tsのコメント参照）。
export default function MapOverlayControls({ layers, onToggle, onSummaryClick }: MapOverlayControlsProps) {
  return (
    <div className={styles.wrapper}>
      <div className={styles.chipRow}>
        {layers.map((layer) => {
          const Icon = LAYER_ICONS[layer.id];
          const showSummary = layer.on && !layer.disabled && layer.summary;
          return (
            // チップとその条件サマリを1行にまとめる。以前はサマリをチップ列の下にまとめて
            // 縦に並べていたが、複数レイヤーがONのとき「どのチップの条件か」が離れて分かり
            // にくいという実機フィードバックを受け、該当チップの横へ移した。
            <div key={layer.id} className={styles.chipRowItem}>
              <button
                type="button"
                aria-pressed={layer.on && !layer.disabled}
                disabled={layer.disabled}
                title={layer.title}
                onClick={() => onToggle(layer.id, !layer.on)}
                className={
                  layer.on && !layer.disabled ? `${styles.iconChip} ${styles.iconChipActive}` : styles.iconChip
                }
              >
                <Icon />
                <span className={styles.iconLabel}>{layer.chipLabel ?? layer.label}</span>
              </button>
              {showSummary && (
                <button
                  type="button"
                  onClick={() => onSummaryClick(layer.id)}
                  className={styles.summaryButton}
                  title="タップするとサイドバーで設定を変更できます"
                >
                  <span className={styles.summaryLayerLabel}>{layer.label}:</span>
                  {layer.summarySwatches && layer.summarySwatches.length > 0 && (
                    renderSummarySwatches(layer.summarySwatches)
                  )}
                  <span className={styles.summaryText}>{layer.summary}</span>
                  <span aria-hidden="true" className={styles.summaryArrow}>
                    ▸
                  </span>
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
