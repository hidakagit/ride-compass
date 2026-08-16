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
  type RoadFilterAxis,
  type RoadFilterAxisId,
} from "@/components/Map/roadFilterAxes";
import { ROUTE_STYLE_MODES, getRouteStyleMode, type RouteStyleModeId } from "@/components/Map/routeStyleModes";
import type { LegendEntry } from "@/components/Map/legendFilter";
import { STATIC_FILTER_AXES, type StaticFilterAxis, type StaticFilterAxisId } from "@/components/Map/staticAttributeLayers";
import LayerChip from "@/components/Map/LayerChip";
import WidthSwatch from "./WidthSwatch";
import styles from "./MapLayersPanel.module.css";

interface MapLayersPanelProps {
  layerVisibility: MapLayerVisibility;
  onLayerToggle: (id: MapLayerId, on: boolean) => void;
  /** 道路情報の2軸（路面の種類・道路の種類）それぞれの非表示カテゴリキー */
  roadHiddenKeysByMode: Record<RoadFilterAxisId, readonly string[]>;
  /** 凡例チェックの操作（即時反映。連続タップの再描画はpage.tsx側のデバウンスが吸収） */
  onRoadLegendToggle: (axisId: RoadFilterAxisId, key: string) => void;
  /** 「すべて表示/すべて隠す」の一括操作（非表示キー全体の置き換え） */
  onRoadAxisSetHidden: (axisId: RoadFilterAxisId, hiddenKeys: string[]) => void;
  /** 交通ストレス・自転車インフラ・停止要因POI・交差点密度・事故（当事者/重大度）の絞り込み軸
   * （改善計画T63、STATIC_FILTER_AXES参照）。事故のみ2軸を持ち、他は1軸。 */
  staticFilterHiddenKeysByAxis: Record<StaticFilterAxisId, readonly string[]>;
  onStaticFilterLegendToggle: (axisId: StaticFilterAxisId, key: string) => void;
  onStaticFilterAxisSetHidden: (axisId: StaticFilterAxisId, hiddenKeys: string[]) => void;
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
  onRoadLegendToggle,
  onRoadAxisSetHidden,
  staticFilterHiddenKeysByAxis,
  onStaticFilterLegendToggle,
  onStaticFilterAxisSetHidden,
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

  // 道路情報の絞り込みは即時反映（T31。旧「下書き→適用」はRoadFilterEditorごと廃止し、
  // ルート凡例のチェックと同じ方式へ統一した）。OFF中に操作したら、色分けモード選択と
  // 同じくレイヤーを自動でONにする（設定したのに何も起きない状態を作らない）。
  function handleRoadLegendToggle(axisId: RoadFilterAxisId, key: string) {
    onRoadLegendToggle(axisId, key);
    if (!layerVisibility.road) onLayerToggle("road", true);
  }

  function handleRoadAxisSetHidden(axisId: RoadFilterAxisId, hiddenKeys: string[]) {
    onRoadAxisSetHidden(axisId, hiddenKeys);
    if (!layerVisibility.road) onLayerToggle("road", true);
  }

  // 改善計画T63: 道路情報以外の5レイヤー（交通ストレス・自転車インフラ・停止要因POI・
  // 交差点密度・事故）の絞り込み。道路情報と同じ「即時反映＋操作したレイヤーを自動でON」の
  // 挙動を、STATIC_FILTER_AXESのlayerIdを使って軸非依存に実装する（layerIdは呼び出し側の
  // renderSectionBodyケースが自身のlayer.idとして渡す）。
  function handleStaticFilterLegendToggle(layerId: MapLayerId, axisId: StaticFilterAxisId, key: string) {
    onStaticFilterLegendToggle(axisId, key);
    if (!layerVisibility[layerId]) onLayerToggle(layerId, true);
  }

  function handleStaticFilterAxisSetHidden(layerId: MapLayerId, axisId: StaticFilterAxisId, hiddenKeys: string[]) {
    onStaticFilterAxisSetHidden(axisId, hiddenKeys);
    if (!layerVisibility[layerId]) onLayerToggle(layerId, true);
  }

  // 凡例そのものをチェックボックスにして、参照表示と絞り込み操作を1つのリストで兼ねる
  // （即時反映。ルート凡例と道路情報の2軸が共通で使う、T31で方式統一）。
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

