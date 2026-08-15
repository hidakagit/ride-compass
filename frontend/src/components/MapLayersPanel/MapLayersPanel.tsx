"use client";

import {
  MAP_LAYERS,
  layerSectionDomId,
  type MapLayerDescriptor,
  type MapLayerId,
  type MapLayerKind,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import {
  ROAD_LINE_COLOR_AXIS_ID,
  ROAD_LINE_WIDTH_AXIS_ID,
  getRoadFilterAxis,
  type RoadFilterAxisId,
} from "@/components/Map/roadFilterAxes";
import { ROUTE_STYLE_MODES, getRouteStyleMode, type RouteStyleModeId } from "@/components/Map/routeStyleModes";
import type { LegendEntry } from "@/components/Map/legendFilter";
import { BICYCLE_INFRA_LEGEND, TRAFFIC_STRESS_LEGEND } from "@/components/Map/staticAttributeLayers";
import LayerChip from "@/components/Map/LayerChip";
import RoadFilterEditor from "./RoadFilterEditor";
import WidthSwatch from "./WidthSwatch";
import styles from "./MapLayersPanel.module.css";

interface MapLayersPanelProps {
  layerVisibility: MapLayerVisibility;
  onLayerToggle: (id: MapLayerId, on: boolean) => void;
  /** 路面の2軸（路面の種類・道路の種類）それぞれの非表示カテゴリキー */
  roadHiddenKeysByMode: Record<RoadFilterAxisId, readonly string[]>;
  /** 絞り込み編集（RoadFilterEditor）で「適用」を押したときにまとめて呼ばれる */
  onRoadFilterApply: (hiddenKeysByMode: Record<RoadFilterAxisId, string[]>) => void;
  regionZoomTooWide: boolean;
  routeStyleModeId: RouteStyleModeId;
  onRouteStyleModeChange: (id: RouteStyleModeId) => void;
  hiddenRouteLegendKeys: readonly string[];
  onRouteLegendToggle: (key: string) => void;
  hasDetail: boolean;
  /** ルート未生成時の案内から「ルートを作る」セクションへ誘導する（page.tsxがスクロール） */
  onGoToGenerate?: () => void;
}

// サイドバーのグループ見出し。内部的にはデータの性質（static/dynamic、mapLayers.tsのkind）で
// 分かれているが、見出しは「変わらないデータ」のような実装都合の表現を避け、ユーザーから見た
// 役割（地図に重ねるか、生成したルートの見え方か）で言い表す（T30）。
const GROUP_HEADINGS: Record<MapLayerKind, string> = {
  static: "地図に重ねる情報",
  dynamic: "生成したルートの色分け",
};

// 地図レイヤーの「細かな設定」をすべて集約するサイドバー内パネル。
// レイヤーごとに1セクション（見出し＋表示スイッチ＋凡例・絞り込み等の設定）を持ち、
// セクションの枠組みはMAP_LAYERS（レイヤーカタログ）の列挙で描画する。地図の上
// （MapOverlayControls）にはON/OFFチップと条件サマリだけを残し、サマリのタップで
// このパネルの該当セクションへスクロールしてくる（layerSectionDomId参照）。
// 以前のMapLegendPanel（凡例の参照表示のみ）とRoadFilterDialog（地図上の⚙から開く
// 絞り込みモーダル）を統合したもので、レイヤーの設定はこのパネルの中だけで完結する。
export default function MapLayersPanel({
  layerVisibility,
  onLayerToggle,
  roadHiddenKeysByMode,
  onRoadFilterApply,
  regionZoomTooWide,
  routeStyleModeId,
  onRouteStyleModeChange,
  hiddenRouteLegendKeys,
  onRouteLegendToggle,
  hasDetail,
  onGoToGenerate,
}: MapLayersPanelProps) {
  const roadColorAxis = getRoadFilterAxis(ROAD_LINE_COLOR_AXIS_ID);
  const roadWidthAxis = getRoadFilterAxis(ROAD_LINE_WIDTH_AXIS_ID);
  const routeStyleMode = getRouteStyleMode(routeStyleModeId);

  function handleRouteModeSelect(id: RouteStyleModeId) {
    onRouteStyleModeChange(id);
    if (!layerVisibility.route) onLayerToggle("route", true);
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
  // チェックボックスにして参照表示と絞り込み操作を1つのリストで兼ねる（即時反映。
  // 路面側の「下書き→適用」と使い分ける理由はRoadFilterEditorのコメント参照）。
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

  function renderSectionBody(layer: MapLayerDescriptor) {
    switch (layer.id) {
      case "elevation":
        // 設定項目が無いレイヤーは説明文のみ（将来、不透明度等の設定を足す場所）
        return <p className={styles.mutedHint}>{layer.description}</p>;
      case "trafficStress":
        // P0時点では絞り込みUIは持たず色分け表示のみ（staticAttributeLayers.ts参照）。
        // 色分けは常時全カテゴリ表示のため、レイヤーOFF時も凡例だけ参考表示する。
        return renderLegendDisplay(TRAFFIC_STRESS_LEGEND, []);
      case "bicycleInfra":
        return renderLegendDisplay(BICYCLE_INFRA_LEGEND, []);
      case "road":
        return (
          <>
            {!layerVisibility.road && <p className={styles.mutedHint}>表示をONにすると地図に出ます</p>}
            {layerVisibility.road && regionZoomTooWide && (
              <p className={styles.zoomWarning}>表示範囲が広すぎます。ズームインしてください。</p>
            )}
            {layerVisibility.road && !regionZoomTooWide && (
              <>
                <p className={styles.legendCaption}>色：{roadColorAxis.label}</p>
                {renderLegendDisplay(roadColorAxis.legend, roadHiddenKeysByMode[ROAD_LINE_COLOR_AXIS_ID] ?? [])}
                <p className={styles.legendCaption}>太さ：{roadWidthAxis.label}</p>
                {renderLegendDisplay(roadWidthAxis.legend, roadHiddenKeysByMode[ROAD_LINE_WIDTH_AXIS_ID] ?? [])}
              </>
            )}
            {/* 絞り込み編集はOFF中でも開ける（適用すると自動でONになる。旧⚙ダイアログと同じ挙動） */}
            <RoadFilterEditor savedHiddenKeys={roadHiddenKeysByMode} onApply={onRoadFilterApply} />
          </>
        );
      case "route":
        if (!hasDetail) {
          // 生成前は使えない理由だけでなく、次の一歩（ルートを作るセクション）へ誘導する
          // （地図上の条件サマリ→設定セクションへの誘導と同じパターンの逆方向、T30）
          return (
            <p className={styles.mutedHint}>
              ルートを生成・選択すると使えます。
              {onGoToGenerate && (
                <button type="button" onClick={onGoToGenerate} className={styles.inlineLink}>
                  「ルートを作る」へ
                </button>
              )}
            </p>
          );
        }
        return (
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
        );
    }
  }

  // ルートレイヤーはルート未選択時に使えない（スイッチも非活性）。他レイヤーは常に使える。
  function isLayerDisabled(id: MapLayerId): boolean {
    return id === "route" && !hasDetail;
  }

  const kinds: MapLayerKind[] = ["static", "dynamic"];

  return (
    <div className={styles.panel}>
      {kinds.map((kind) => (
        <div key={kind} className={styles.group}>
          <h2 className={styles.groupTitle}>{GROUP_HEADINGS[kind]}</h2>
          {MAP_LAYERS.filter((layer) => layer.kind === kind).map((layer) => {
            const disabled = isLayerDisabled(layer.id);
            const domId = layerSectionDomId(layer.id);
            return (
              <section key={layer.id} id={domId} className={styles.layerSection}>
                <div className={styles.layerHeader}>
                  {/* tabIndex=-1: 地図上の条件サマリから飛んできたときにJSからfocus()するため
                      （MapOverlayControls→page.tsxのスクロール誘導。クリックでは選択されない） */}
                  <h3 id={`${domId}-title`} tabIndex={-1} className={styles.layerTitle}>
                    {layer.label}
                  </h3>
                  {/* ON/OFFは地図上のチップと同一部品（LayerChip）。見た目が同じ＝同じ操作だと
                      伝えるため、role=switchのチェックボックスからチップへ統一した（T30） */}
                  <LayerChip
                    label="表示"
                    ariaLabel={`${layer.label}レイヤーを表示`}
                    on={layerVisibility[layer.id]}
                    disabled={disabled}
                    title={disabled ? "ルートを生成・選択すると使えます" : undefined}
                    onClick={() => onLayerToggle(layer.id, !layerVisibility[layer.id])}
                  />
                </div>
                {renderSectionBody(layer)}
              </section>
            );
          })}
        </div>
      ))}
    </div>
  );
}
