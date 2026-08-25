"use client";

import { useState } from "react";
import {
  LAYER_DATA_STATUS_LABELS,
  MAP_LAYER_CATEGORY_ORDER,
  MAP_LAYER_DATA_NATURE_LABELS,
  MAP_LAYER_DATA_NATURE_ORDER,
  layerSectionDomId,
  type LayerDataStatus,
  type LayerDataStatusByLayer,
  type MapLayerDataNature,
  type MapLayerDescriptor,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import {
  ROAD_LINE_COLOR_AXIS_ID,
  ROAD_LINE_WIDTH_AXIS_ID,
  getRoadFilterAxis,
  type RoadFilterAxis,
  type RoadFilterAxisId,
} from "@/components/Map/roadFilterAxes";
import type { LegendEntry } from "@/components/Map/legendFilter";
import type { StaticFilterAxis, StaticFilterAxisId } from "@/components/Map/staticAttributeLayers";
import type { SecondaryAxisSummary } from "@/components/Map/secondaryAxes";
import { InfoIcon } from "@/components/Map/icons";
import LayerChip from "@/components/Map/LayerChip";
import Disclosure from "@/components/Disclosure/Disclosure";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import WidthSwatch from "./WidthSwatch";
import styles from "./MapLayersPanel.module.css";

// 路面の絞り込み軸→対応するレイヤーID（改善計画T165: 「道路情報」の論理分割）。
// surface（路面の種類）はroadSurfaceレイヤー、highway（道路の種類）はroadTypeレイヤーを
// それぞれ自動ON対象とする（handleRoadLegendToggle/handleRoadAxisSetHidden参照）。
function roadFilterAxisLayerId(axisId: RoadFilterAxisId): MapLayerId {
  return axisId === "surface" ? "roadSurface" : "roadType";
}

interface MapLayersPanelProps {
  layerVisibility: MapLayerVisibility;
  onLayerToggle: (id: MapLayerId, on: boolean) => void;
  /** 道路情報の2軸（路面の種類・道路の種類）それぞれの非表示カテゴリキー */
  roadHiddenKeysByMode: Record<RoadFilterAxisId, readonly string[]>;
  /** 凡例チェックの操作（即時反映。連続タップの再描画はpage.tsx側のデバウンスが吸収） */
  onRoadLegendToggle: (axisId: RoadFilterAxisId, key: string) => void;
  /** 「すべて表示/すべて隠す」の一括操作（非表示キー全体の置き換え） */
  onRoadAxisSetHidden: (axisId: RoadFilterAxisId, hiddenKeys: string[]) => void;
  /** 車ストレス・自転車インフラ・停止要因POI・事故（当事者/重大度）の絞り込み軸
   * （改善計画T63、STATIC_FILTER_AXES参照）。事故のみ2軸を持ち、他は1軸。 */
  staticFilterHiddenKeysByAxis: Record<StaticFilterAxisId, readonly string[]>;
  onStaticFilterLegendToggle: (axisId: StaticFilterAxisId, key: string) => void;
  onStaticFilterAxisSetHidden: (axisId: StaticFilterAxisId, hiddenKeys: string[]) => void;
  regionZoomTooWide: boolean;
  /** レイヤーごとのデータ取得状態（改善計画T87、loading/empty/error）。MapView.tsxが
   * タイル取得結果から算出する。表示OFF中や正常時はキー自体を持たない。 */
  layerDataStatus: LayerDataStatusByLayer;
  /** いずれかの軸で絞り込み中（非表示カテゴリが1つ以上ある）か。falseの間は一括クリアボタン自体を出さない */
  hasHiddenFilters: boolean;
  /** 全軸の非表示カテゴリを一度に解除する（軸ごとの「すべて表示」を繰り返させない）。
   * レイヤーのON/OFFには触れない（絞り込みとは別の状態のため） */
  onClearAllFilters: () => void;
  /** 改善計画T308: 地図レイヤーカタログ（page.tsx側でaxisCatalog.rampAxesから
   * buildMapLayers()経由で組み立てたもの、軸スタジオの公開軸を含む）。 */
  mapLayers: readonly MapLayerDescriptor[];
  /** road_surfaceタイルを共有するレイヤーのMapLayerId一覧（page.tsx側でmapLayersと同じ
   * rampAxesからbuildRoadSurfaceSharedLayerIds()経由で組み立てたもの）。 */
  roadSurfaceSharedLayerIds: readonly MapLayerId[];
  /** 二次軸(推定指標)一覧（page.tsx側でaxisCatalog.secondaryAxesをそのまま渡す）。 */
  secondaryAxes: readonly SecondaryAxisSummary[];
  /** コードレビュー指摘の修正: 車ストレス・自転車インフラ・停止要因POI・事故等の絞り込み軸
   * カタログ（page.tsx側でaxisCatalog.rampAxesからbuildStaticFilterAxes()経由で組み立てた
   * もの、軸スタジオの公開ramp軸を含む）。以前はこのファイル内で静的STATIC_FILTER_AXESを
   * 直接importしており、軸スタジオで新規公開したramp軸の絞り込みチェックボックスが
   * 再デプロイまで現れなかった（MapView.tsx側は既にbuildStaticFilterAxes(rampAxes)へ
   * 移行済みで、この画面だけ取り残されていた）。 */
  staticFilterAxes: readonly StaticFilterAxis[];
}

// サイドバーのグループ見出し。改善計画（地図の見え方パネルのグルーピングを地図上チップと
// 統一）: 見出しは次数（推定/観測、mapLayers.ts: MAP_LAYER_DATA_NATURE_ORDER/LABELS）のみの
// 1階層。以前は中分類（category、改善計画T86、MAP_LAYER_CATEGORY_ORDER/LABELS）ごとの
// 見出し（h2）も持っていたが、地図上チップ側（MapOverlayControls.tsx）が実機フィードバックを
// 受けてカテゴリ見出しを廃止しフラット化した経緯（改善計画T169）と揃え、こちらも中分類の
// 見出しは出さない（「地図の見え方と合わせて、中分類は不要」という実機フィードバック）。
// categoryはあくまで観測グループ内のレイヤー並び順（MAP_LAYER_CATEGORY_ORDER）を
// 揃えるための内部キーとしてのみ使う。「生成したルートの色分け」（dynamic/route）は次数を
// 持たないレイヤーで観測/推定どちらにも属さないため、地図の見え方パネルからは撤去し
// 「ルートを作る」パネル側へ移設した（page.tsx: renderRouteSectionBody参照。実機
// フィードバック「ルートを作るパネルがルートに関する制御、地図の見え方パネルが地図自体の
// 制御」への対応。そちらは見出し＋本文の見た目としてこのファイルの.group/.groupTitleを
// 再利用しているため、このファイル自身はもう使っていなくてもクラス定義は残す）。
// 見出し文言はmapLayers.tsを単一ソースとし、地図上チップのグルーピング
// （改善計画T128/T166、MapOverlayControls.tsx）と共有するが、次数グループの表示順
// （MAP_LAYER_DATA_NATURE_ORDER）自体はパネル専用に「観測→推定」へ反転済み（実機
// フィードバック「推定指標よりも観測指標を上に」への対応。mapLayers.tsのコメント参照）。
// 推定グループ内のレイヤー並び順は、地図チップの推定グループが横並びで見せている軸の順序
// （SECONDARY_AXES、axis-catalog.json由来）と一致させる（実機フィードバック「推定指標の
// 上から数えた順番を地図上の左から数えた順番と一致させて」への対応。以前はcategory順
// だったため、地図チップの並び[勾配・舗装質・停止密度・車の圧迫感・夜間・事故密度]と
// 食い違っていた）。専用の表示レイヤーを持たない軸（勾配・舗装質・夜間、地図チップでは
// 灰色のタップ不能タイル）も、地図チップと同じくパネルにも存在させる（実機フィードバック
// 「地図上でグレー表示のものも展開だけさせず存在させて」への対応。以前はMapLayerId自体を
// 持たないためパネルから完全に抜け落ちていた）。ただし設定できる項目が無いため、他レイヤーの
// ような開閉式の<details>にはせず、常時見える案内行（renderProxyAxisSection）として出す
// （「展開だけさせず」＝折りたたみ式にすると開かない限り存在に気づけないため）。
// 地図レイヤーの「細かな設定」をすべて集約するサイドバー内パネル。
// レイヤーごとに1セクション（見出し＋表示スイッチ＋凡例・絞り込み等の設定）を持ち、
// セクションの枠組みはMAP_LAYERS（レイヤーカタログ）の列挙で描画する。地図の上
// （MapOverlayControls）はON/OFFチップと▶で開く凡例の確認までで、絞り込みの変更などの
// 編集操作はすべてこのパネルの中だけで完結する。
// 以前のMapLegendPanel（凡例の参照表示のみ）とRoadFilterDialog（地図上の⚙から開く
// 絞り込みモーダル）を統合したもの。
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
  layerDataStatus,
  hasHiddenFilters,
  onClearAllFilters,
  mapLayers,
  roadSurfaceSharedLayerIds,
  secondaryAxes,
  staticFilterAxes,
}: MapLayersPanelProps) {
  const roadColorAxis = getRoadFilterAxis(ROAD_LINE_COLOR_AXIS_ID);
  const roadWidthAxis = getRoadFilterAxis(ROAD_LINE_WIDTH_AXIS_ID);

  // 各メンバーの説明（panelHint/panelHintDetail/proxyHint）の開閉状態。実機フィードバック
  // 「各メンバーの説明は、情報アイコン（！）を押したら見えるようにして」への対応。以前は
  // セクションを開く（<details>）だけで説明文が常に見えており、車ストレスの8行に及ぶ
  // 判定内訳などが常時表示されて読みにくいという指摘につながっていた。研究タブの
  // FieldLabel（recipeControls.tsx、評価重み入力の説明トグルと同じ部品）をそのまま再利用し、
  // 「見出し（ON/OFFの下）に説明トグルを置き、押すまで説明文自体は非表示」という統一挙動に
  // する。キーはlayer.idまたは`axis-proxy-${axisId}`（専用レイヤーを持たない推定軸）。
  const [openHintKeys, setOpenHintKeys] = useState<ReadonlySet<string>>(new Set());
  function toggleHintOpen(key: string) {
    setOpenHintKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }
  // panelHint（＋panelHintDetailがあれば内訳の箇条書き）を、情報アイコンのトグルの下へ
  // まとめて出す共通描画。renderStandardSectionBody・elevationケース・
  // renderProxyAxisSectionの3箇所が共有する（以前はmutedHintの<p>を直接埋め込むだけの
  // 3箇所バラバラの実装だった）。研究タブのFieldLabel（recipeControls.tsx）と同趣向だが、
  // あちらは「フィールド名＋アイコン」がラベル代わりを兼ねる構成（フィールド名自体が
  // 他に表示されていない）のに対し、こちらはレイヤー名が既に見出し（<summary><h3>）に
  // 出ているため、ボタンの可視テキストは汎用の「説明」に留め、アクセシブル名
  // （aria-label）の方にレイヤー固有の名前（subjectLabel）を使い分ける。
  function renderHintToggle(
    key: string,
    subjectLabel: string,
    hint: string | undefined,
    detail?: readonly string[],
  ) {
    if (!hint) return null;
    const open = openHintKeys.has(key);
    return (
      <>
        <button
          type="button"
          className={styles.hintToggle}
          aria-expanded={open}
          aria-label={`${subjectLabel}の説明を${open ? "隠す" : "表示"}`}
          onClick={() => toggleHintOpen(key)}
        >
          <InfoIcon size={13} />
          <span aria-hidden="true">説明</span>
        </button>
        {open && (
          <>
            <p className={styles.mutedHint}>{hint}</p>
            {detail && detail.length > 0 && (
              <ul className={styles.hintList}>
                {detail.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </>
    );
  }

  // 路面の種類・道路の種類の絞り込みは即時反映（T31。旧「下書き→適用」はRoadFilterEditor
  // ごと廃止し、ルート凡例のチェックと同じ方式へ統一した）。OFF中に操作したら
  // レイヤーを自動でONにする（設定したのに何も起きない状態を作らない）。
  // 改善計画T165: 「道路情報」（road）が路面の種類（surface軸→roadSurfaceレイヤー）・
  // 道路の種類（highway軸→roadTypeレイヤー）へ論理分割されたため、軸ごとに自動ONする
  // レイヤーが異なる（roadFilterAxisLayerId参照）。
  function handleRoadLegendToggle(axisId: RoadFilterAxisId, key: string) {
    onRoadLegendToggle(axisId, key);
    const layerId = roadFilterAxisLayerId(axisId);
    if (!layerVisibility[layerId]) onLayerToggle(layerId, true);
  }

  function handleRoadAxisSetHidden(axisId: RoadFilterAxisId, hiddenKeys: string[]) {
    onRoadAxisSetHidden(axisId, hiddenKeys);
    const layerId = roadFilterAxisLayerId(axisId);
    if (!layerVisibility[layerId]) onLayerToggle(layerId, true);
  }

  // 改善計画T63: 道路情報以外の4レイヤー（車ストレス・自転車インフラ・停止要因POI・
  // 事故）の絞り込み。道路情報と同じ「即時反映＋操作したレイヤーを自動でON」の
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
          // 「不明・他」等の受け皿カテゴリは他の項目と同列の判定値ではないため、区切り線＋
          // 弱調表示で分離する（改善計画T89、legendFilter.ts: LegendEntry.isFallback参照）。
          const rowClassName = entry.isFallback
            ? `${styles.legendCheckboxRow} ${styles.legendCheckboxRowFallback}`
            : styles.legendCheckboxRow;
          return (
            <label key={entry.key} className={rowClassName}>
              <Checkbox checked={visible} onCheckedChange={() => onToggle(entry.key)} aria-label={entry.label} />
              {entry.width !== undefined ? (
                <WidthSwatch width={entry.width} dashed={entry.dashed} color={entry.color} />
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

  // layer.idの絞り込み軸一覧（staticFilterAxes prop参照、事故のみ2件）。
  function staticFilterAxesFor(layerId: MapLayerId): readonly StaticFilterAxis[] {
    return staticFilterAxes.filter((axis) => axis.layerId === layerId);
  }

  // 道路情報と同じ「OFF中でも絞り込み操作でき、操作すると自動でONになる」ことの案内文。
  function renderOffHint(layerId: MapLayerId) {
    return (
      !layerVisibility[layerId] && (
        <p className={styles.mutedHint}>表示はOFFです[絞り込みを操作すると自動でONになります]</p>
      )
    );
  }

  // レイヤーの現在有効なデータ状態（改善計画T87）。表示OFF中、またはroad_surfaceタイルを
  // 共有する4レイヤー（ROAD_SURFACE_SHARED_LAYER_IDS）がregionZoomTooWide中（ズーム範囲外の
  // 案内が既に出ている）はundefinedを返し、案内自体を抑制する。セクション本文
  // （renderDataStatusHint）とヘッダーのLayerChip状態ドット（renderLayerSection）の両方が
  // この判定を共有する単一の入口にすることで、片方だけ抑制し忘れる食い違いを防ぐ
  // （レビュー指摘: 以前はroadのswitchケースの呼び出し元だけでregionZoomTooWideを見ており、
  // 同じソースを共有するbicycleInfra/designationの本文や、road自身を含む
  // 全レイヤーのヘッダーチップには抑制が効いていなかった）。
  function visibleDataStatus(layerId: MapLayerId): LayerDataStatus | undefined {
    if (!layerVisibility[layerId]) return undefined;
    if (regionZoomTooWide && roadSurfaceSharedLayerIds.includes(layerId)) return undefined;
    return layerDataStatus[layerId];
  }

  // レイヤーのデータ取得状態を示す案内文。正常時（既知件数のデータが描画できている状態）は
  // visibleDataStatusがundefinedを返すため何も出さない。取得失敗のみ警告色（zoomWarningと
  // 同じ「ズームインしてください」に近い、行動を促す度合いが高いメッセージ）で目立たせ、
  // 読込中・データなしはOFF案内と同じ弱調表示にする。
  function renderDataStatusHint(layerId: MapLayerId) {
    const status = visibleDataStatus(layerId);
    if (!status) return null;
    return (
      <p className={status === "error" ? styles.dataStatusError : styles.mutedHint}>
        {LAYER_DATA_STATUS_LABELS[status]}
      </p>
    );
  }

  // 改善計画T84: bicycleInfra/designation/tunnel/oneway/stopPoi/accidents（T292でcar_stress
  // もaxis:${string}経由でここへ合流）は「panelHint文＋OFF案内＋絞り込み軸」という同型JSXの
  // 標準レイヤー（elevationはpanelHintのみ・
  // road/routeは専用UIを持つ真に特殊なレイヤーのためこの関数の対象外）。以前はレイヤーごとに
  // 同型JSXブロックを6つ複製し、説明文もmapLayers.tsのdescriptionとは別にここへハードコード
  // していた（文言修正時に片方だけ直り画面間で食い違うリスク、設計原則8違反）。
  function renderStandardSectionBody(layer: MapLayerDescriptor) {
    return (
      <>
        {renderHintToggle(layer.id, layer.label, layer.panelHint, layer.panelHintDetail)}
        {renderDataStatusHint(layer.id)}
        {renderOffHint(layer.id)}
        {staticFilterAxesFor(layer.id).map(renderStaticFilterAxis)}
      </>
    );
  }

  // 路面の種類・道路の種類（改善計画T165で「道路情報」から論理分割）1レイヤーぶんの本文。
  // 凡例チェックボックス＝絞り込み操作（参照表示と操作を1つのリストで兼ねる、ルート凡例と
  // 同じ方式）。OFF中でも操作でき、操作すると自動でONになる。2レイヤーとも同じ形（OFF案内・
  // ズーム警告・データ状態・凡例）のため共通化し、visual（"色"/"太さ"）・axisだけ呼び出し側で渡す。
  function renderRoadAxisSectionBody(layer: MapLayerDescriptor, axis: RoadFilterAxis, visual: string) {
    const layerId = layer.id;
    return (
      <>
        {renderHintToggle(layer.id, layer.label, layer.panelHint)}
        {!layerVisibility[layerId] && (
          <p className={styles.mutedHint}>表示はOFFです[絞り込みを操作すると自動でONになります]</p>
        )}
        {layerVisibility[layerId] && regionZoomTooWide && (
          <p className={styles.zoomWarning}>表示範囲が広すぎます。ズームインしてください。</p>
        )}
        {/* regionZoomTooWide中の抑制はrenderDataStatusHint内で一律に判定する
            （ROAD_SURFACE_SHARED_LAYER_IDS参照）。 */}
        {renderDataStatusHint(layerId)}
        {renderRoadAxis(axis, visual)}
      </>
    );
  }

  function renderSectionBody(layer: MapLayerDescriptor) {
    switch (layer.id) {
      case "elevation":
        // 設定項目が無いレイヤーは説明文のみ（将来、不透明度等の設定を足す場所）。
        // ラスタタイルのためデータ取得状態は取得失敗のみ検知対象（MapView.tsx参照）。
        return (
          <>
            {renderHintToggle(layer.id, layer.label, layer.panelHint)}
            {renderDataStatusHint(layer.id)}
          </>
        );
      case "precipitationNowcast":
      case "windVector":
        // elevationと同じ理由（絞り込みUIを持たないレイヤー）でOFF案内
        // （renderOffHint、「絞り込みを操作すると自動でONになります」）を出さない。
        // 表示時刻は地図上の時刻スライダー（page.tsx）で操作する、このパネルの対象外の機構。
        return (
          <>
            {renderHintToggle(layer.id, layer.label, layer.panelHint)}
            {renderDataStatusHint(layer.id)}
          </>
        );
      case "bicycleInfra":
      case "designation":
      case "tunnel":
      case "oneway":
      case "stopPoi":
      case "supplyPoi":
      case "accidents":
        return renderStandardSectionBody(layer);
      case "roadSurface":
        return renderRoadAxisSectionBody(layer, roadColorAxis, "色");
      case "roadType":
        return renderRoadAxisSectionBody(layer, roadWidthAxis, "太さ");
      default:
        // axis:${string}（ramp軸、改善計画T145b: 停止/事故密度の凡例追加。T292で
        // car_stressもここに合流）はbicycleInfra等と同じ標準構成（panelHint＋OFF案内＋
        // 絞り込み軸）で足りるため、個別caseを持たずデフォルトで拾う。
        return renderStandardSectionBody(layer);
    }
  }

  // レイヤー1件分のセクション（見出し＋ON/OFFチップ＋設定本文）。カテゴリ単位・kind単位
  // どちらのグループ化でも同じ描画になる（改善計画T86でグルーピング単位をkindからcategoryへ
  // 変更したが、レイヤー単体の描画自体は変えていない）。「route」は次数を持たず観測/推定の
  // どちらにも属さないため、地図の見え方パネル自体の対象外へ移設した（「ルートを作る」
  // パネル、page.tsx参照）。以前ここにあったdisabled判定（ルート未生成時のみ）はそれに
  // 伴い不要になった（この関数を通るレイヤーが常に有効なため）。
  function renderLayerSection(layer: MapLayerDescriptor) {
    const domId = layerSectionDomId(layer.id);
    return (
      // 要素ごとに折りたたむ階層メニュー（モバイル実機フィードバック対応T38。
      // 以前は5レイヤー分の設定が常時全展開でスクロールが長かった）。デフォルト全閉。
      // domIdはコンテナ（Root）に振る（旧<details id>と同じ位置づけ。テストで
      // document.getElementByIdから領域を絞り込んだりトリガーを辿ってクリックする
      // ためのフック。MapLayersPanel.test.tsxのopenSection参照。以前はネイティブ<details>の
      // .open書き換えだったが、Radix Accordion化(T254)によりトリガーをクリックする方式へ
      // 変更した）。
      <Disclosure
        key={layer.id}
        className={styles.layerSection}
        headerClassName={styles.layerHeader}
        triggerClassName={styles.layerTitle}
        bodyClassName={styles.layerBody}
        id={domId}
        summary={
          <>
            <span aria-hidden="true" className={styles.chevron} />
            {layer.label}
          </>
        }
        // ON/OFFは地図上のチップと同一部品（LayerChip）。見た目が同じ＝同じ操作だと
        // 伝えるため、role=switchのチェックボックスからチップへ統一した（T30）。
        // trailingとしてTrigger（button）の外に置くため、button内buttonという無効な
        // HTMLにならず、以前summary内で必要だったpreventDefault/stopPropagation
        // （details開閉のデフォルト動作との衝突回避）も不要になった。
        trailing={
          <LayerChip
            label="表示"
            ariaLabel={`${layer.label}レイヤーを表示`}
            on={layerVisibility[layer.id]}
            dataStatus={visibleDataStatus(layer.id)}
            onClick={() => onLayerToggle(layer.id, !layerVisibility[layer.id])}
          />
        }
      >
        {renderSectionBody(layer)}
      </Disclosure>
    );
  }

  // 推定グループの1件（secondaryAxes props由来）。専用の表示レイヤーを持つ軸はmapLayersの
  // 対応するレイヤーを、持たない軸（proxy）はaxis自体を返す（上記コメント参照）。
  type CompositeEntry =
    | { kind: "layer"; layer: MapLayerDescriptor }
    | { kind: "proxy"; axis: SecondaryAxisSummary };

  // secondaryAxes（改善計画T308: axisCatalog.secondaryAxes、地図チップの左からの並びと
  // 同じ順序）をそのままなぞって推定グループの並び順を作る。地図チップ側と単一ソースを
  // 共有することで、軸の追加・並び替えがあってもここを個別に追従させる必要がない。
  function orderedCompositeEntries(): readonly CompositeEntry[] {
    return secondaryAxes.map((axis): CompositeEntry => {
      const layer = axis.layerId ? mapLayers.find((l) => l.id === axis.layerId) : undefined;
      return layer ? { kind: "layer", layer } : { kind: "proxy", axis };
    });
  }

  // 専用の表示レイヤーを持たない推定軸（勾配・舗装質・夜間）の1件分。地図チップでは
  // タップ不能の灰色タイルとして存在するのと同じ理由で、開閉式の<details>にはせず
  // 常時見える案内行にする（上記コメント参照）。設定項目もON/OFFも無いため、
  // 他レイヤーのセクション（renderLayerSection）とは別の軽量な描画にする。
  function renderProxyAxisSection(axis: SecondaryAxisSummary) {
    return (
      <div key={`axis-proxy-${axis.axisId}`} className={styles.proxyAxisSection}>
        <h3 className={styles.proxyAxisTitle}>{axis.label}</h3>
        <div className={styles.proxyAxisBody}>
          {renderHintToggle(`axis-proxy-${axis.axisId}`, axis.label, axis.proxyHint)}
        </div>
      </div>
    );
  }

  return (
    // gap-2(0.5rem)は要素間の余白を詰めてほしいという実機フィードバックを受けた縮小値（T41）
    <div className="flex flex-col gap-2">
      {/* 各軸に「すべて表示」はあるが、複数レイヤーにまたがって絞り込んだ後に全部を
          1つずつ開いて戻すのは手間が大きい（ゆる～と等の地図ポータルの「消去」ボタンを
          参考に追加）。絞り込みが無ければボタンを無効化・非表示にするが、要素自体は
          常にマウントしたままにする（実機フィードバック: 条件付きレンダリングでこの行が
          出現/消失するとパネル内の他のボタン（レイヤーの表示トグル等）が上下にずれ、
          「消える直前・直後にクリックすると別の要素に当たる」誤操作を実測で確認したため。
          visibilityで隠すだけならレイアウト上の高さは常に確保され、この種のずれが起きない）。 */}
      <div className={styles.clearAllRow} data-visible={hasHiddenFilters}>
        <button
          type="button"
          className={styles.bulkButton}
          onClick={onClearAllFilters}
          disabled={!hasHiddenFilters}
          tabIndex={hasHiddenFilters ? 0 : -1}
          aria-hidden={!hasHiddenFilters}
        >
          絞り込みを一括クリア
        </button>
      </div>
      {MAP_LAYER_DATA_NATURE_ORDER.map((dataNature: MapLayerDataNature) => {
        if (dataNature === "composite") {
          // 推定グループだけは地図チップの並び（SECONDARY_AXES）を使う（上記コメント参照）。
          const entries = orderedCompositeEntries();
          if (entries.length === 0) return null;
          return (
            <div key={dataNature} className={styles.natureGroup}>
              <h2 className={styles.natureTitle}>{MAP_LAYER_DATA_NATURE_LABELS[dataNature]}</h2>
              {entries.map((entry) =>
                entry.kind === "layer" ? renderLayerSection(entry.layer) : renderProxyAxisSection(entry.axis)
              )}
            </div>
          );
        }
        // categoryは見出しにはせず、地図上チップの観測グループと同じ並び順
        // （MAP_LAYER_CATEGORY_ORDER）を揃えるためだけに使う内部キー（上記コメント参照）。
        const layers = MAP_LAYER_CATEGORY_ORDER.flatMap((category) =>
          mapLayers.filter(
            (layer) => layer.kind === "static" && layer.category === category && (layer.dataNature ?? "raw") === dataNature
          )
        );
        if (layers.length === 0) return null;
        return (
          <div key={dataNature} className={styles.natureGroup}>
            <h2 className={styles.natureTitle}>{MAP_LAYER_DATA_NATURE_LABELS[dataNature]}</h2>
            {layers.map(renderLayerSection)}
          </div>
        );
      })}
    </div>
  );
}