  // 道路情報の1軸分（見出し＋一括操作＋凡例チェックボックス）。visualはこの軸が地図の
  // どの視覚チャンネル（色/太さ）に反映されるかの表記。
  function renderRoadAxis(axis: RoadFilterAxis, visual: string) {
    const hiddenKeys = roadHiddenKeysByMode[axis.id] ?? [];
    const allKeys = axis.legend.map((entry) => entry.key);
    return (
      <div>
        <div className={styles.axisHeader}>
          <p className={styles.legendCaption}>
            {visual}：{axis.label}
          </p>
          {/* 複数カテゴリの絞り込みはチェックの繰り返しになりがちなため、起点を揃える
              一括ボタンでタップ数を減らす（旧「下書き→適用」廃止の代替、T31） */}
          <div className={styles.bulkRow}>
            <button type="button" className={styles.bulkButton} onClick={() => handleRoadAxisSetHidden(axis.id, [])}>
              すべて表示
            </button>
            <button
              type="button"
              className={styles.bulkButton}
              onClick={() => handleRoadAxisSetHidden(axis.id, allKeys)}
            >
              すべて隠す
            </button>
          </div>
        </div>
        {renderLegendCheckboxes(axis.legend, hiddenKeys, (key) => handleRoadLegendToggle(axis.id, key))}
      </div>
    );
  }

  // 改善計画T63: 道路情報以外の絞り込み可能レイヤーの1軸分（一括操作＋凡例チェックボックス）。
  // axis.labelがある場合のみ見出しを出す（1レイヤー1軸なら外側のレイヤー見出しで十分なため、
  // 事故のように1レイヤーに複数軸を持つ場合だけ「当事者」「重大度」で区別する）。
  function renderStaticFilterAxis(axis: StaticFilterAxis) {
    const hiddenKeys = staticFilterHiddenKeysByAxis[axis.axisId] ?? [];
    const allKeys = axis.legend.map((entry) => entry.key);
    return (
      <div key={axis.axisId}>
        <div className={styles.axisHeader}>
          {axis.label && <p className={styles.legendCaption}>{axis.label}</p>}
          <div className={styles.bulkRow}>
            <button
              type="button"
              className={styles.bulkButton}
              onClick={() => handleStaticFilterAxisSetHidden(axis.layerId, axis.axisId, [])}
            >
              すべて表示
            </button>
            <button
              type="button"
              className={styles.bulkButton}
              onClick={() => handleStaticFilterAxisSetHidden(axis.layerId, axis.axisId, allKeys)}
            >
              すべて隠す
            </button>
          </div>
        </div>
        {renderLegendCheckboxes(axis.legend, hiddenKeys, (key) =>
          handleStaticFilterLegendToggle(axis.layerId, axis.axisId, key),
        )}
      </div>
    );
  }

  // layer.idの絞り込み軸一覧（STATIC_FILTER_AXES参照、事故のみ2件）。
  function staticFilterAxesFor(layerId: MapLayerId): readonly StaticFilterAxis[] {
    return STATIC_FILTER_AXES.filter((axis) => axis.layerId === layerId);
  }

  // 道路情報と同じ「OFF中でも絞り込み操作でき、操作すると自動でONになる」ことの案内文。
  function renderOffHint(layerId: MapLayerId) {
    return (
      !layerVisibility[layerId] && (
        <p className={styles.mutedHint}>表示はOFFです（絞り込みを操作すると自動でONになります）</p>
      )
    );
  }

