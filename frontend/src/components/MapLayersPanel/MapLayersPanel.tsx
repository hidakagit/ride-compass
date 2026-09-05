"use client";

import {
  LAYER_DATA_STATUS_LABELS,
  MAP_LAYER_CATEGORY_ORDER,
  MAP_OVERLAY_GROUP_LABELS,
  MAP_OVERLAY_GROUP_ORDER,
  layerSectionDomId,
  mapOverlayGroupFor,
  type LayerDataStatus,
  type LayerDataStatusByLayer,
  type MapLayerDescriptor,
  type MapLayerId,
  type MapLayerVisibility,
  type MapOverlayGroup,
} from "@/components/Map/mapLayers";
import {
  ROAD_LINE_COLOR_AXIS_ID,
  ROAD_LINE_WIDTH_AXIS_ID,
  getRoadFilterAxis,
  type RoadFilterAxis,
  type RoadFilterAxisId,
} from "@/components/Map/roadFilterAxes";
import type { StaticFilterAxis, StaticFilterAxisId } from "@/components/Map/staticAttributeLayers";
import LayerChip from "@/components/Map/LayerChip";
import LegendCheckboxList from "@/components/Map/LegendCheckboxList";
import Disclosure from "@/components/Disclosure/Disclosure";
import styles from "./MapLayersPanel.module.css";

// 路面の絞り込み軸→対応するレイヤーID。surface（路面の種類）はroadSurfaceレイヤー、
// highway（道路の種類）はroadTypeレイヤーを
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
   * （STATIC_FILTER_AXES参照）。事故のみ2軸を持ち、他は1軸。 */
  staticFilterHiddenKeysByAxis: Record<StaticFilterAxisId, readonly string[]>;
  onStaticFilterLegendToggle: (axisId: StaticFilterAxisId, key: string) => void;
  onStaticFilterAxisSetHidden: (axisId: StaticFilterAxisId, hiddenKeys: string[]) => void;
  regionZoomTooWide: boolean;
  /** レイヤーごとのデータ取得状態（loading/empty/error）。MapView.tsxがタイル取得結果
   * から算出する。表示OFF中や正常時はキー自体を持たない。 */
  layerDataStatus: LayerDataStatusByLayer;
  /** いずれかの軸で絞り込み中（非表示カテゴリが1つ以上ある）か。falseの間は一括クリアボタン自体を出さない */
  hasHiddenFilters: boolean;
  /** 全軸の非表示カテゴリを一度に解除する（軸ごとの「すべて表示」を繰り返させない）。
   * レイヤーのON/OFFには触れない（絞り込みとは別の状態のため） */
  onClearAllFilters: () => void;
  /** 地図レイヤーカタログ（page.tsx側でaxisCatalog.rampAxesからbuildMapLayers()経由で
   * 組み立てたもの、軸スタジオの公開軸を含む）。 */
  mapLayers: readonly MapLayerDescriptor[];
  /** road_surfaceタイルを共有するレイヤーのMapLayerId一覧（page.tsx側でmapLayersと同じ
   * rampAxesからbuildRoadSurfaceSharedLayerIds()経由で組み立てたもの）。 */
  roadSurfaceSharedLayerIds: readonly MapLayerId[];
  /** 車ストレス・自転車インフラ・停止要因POI・事故等の絞り込み軸カタログ（page.tsx側で
   * axisCatalog.rampAxesからbuildStaticFilterAxes()経由で組み立てたもの、軸スタジオの
   * 公開ramp軸を含む）。 */
  staticFilterAxes: readonly StaticFilterAxis[];
}

