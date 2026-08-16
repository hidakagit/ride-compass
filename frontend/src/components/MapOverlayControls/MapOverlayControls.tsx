"use client";

import { useState, type ReactElement } from "react";
import type { MapLayerId } from "@/components/Map/mapLayers";
import type { LegendEntry, LegendFilterSummaryAxis } from "@/components/Map/legendFilter";
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

/** 地図上のチップ1つ分の表示状態。page.tsxがMAP_LAYERS（レイヤーカタログ）から組み立てる。 */
export interface OverlayLayerChip {
  id: MapLayerId;
  label: string;
  /** アイコンチップ下に出す短縮表記（未指定ならlabelを使う） */
  chipLabel?: string;
  on: boolean;
  disabled?: boolean;
  /** チップのtitle（ONにすると何が出るか、disabledなら使えない理由） */
  title?: string;
  /** ▶を開いたときに出す案内文。legendDetailsが無い（描く凡例が無い）ときの
   * 唯一の表示内容として使う（例:「ズームインすると表示されます」）。legendDetailsが
   * あるときは軸ごとの内訳だけで十分なため使わない（レイヤー名や絞り込みの1行要約を
   * 重ねて出すと、▶を押した本人には自明な情報の繰り返しになるという実機フィードバックを
   * 受けて廃止した）。 */
  summary?: string | null;
  /** ▶を開いたときに出す、軸ごとの全カテゴリ内訳（表示中/非表示のいずれも含む）。
   * 絞り込み中かどうかに関わらず、レイヤーがONで凡例を持つならこれだけで開閉できる
   * （以前は絞り込み中のレイヤーしか▶が出なかったが、無条件のレイヤーでも凡例を
   * 確認したいという実機フィードバックを受け、legendDetailsの有無だけで判定するよう変更）。 */
  legendDetails?: readonly LegendFilterSummaryAxis[];
}

interface MapOverlayControlsProps {
  layers: readonly OverlayLayerChip[];
  onToggle: (id: MapLayerId, on: boolean) => void;
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

// 凡例1カテゴリぶんのスウォッチ。太さ・線種で地図に反映するカテゴリ（entry.widthを持つ、
// 例:「道路の種類」）は色スウォッチのままだと「この色が地図に出る」という誤った期待を
// 持たせてしまう（WidthSwatch.tsxと同じ理由）ため、太さバーで示す。
function renderLegendSwatch(entry: LegendEntry) {
  return entry.width !== undefined ? (
    <span
      className={entry.dashed ? `${styles.detailSwatchBar} ${styles.detailSwatchBarDashed}` : styles.detailSwatchBar}
      style={{ height: `${Math.max(2, entry.width)}px` }}
    />
  ) : (
    <span className={styles.detailSwatchDot} style={{ background: entry.color }} />
  );
}

// ▶を開いたときの内訳パネル。軸に属する全カテゴリを表示中/非表示の別なく並べ、
// 非表示分だけ薄く見せる（「これだけで何が起きているか分かる」ことを優先する）。
function renderLegendDetails(axes: readonly LegendFilterSummaryAxis[]) {
  return (
    <div className={styles.detailBody}>
      {axes.map((axis, axisIndex) => (
        <div key={axis.label || axisIndex} className={styles.detailAxis}>
          {axis.label && <div className={styles.detailAxisLabel}>{axis.label}</div>}
          <ul className={styles.detailList}>
            {axis.legend.map((entry) => {
              const hidden = axis.hiddenKeys.includes(entry.key);
              return (
                <li key={entry.key} className={hidden ? `${styles.detailRow} ${styles.detailRowHidden}` : styles.detailRow}>
                  {renderLegendSwatch(entry)}
                  <span className={styles.detailRowLabel}>{entry.label}</span>
                  {hidden && <span className={styles.detailHiddenTag}>非表示</span>}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

// 地図の上に重ねるのは「地図を見ながら頻繁に切り替える」ON/OFFチップと、▶で開く凡例
// だけ。絞り込みの編集・色分けモードの選択など「変更を伴う設定」はすべてサイドバー
// （MapLayersPanel）で行う（地図上の▶はあくまで確認用で、以前あった「タップでサイドバーへ
// ジャンプ」動線はここが確認専用になったことで廃止した）。このコンポーネントはレイヤー
// 固有の知識を持たない汎用の描画係で、レイヤーが増えてもここは変更不要（mapLayers.tsの
// コメント参照）。
export default function MapOverlayControls({ layers, onToggle }: MapOverlayControlsProps) {
  // 凡例を常時表示すると地図の視界を圧迫するという実機フィードバックを受け、既定は
  // 非表示にし、チップ横の▶を押したレイヤーのぶんだけ薄いポップオーバーで出す。
  // 複数レイヤーを同時に開いておきたい場合もあるため、開閉はレイヤーIDのSetで個別管理する。
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<MapLayerId>>(new Set());

  const toggleExpanded = (id: MapLayerId) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <div className={styles.wrapper}>
      <div className={styles.chipRow}>
        {layers.map((layer) => {
          const Icon = LAYER_ICONS[layer.id];
          const hasLegendDetails = Boolean(layer.legendDetails && layer.legendDetails.length > 0);
          const canExpand = layer.on && !layer.disabled && (hasLegendDetails || Boolean(layer.summary));
          const isExpanded = canExpand && expandedIds.has(layer.id);
          return (
            // ▶を開いても後続レイヤーの位置がずれないよう、内訳パネルはこの行の中で
            // position: absoluteにして通常のフロー（chipRowの縦積み）から外す
            // （実機フィードバック「▶展開で以降のアイコンまでずれる」への対応）。
            <div
              key={layer.id}
              className={isExpanded ? `${styles.iconWithToggle} ${styles.iconWithToggleExpanded}` : styles.iconWithToggle}
            >
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
              {canExpand && (
                <button
                  type="button"
                  onClick={() => toggleExpanded(layer.id)}
                  aria-expanded={isExpanded}
                  aria-label={`${layer.label}の凡例を${isExpanded ? "隠す" : "表示"}`}
                  title="凡例を表示"
                  className={isExpanded ? `${styles.expandToggle} ${styles.expandToggleActive}` : styles.expandToggle}
                >
                  <span
                    aria-hidden="true"
                    className={isExpanded ? `${styles.expandArrow} ${styles.expandArrowOpen}` : styles.expandArrow}
                  >
                    ▶
                  </span>
                </button>
              )}
              {isExpanded && (
                <div className={styles.detailPanel}>
                  {layer.legendDetails && layer.legendDetails.length > 0 ? (
                    renderLegendDetails(layer.legendDetails)
                  ) : (
                    <p className={styles.detailNotice}>{layer.summary}</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