  function renderSectionBody(layer: MapLayerDescriptor) {
    switch (layer.id) {
      case "elevation":
        // 設定項目が無いレイヤーは説明文のみ（将来、不透明度等の設定を足す場所）
        return <p className={styles.mutedHint}>{layer.description}</p>;
      case "trafficStress":
        // 改善計画T63で凡例チェックボックス＝絞り込み操作へ変更（道路情報と同じ方式）。
        // 判定基準が不明という実機フィードバック（モバイル実機フィードバック対応T39）を受け、
        // backend/app/domain/traffic.py: traffic_stress_levelの要約を明記する。
        return (
          <>
            <p className={styles.mutedHint}>
              道路の種別を基準に、自転車専用帯・レーンの有無、制限速度、車線数で補正した
              1（快適）〜4（ストレス大）の目安です。実際の交通量そのものは加味していません。
            </p>
            {renderOffHint("trafficStress")}
            {staticFilterAxesFor("trafficStress").map(renderStaticFilterAxis)}
          </>
        );
      case "bicycleInfra":
        // 「道路情報（路面）」との違いが分からないという実機フィードバック（同T40）を受け、
        // 両者が独立した軸であることを明記する。
        return (
          <>
            <p className={styles.mutedHint}>
              自転車が走る帯の構造（専用道・レーン・車道混在など）を表します。道路情報レイヤーの
              路面の種類（アスファルト/砂利など、舗装の物理的な状態）とは別の軸で、
              組み合わせて確認できます。
            </p>
            {renderOffHint("bicycleInfra")}
            {staticFilterAxesFor("bicycleInfra").map(renderStaticFilterAxis)}
          </>
        );
      case "stopPoi":
        return (
          <>
            <p className={styles.mutedHint}>
              信号・横断歩道・一時停止・踏切の位置です。評価の「停止密度」軸が近傍のこれらを
              数えて算出しているものを、種別ごとの色分けで直接確認できます。
            </p>
            {renderOffHint("stopPoi")}
            {staticFilterAxesFor("stopPoi").map(renderStaticFilterAxis)}
          </>
        );
      case "intersections":
        // 改善計画T63: degree（接続路の本数）を3段階に束ねた絞り込みへ変更。「主要な交差路
        // だけ表示」で密度の高い箇所を判断しやすくする（詳細はstaticAttributeLayers.ts参照）。
        return (
          <>
            <p className={styles.mutedHint}>
              接続する道路が3本以上ある交差点です。接続数が多いほど円が大きくなります。
              評価の「交差点密度」軸が近傍のこれらを数えて算出しています。
            </p>
            {renderOffHint("intersections")}
            {staticFilterAxesFor("intersections").map(renderStaticFilterAxis)}
          </>
        );
      case "accidents":
        // 改善計画T63: 当事者（自転車関連/その他）に加え、重大度（死亡事故か否か）を独立した
        // 第2軸として絞り込み可能にした（道路情報の路面の種類×道路の種類と同じAND絞り込み）。
        return (
          <>
            <p className={styles.mutedHint}>
              警察庁が公開する交通事故統計オープンデータ（本票、関東7都県・2022〜2024年）の
              発生地点です。死亡事故は円を大きく表示します。2019〜2021年は本票のCSV形式が
              異なるため未対応です。
            </p>
            {renderOffHint("accidents")}
            {staticFilterAxesFor("accidents").map(renderStaticFilterAxis)}
          </>
        );
      case "road":
        // 2軸とも凡例チェックボックス＝絞り込み操作（参照表示と操作を1つのリストで兼ねる、
        // ルート凡例と同じ方式）。OFF中でも操作でき、操作すると自動でONになる。
        return (
          <>
            {!layerVisibility.road && (
              <p className={styles.mutedHint}>表示はOFFです（絞り込みを操作すると自動でONになります）</p>
            )}
            {layerVisibility.road && regionZoomTooWide && (
              <p className={styles.zoomWarning}>表示範囲が広すぎます。ズームインしてください。</p>
            )}
            {renderRoadAxis(roadColorAxis, "色")}
            {renderRoadAxis(roadWidthAxis, "太さ")}
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
              // 要素ごとに折りたたむ階層メニュー（モバイル実機フィードバック対応T38。
              // 以前は5レイヤー分の設定が常時全展開でスクロールが長かった）。デフォルト全閉。
              // domIdはdetails自体に振る（地図上の条件サマリからの誘導、page.tsxの
              // handleLayerSummaryClickがこのidで要素を取得しopen=trueにしてから
              // スクロール・フォーカスする）。
              <details key={layer.id} id={domId} className={styles.layerSection}>
                <summary className={styles.layerHeader}>
                  {/* tabIndex=-1: 地図上の条件サマリから飛んできたときにJSからfocus()するため
                      （MapOverlayControls→page.tsxのスクロール誘導。クリックでは選択されない） */}
                  <h3 id={`${domId}-title`} tabIndex={-1} className={styles.layerTitle}>
                    <span aria-hidden="true" className={styles.chevron} />
                    {layer.label}
                  </h3>
                  {/* ON/OFFは地図上のチップと同一部品（LayerChip）。見た目が同じ＝同じ操作だと
                      伝えるため、role=switchのチェックボックスからチップへ統一した（T30）。
                      summary内のクリックはdetails開閉のデフォルト動作を伴うため、チップ操作が
                      同時に開閉してしまわないようpreventDefault/stopPropagationする。 */}
                  <LayerChip
                    label="表示"
                    ariaLabel={`${layer.label}レイヤーを表示`}
                    on={layerVisibility[layer.id]}
                    disabled={disabled}
                    title={disabled ? "ルートを生成・選択すると使えます" : undefined}
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      onLayerToggle(layer.id, !layerVisibility[layer.id]);
                    }}
                  />
                </summary>
                <div className={styles.layerBody}>{renderSectionBody(layer)}</div>
              </details>
            );
          })}
        </div>
      ))}
    </div>
  );
}