// サイドバーのグループ見出しは「道路/環境/スポット」（mapLayers.ts:
// MAP_OVERLAY_GROUP_ORDER/LABELS、mapOverlayGroupFor）のみの1階層で、地図上チップ側
// （MapOverlayControls.tsx）と同じ語彙を単一ソース（mapOverlayGroupFor）から使う
// （複雑度平衡原則8「UI語彙のカタログ集約」）。中分類（category、
// MAP_LAYER_CATEGORY_ORDER/LABELS）ごとの見出し（h2）は出さない——categoryはあくまで
// 「道路」「環境」「スポット」各グループ内のレイヤー並び順を揃えるための内部キーとして
// のみ使う。降水ナウキャスト等dataNature="dynamic"のレイヤー（帯単位の絞り込み機能を
// 持たない）は、このパネルの詳細セクションからは除外する（ON/OFFは地図上チップ側で
// 操作できるため実害なし）。elevation（標高図）のように静的なラスタレイヤーで
// dataNature="dynamic"には当てはまらないが同じ理由（絞り込み機能を持たずON/OFFのみ）で
// 掲載する意味が無いレイヤーはhideFromLayersPanelで個別に除外する（mapLayers.ts:
// MapLayerDescriptor.hideFromLayersPanel参照。地図上チップのON/OFF自体は引き続き必要
// なため撤去はせず、このサイドバーパネルへの重複掲載のみをやめる）。
// 「生成したルートの色分け」（dynamic/route）はどのグループにも属さないレイヤーのため、
// 地図の見え方パネルからは撤去し「ルートを作る」パネル側へ移設した（page.tsx:
// renderRouteSectionBody参照。「ルートを作るパネルがルートに関する制御、地図の見え方
// パネルが地図自体の制御」という役割分担のため。そちらは見出し＋本文の見た目として
// このファイルの.group/.groupTitleを再利用しているため、このファイル自身はもう
// 使っていなくてもクラス定義は残す）。
// 軸スタジオが作る評価軸（car_stress等・windAxis）のセクションはこのパネルに無い
// （評価軸チップ自体を地図UIから撤去しルート設定パネル[RouteSettingsPanel.tsx]へ
// 移設したため）——軸スタジオ由来のレイヤー（isAxisStudioLayer、mapLayers.ts）は
// mapOverlayGroupForが常にundefinedを返すため、下記の「道路」「環境」「スポット」列挙
// （mapOverlayGroupFor(layer) === groupの絞り込み）には自然に現れない。
// 地図レイヤーの「細かな設定」をすべて集約するサイドバー内パネル。
// レイヤーごとに1セクション（見出し＋表示スイッチ＋凡例・絞り込み等の設定）を持ち、
// セクションの枠組みはMAP_LAYERS（レイヤーカタログ）の列挙で描画する。地図の上
// （MapOverlayControls）はON/OFFチップと▶で開く凡例の確認までで、絞り込みの変更などの
// 編集操作はすべてこのパネルの中だけで完結する。
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
  staticFilterAxes,
}: MapLayersPanelProps) {
  const roadColorAxis = getRoadFilterAxis(ROAD_LINE_COLOR_AXIS_ID);
  const roadWidthAxis = getRoadFilterAxis(ROAD_LINE_WIDTH_AXIS_ID);

// 路面の種類・道路の種類の絞り込みは即時反映する。OFF中に操作したらレイヤーを自動で
  // ONにする（設定したのに何も起きない状態を作らない）。「道路情報」（road）は路面の種類
  // （surface軸→roadSurfaceレイヤー）・道路の種類（highway軸→roadTypeレイヤー）へ論理
  // 分割されているため、軸ごとに自動ONするレイヤーが異なる（roadFilterAxisLayerId参照）。
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

  // 道路情報以外の4レイヤー（車ストレス・自転車インフラ・停止要因POI・事故）の絞り込み。
  // 道路情報と同じ「即時反映＋操作したレイヤーを自動でON」の挙動を、STATIC_FILTER_AXESの
  // layerIdを使って軸非依存に実装する（layerIdは呼び出し側のrenderSectionBodyケースが
  // 自身のlayer.idとして渡す）。
  function handleStaticFilterLegendToggle(layerId: MapLayerId, axisId: StaticFilterAxisId, key: string) {
    onStaticFilterLegendToggle(axisId, key);
    if (!layerVisibility[layerId]) onLayerToggle(layerId, true);
  }

  function handleStaticFilterAxisSetHidden(layerId: MapLayerId, axisId: StaticFilterAxisId, hiddenKeys: string[]) {
    onStaticFilterAxisSetHidden(axisId, hiddenKeys);
    if (!layerVisibility[layerId]) onLayerToggle(layerId, true);
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
              一括ボタンでタップ数を減らす */}
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
        <LegendCheckboxList
          legend={axis.legend}
          hiddenKeys={hiddenKeys}
          onToggle={(key) => handleRoadLegendToggle(axis.id, key)}
          listClassName={styles.legendCheckboxList}
          rowClassName={styles.legendCheckboxRow}
          rowFallbackClassName={styles.legendCheckboxRowFallback}
          swatchClassName={styles.swatch}
        />
      </div>
    );
  }

  // 道路情報以外の絞り込み可能レイヤーの1軸分（一括操作＋凡例チェックボックス）。
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
        <LegendCheckboxList
          legend={axis.legend}
          hiddenKeys={hiddenKeys}
          onToggle={(key) => handleStaticFilterLegendToggle(axis.layerId, axis.axisId, key)}
          listClassName={styles.legendCheckboxList}
          rowClassName={styles.legendCheckboxRow}
          rowFallbackClassName={styles.legendCheckboxRowFallback}
          swatchClassName={styles.swatch}
        />
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

  // レイヤーの現在有効なデータ状態。表示OFF中、またはroad_surfaceタイルを共有する
  // 4レイヤー（ROAD_SURFACE_SHARED_LAYER_IDS）がregionZoomTooWide中（ズーム範囲外の
  // 案内が既に出ている）はundefinedを返し、案内自体を抑制する。セクション本文
  // （renderDataStatusHint）とヘッダーのLayerChip状態ドット（renderLayerSection）の両方が
  // この判定を共有する単一の入口にすることで、片方だけ抑制し忘れる食い違いを防ぐ。
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

  // designation/tunnel/oneway/stopPoi/accidents（car_stressもaxis:${string}経由で
  // ここへ合流）は「panelHint文＋OFF案内＋絞り込み軸」という同型JSXの標準レイヤー
  // （elevationはpanelHintのみ・road/routeは専用UIを持つ真に特殊なレイヤーのため
  // この関数の対象外）。
  function renderStandardSectionBody(layer: MapLayerDescriptor) {
    return (
      <>
        {renderDataStatusHint(layer.id)}
        {renderOffHint(layer.id)}
        {staticFilterAxesFor(layer.id).map(renderStaticFilterAxis)}
      </>
    );
  }

  // 路面の種類・道路の種類（「道路情報」から論理分割した2レイヤー）1レイヤーぶんの本文。
  // 凡例チェックボックス＝絞り込み操作（参照表示と操作を1つのリストで兼ねる、ルート凡例と
  // 同じ方式）。OFF中でも操作でき、操作すると自動でONになる。2レイヤーとも同じ形（OFF案内・
  // ズーム警告・データ状態・凡例）のため共通化し、visual（"色"/"太さ"）・axisだけ呼び出し側で渡す。
  function renderRoadAxisSectionBody(layer: MapLayerDescriptor, axis: RoadFilterAxis, visual: string) {
    const layerId = layer.id;
    return (
      <>
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
        // axis:${string}（ramp軸、car_stressを含む）はdesignation等と同じ標準構成
        // （panelHint＋OFF案内＋絞り込み軸）で足りるため、個別caseを持たずデフォルトで拾う。
        return renderStandardSectionBody(layer);
    }
  }

  // レイヤー1件分のセクション（見出し＋ON/OFFチップ＋設定本文）。カテゴリ単位・kind単位
  // どちらのグループ化でも同じ描画になる。「route」はどのグループにも属さないため、
  // 地図の見え方パネル自体の対象外へ移設した（「ルートを作る」パネル、page.tsx参照）。
  // この関数を通るレイヤーは常に有効なため、disabled判定は持たない。
  function renderLayerSection(layer: MapLayerDescriptor) {
    const domId = layerSectionDomId(layer.id);
    return (
      // 要素ごとに折りたたむ階層メニュー。デフォルト全閉。domIdはコンテナ（Root）に
      // 振る。テストでdocument.getElementByIdから領域を絞り込んだりトリガーを辿って
      // クリックするためのフック（MapLayersPanel.test.tsxのopenSection参照）。
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
        // 伝える。trailingとしてTrigger（button）の外に置くため、button内buttonという
        // 無効なHTMLにならない。
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

  return (
    // gap-2(0.5rem)は要素間の余白を詰めた縮小値
    <div className="flex flex-col gap-2">
      {/* 各軸に「すべて表示」はあるが、複数レイヤーにまたがって絞り込んだ後に全部を
          1つずつ開いて戻すのは手間が大きいため、一括で解除するボタンを設ける。
          絞り込みが無ければボタンを無効化・非表示にするが、要素自体は常にマウントした
          ままにする——条件付きレンダリングでこの行が出現/消失すると、パネル内の他の
          ボタン（レイヤーの表示トグル等）が上下にずれ、「消える直前・直後にクリックすると
          別の要素に当たる」誤操作を招く。visibilityで隠すだけならレイアウト上の高さは
          常に確保され、この種のずれが起きない。 */}
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
      {MAP_OVERLAY_GROUP_ORDER.map((group: MapOverlayGroup) => {
        // 「道路」「環境」「スポット」は、mapOverlayGroupForで地図上チップと同じグループへ
        // 判定されるレイヤーのうち、dataNature="dynamic"（絞り込み機能を持たない、上記
        // コメント参照）・hideFromLayersPanel（同じくON/OFFのみで絞り込み機能を持たない
        // が、dynamicではない静的ラスタレイヤー[elevation実例]向け、mapLayers.ts:
        // MapLayerDescriptor.hideFromLayersPanel参照）を除いたものを、categoryの並び順
        // （MAP_LAYER_CATEGORY_ORDER）で揃えて列挙する。
        const layers = MAP_LAYER_CATEGORY_ORDER.flatMap((category) =>
          mapLayers.filter(
            (layer) =>
              layer.kind === "static" &&
              layer.category === category &&
              (layer.dataNature ?? "raw") !== "dynamic" &&
              !layer.hideFromLayersPanel &&
              mapOverlayGroupFor(layer) === group
          )
        );
        if (layers.length === 0) return null;
        return (
          <div key={group} className={styles.overlayGroup}>
            <h2 className={styles.overlayGroupTitle}>{MAP_OVERLAY_GROUP_LABELS[group]}</h2>
            {layers.map(renderLayerSection)}
          </div>
        );
      })}
    </div>
  );
}
