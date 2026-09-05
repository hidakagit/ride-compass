"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactElement,
} from "react";
import { createPortal } from "react-dom";
import { useStoredState } from "@/hooks/useStoredState";
import {
  isAxisStudioLayer,
  LAYER_DATA_STATUS_LABELS,
  MAP_LAYER_CATEGORY_ORDER,
  MAP_OVERLAY_GROUP_CHIP_LABELS,
  MAP_OVERLAY_GROUP_LABELS,
  MAP_OVERLAY_GROUP_ORDER,
  mapOverlayGroupFor,
  type LayerDataStatus,
  type MapLayerCategory,
  type MapLayerDataNature,
  type MapLayerId,
  type MapOverlayGroup,
} from "@/components/Map/mapLayers";
import type { LegendEntry, LegendFilterSummaryAxis } from "@/components/Map/legendFilter";
import WidthSwatch from "@/components/MapLayersPanel/WidthSwatch";
import LegendCheckboxList from "@/components/Map/LegendCheckboxList";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import {
  AccidentIcon,
  AxisRampIcon,
  DesignationIcon,
  ElevationIcon,
  EnvironmentDataIcon,
  InfoIcon,
  RaindropIcon,
  RoadIcon,
  RoadSurfaceIcon,
  ShieldIcon,
  SpotDataIcon,
  StopPoiIcon,
  SupplyPoiIcon,
  TunnelIcon,
  OnewayIcon,
  RouteIcon,
  WindIcon,
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
   * あるときは軸ごとの内訳だけで十分なため使わない。 */
  summary?: string | null;
  /** ▶を開いたときに出す、軸ごとの全カテゴリ内訳（表示中/非表示のいずれも含む）。
   * 絞り込み中かどうかに関わらず、レイヤーがONで凡例を持つならこれだけで開閉できる。 */
  legendDetails?: readonly LegendFilterSummaryAxis[];
  /** グループ内の小見出し分け用。mapLayers.ts: MapLayerDescriptor.categoryをそのまま
   * 渡す。未指定＝route等はどのグループにも属さず単独チップのまま。 */
  category?: MapLayerCategory;
  /** mapOverlayGroupFor()がcategoryと合わせて最上位グループ（道路/環境/スポット）を
   * 判定するために使う。mapLayers.ts: MapLayerDescriptor.dataNatureをそのまま渡す。 */
  dataNature?: MapLayerDataNature;
  /** 「表示する項目を選ぶ」設定パネル（renderVisibilitySettings）で、この項目の行に
   * 個別の情報アイコンを出し、押すと表示する説明文。mapLayers.ts:
   * MapLayerDescriptor.panelHintをそのまま渡す。未設定なら情報アイコン自体を出さない。
   * ▶パネル本体（renderRawMemberTile等）へ常時表示する用途には使わない（設定パネル
   * 内の任意開閉表示専用）。 */
  panelHint?: string;
  /** レイヤーのデータ取得状態。ChipButtonがLayerChip（サイドバー）と同じ
   * 「on && dataStatus != null」の間だけ小さな状態ドットを添える。 */
  dataStatus?: LayerDataStatus;
}

interface MapOverlayControlsProps {
  layers: readonly OverlayLayerChip[];
  onToggle: (id: MapLayerId, on: boolean) => void;
  /** ▶パネル内の1行（凡例カテゴリ・災害の要素等）の表示/非表示を切り替える。
   * `axisId`を持つ軸（`LegendFilterSummaryAxis.axisId`）だけがチェックボックス付きで
   * 描画され、この関数を呼ぶ。保存先はサイドバー（`MapLayersPanel`）と同じ
   * `page.tsx: hiddenLegendKeysByMode`のため、どちらから操作しても状態は1つに揃う。 */
  onLegendEntryToggle: (axisId: string, key: string) => void;
  /** ▶パネル内の1軸をまとめて表示/非表示にする（見出し行のチェックボックス）。
   * 保存先は`onLegendEntryToggle`と同じ`page.tsx: hiddenLegendKeysByMode`。 */
  onLegendAxisSetHidden: (axisId: string, hiddenKeys: string[]) => void;
}

// 最上位グループ（道路/環境/スポット）単位でグルーピングされたチップの中身。どの
// グループにも属さないレイヤー（route等）は単独チップ（members.length === 1）として
// まとめて表現し、単独/グループの分岐をレンダリング側で1本化する。
interface ChipGroup {
  key: string;
  members: readonly OverlayLayerChip[];
}

// レイヤーをmapOverlayGroupFor()（mapLayers.ts）で最上位グループ（道路/環境/スポット）へ
// 束ね、どのグループにも属さないレイヤー（route等）は元の並び順のまま末尾へ単独チップ
// として追加する。ただし軸スタジオ由来のレイヤー（isAxisStudioLayer、ramp軸・windAxis）は
// mapOverlayGroupForがundefinedを返す点ではroute等と同じだが、ルート設定パネルへ移設し
// 地図UIには一切出さないため、単独チップとしても出さないよう明示的に除外する
// （undefinedだけだとroute等と区別できず単独チップとして復活してしまう）。表示順は
// MAP_OVERLAY_GROUP_ORDER（道路→環境→スポット）に従う。MapLayerDataNature（生/合成/
// 動的）とは独立した分類軸のため、この関数はdataNatureそのものではなく
// mapOverlayGroupForの判定結果だけを見る。
function buildChipGroups(layers: readonly OverlayLayerChip[]): ChipGroup[] {
  const groups: ChipGroup[] = [];
  for (const group of MAP_OVERLAY_GROUP_ORDER) {
    const members = layers.filter((layer) => mapOverlayGroupFor(layer) === group);
    if (members.length > 0) {
      groups.push({ key: `group:${group}`, members });
    }
  }
  for (const layer of layers) {
    if (!mapOverlayGroupFor(layer) && !isAxisStudioLayer(layer)) groups.push({ key: layer.id, members: [layer] });
  }
  return groups;
}

// レイヤーIDごとの自作アイコン（icons.tsx）。地図上は小さいアイコン+短いラベルの
// 縦並びで表示する（文字だけのチップはスペースを圧迫するため）。
const LAYER_ICONS: Record<MapLayerId, (props: { size?: number }) => ReactElement> = {
  elevation: ElevationIcon,
  roadType: RoadIcon,
  roadSurface: RoadSurfaceIcon,
  designation: DesignationIcon,
  tunnel: TunnelIcon,
  oneway: OnewayIcon,
  stopPoi: StopPoiIcon,
  supplyPoi: SupplyPoiIcon,
  accidents: AccidentIcon,
  precipitationNowcast: RaindropIcon,
  windVector: WindIcon,
  // way_id→wind_drag_ratio配信層（評価軸としての風）。専用アイコンは持たず、同じ風の
  // データを扱うwindVectorと同じWindIconを流用する。このチップ自体は地図上に出ないが、
  // RouteSettingsPanel側がこのIcon辞書を引き続き参照しうるため残す。
  windAxis: WindIcon,
  // 勾配の環境グループ面表示・評価軸配信層。専用アイコンは持たず、同じ地形データを扱う
  // elevation（標高図）と同じElevationIconを流用する（windVector/windAxisがWindIconを
  // 共有するのと同じパターン）。gradientAxisも同じ理由でチップとしては地図上に出ないが、
  // RouteSettingsPanel側の参照に備えてRecordを完全に埋める。
  gradientFill: ElevationIcon,
  gradientAxis: ElevationIcon,
  // 災害（雷・竜巻・落雷・キキクル4種を1チップへまとめたグループ）。個々の要素を表す
  // アイコン（ThunderIcon/TornadoIcon/LidenIcon）ではなく、防災情報全体を表すShieldIconを
  // 使う。
  disaster: ShieldIcon,
  route: RouteIcon,
};

// 最上位グループチップ（道路/環境/スポット）を代表するアイコン。
// 道路=RoadIcon（個別メンバーroadTypeと共用、群のテーマそのもの）・
// 環境=EnvironmentDataIcon（雲、terrain+weatherを併せて表す新規アイコン）・
// スポット=SpotDataIcon（地図ピン、新規アイコン）。
const MAP_OVERLAY_GROUP_ICONS: Record<MapOverlayGroup, (props: { size?: number }) => ReactElement> = {
  road: RoadIcon,
  environment: EnvironmentDataIcon,
  spot: SpotDataIcon,
};

// アイコン行と▶トグルの間の間隔（CSS変数--space-2と一致させる。内訳パネルの位置を
// JSで計算する際、CSS側の見た目の間隔と揃えるために数値でも持つ必要がある）。
const PANEL_GAP_PX = 8;
// 内訳パネルの既定の最大高さ（MapOverlayControls.module.css: .detailPanelBaseの
// `max-height: min(45vh, 16rem)`のうちrem側の値と一致させる。PANEL_GAP_PXと同じ理由で、
// 画面下端からのはみ出し対策（下記toggleExpanded参照）をJS側で計算するために数値でも
// 持つ必要がある）。
const DETAIL_PANEL_MAX_HEIGHT_PX = 256; // 16rem（ブラウザ既定のroot font-size 16pxベース）
// 内訳パネルの最小幅。画面右端に近いタイル（例: 推定グループ末尾の軸）の▼/▶を押すと、
// rect.right基準のleftが既にビューポート右端に近く、この最小幅すら確保できないまま
// panelRect.leftを
// 使ってしまい、パネルがビューポート外へはみ出して読めなくなっていた。leftをこの分
// だけビューポート内へ押し戻すことで、パネル自身が必ずこの最小幅ぶんは画面内に収まる
// ようにする（下記toggleExpanded参照）。
const MIN_PANEL_WIDTH_PX = 160;
// グループ本体の開閉キー（下記toggleExpandedのコメント参照）。floatingパネルを持たない
// ため排他制御の対象外にする。
const GROUP_VISIBILITY_KEYS = new Set(["group:road", "group:environment", "group:spot"]);

// グループの開閉・表示項目の設定をlocalStorageへ永続化する（時間経過で変動する要素以外は
// 次回訪問時も同じ状態を保つ）。page.tsxのlayerVisibility（各レイヤーのON/OFF自体）は
// 既にuseStoredStateで永続化済みのため、ここではMapOverlayControls固有の「見せ方」の
// 設定（グループ本体の開閉・非表示に選んだメンバー/軸）だけを対象にする。
const MAP_OVERLAY_EXPANDED_GROUPS_STORAGE_KEY = "ridecompass:map-overlay-expanded-groups";
const MAP_OVERLAY_HIDDEN_IDS_STORAGE_KEY = "ridecompass:map-overlay-hidden-ids";

// 文字列の配列としてSetを保存・復元する共通ヘルパー。keyFilterで「保存・復元してよい値か」を
// 絞り込む（expandedIdsはGROUP_VISIBILITY_KEYSのみ、hiddenIdsは無条件で文字列なら許可）。
// 個々の凡例展開（member:/axis:/単独チップ/${groupKey}:legend）は「今ちょっと確認のために
// 開いている」一時的な状態であり、次回訪問時に勝手にポップアップが開いた状態で再現される
// のは望ましくないため、expandedIdsはグループ本体の開閉（GROUP_VISIBILITY_KEYS）だけを
// 保存対象にする（フィルタはserialize/deserializeの両方に必要。serializeだけで絞ると
// 過去に保存された壊れた値・旧仕様の値がdeserialize経由でそのまま復元されてしまうため）。
function serializeStringSet(v: ReadonlySet<string>, keyFilter: (key: string) => boolean): string {
  return JSON.stringify([...v].filter(keyFilter));
}
function deserializeStringSet(raw: string, keyFilter: (key: string) => boolean): Set<string> | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    return new Set(parsed.filter((key): key is string => typeof key === "string" && keyFilter(key)));
  } catch {
    return null;
  }
}

interface PanelRect {
  top: number;
  left: number;
  maxHeight: number;
  maxWidth: number;
}

// 凡例1カテゴリぶんのスウォッチ。太さ・線種で地図に反映するカテゴリ（entry.widthを持つ、
// 例:「道路の種類」）は、実寸の太さバーで示す（WidthSwatch.tsxと同じ理由）。バー自体も
// entry.colorで塗る（道路の種類も濃淡パレット（COLOR_HIGHWAY_*）を持つため、凡例と
// 地図の見た目を一致させる。路面の種類等widthを持たないカテゴリは色ドット）。
// WidthSwatch（MapLayersPanel）をそのまま使うことで、拡大率（WidthSwatch.tsx:
// DISPLAY_SCALE）を含め太さバーの描画を1箇所に集約する。
function renderLegendSwatch(entry: LegendEntry) {
  if (entry.width === undefined) {
    return <span className={styles.detailSwatchDot} style={{ background: entry.color }} />;
  }
  return <WidthSwatch width={entry.width} dashed={entry.dashed} color={entry.color} />;
}

// ▶を開いたときの内訳パネル。軸に属する全カテゴリを表示中/非表示の別なく並べる
// （「これだけで何が起きているか分かる」ことを優先する）。
// `axisId`を持つ軸はチェックボックス付き（サイドバーと同じ`LegendCheckboxList`）で描き、
// その場で表示/非表示を切り替えられる。持たない軸——配信元が色を焼き込み済みで
// カテゴリ単位の絞り込みができないラスタ系——は読み取り専用の一覧のまま、非表示分を
// 薄く見せる。
function renderLegendDetails(
  axes: readonly LegendFilterSummaryAxis[],
  onEntryToggle: (axisId: string, key: string) => void,
  onAxisSetHidden: (axisId: string, hiddenKeys: string[]) => void
) {
  return (
    <div className={styles.detailBody}>
      {axes.map((axis, axisIndex) => (
        <div key={axis.axisId ?? axis.label ?? axisIndex} className={styles.detailAxis}>
          {axis.axisId ? (
            // 一括ON/OFF。1つ残らず表示中のときだけチェックが入り、押すと全部隠す。
            // 1つでも隠れていれば未チェックで、押すと全部表示に戻る——狭い▶パネルに
            // 「すべて表示」「すべて隠す」の2ボタン（サイドバー側の形）を置く余地が
            // 無いため、1つのチェックボックスで両方向を兼ねる。
            <label className={styles.detailAxisHeader}>
              <Checkbox
                checked={axis.hiddenKeys.length === 0}
                onCheckedChange={() =>
                  onAxisSetHidden(
                    axis.axisId!,
                    axis.hiddenKeys.length === 0 ? axis.legend.map((entry) => entry.key) : []
                  )
                }
                aria-label={`${axis.label || "すべての項目"}をまとめて表示/非表示`}
              />
              <span className={styles.detailAxisLabel}>{axis.label || "すべて"}</span>
            </label>
          ) : (
            axis.label && <div className={styles.detailAxisLabel}>{axis.label}</div>
          )}
          {axis.axisId ? (
            <LegendCheckboxList
              legend={axis.legend}
              hiddenKeys={axis.hiddenKeys}
              onToggle={(key) => onEntryToggle(axis.axisId!, key)}
              listClassName={styles.detailList}
              rowClassName={styles.detailRow}
              rowFallbackClassName={styles.detailRowFallback}
              swatchClassName={styles.detailSwatchDot}
            />
          ) : (
            <ul className={styles.detailList}>
              {axis.legend.map((entry) => {
                const hidden = axis.hiddenKeys.includes(entry.key);
                // 「不明・他」等の受け皿カテゴリは他の項目と同列の判定値ではないため、区切り線で
                // 分離する（MapLayersPanel.tsxの同種の区切りと対応）。
                const rowClasses = [styles.detailRow];
                if (hidden) rowClasses.push(styles.detailRowHidden);
                if (entry.isFallback) rowClasses.push(styles.detailRowFallback);
                return (
                  <li key={entry.key} className={rowClasses.join(" ")}>
                    {renderLegendSwatch(entry)}
                    <span className={styles.detailRowLabel}>{entry.label}</span>
                    {hidden && <span className={styles.detailHiddenTag}>非表示</span>}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

// はみ出したアイコンは、はみ出した分だけ▼/▶ボタンでページ送りする方式にしてある。
// ボタンのクリックはtouch-actionの影響を受けない（touch-actionはpan/zoom等の
// "ジェスチャー"だけを制御する仕様で、タップ由来のclickは対象外）ため、地図との
// ピンチズーム競合を避けるための.iconChip自身のtouch-action: noneと衝突しない。
//
// 表示領域（overflow: hiddenで固定サイズ、スクロールバー自体が存在しない）の中身を
// translateX/Yで押し引きし、まだ隠れている分がある間だけ矢印ボタンを出す。
const PAGE_STEP_PX = 56; // 1回の送りで進める量（アイコン1個ぶん強、タイル+gapの実測値に近い）

function usePagedOverflow(axis: "x" | "y") {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const [offset, setOffset] = useState(0);
  const [maxOffset, setMaxOffset] = useState(0);

  const measure = useCallback(() => {
    const viewport = viewportRef.current;
    const track = trackRef.current;
    if (!viewport || !track) return;
    const viewportSize = axis === "x" ? viewport.clientWidth : viewport.clientHeight;
    const trackSize = axis === "x" ? track.scrollWidth : track.scrollHeight;
    const nextMax = Math.max(0, trackSize - viewportSize);
    setMaxOffset(nextMax);
    setOffset((prev) => Math.min(prev, nextMax));
  }, [axis]);

  // viewport（表示領域）・track（実コンテンツ）はコールバックrefのため、どちらが先に
  // アタッチされるか（マウント順）に依存せず、両方揃った時点でResizeObserverを張り直す
  // （どちらかがアンマウントされたら破棄する）。ResizeObserverを使うことで、軸の増減・
  // 展開/収納・フィルタ設定・画面回転等、はみ出し量に影響しうる変化を網羅的に検知する
  // （個々の変化のたびに手動でmeasure()を呼ぶ箇所を列挙する保守コストを避ける）。
  const rewireObserver = useCallback(() => {
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    const viewport = viewportRef.current;
    const track = trackRef.current;
    if (!viewport || !track) return;
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    observer.observe(track);
    resizeObserverRef.current = observer;
    measure();
  }, [measure]);

  // registerViewport/registerTrackはコールバックrefとしてJSXへ渡すため、useCallbackで
  // 参照を安定させないと親コンポーネントが再レンダーするたびに新しい関数が渡り、Reactが
  // ref変更とみなして毎回detach（null呼び出し）→reattachし、rewireObserver
  // （ResizeObserverの破棄・再構築）が無関係な再レンダーのたびに走ってしまう。
  const registerViewport = useCallback(
    (el: HTMLDivElement | null) => {
      viewportRef.current = el;
      rewireObserver();
    },
    [rewireObserver],
  );
  const registerTrack = useCallback(
    (el: HTMLDivElement | null) => {
      trackRef.current = el;
      rewireObserver();
    },
    [rewireObserver],
  );

  const pageForward = () => setOffset((prev) => Math.min(maxOffset, prev + PAGE_STEP_PX));
  const pageBackward = () => setOffset((prev) => Math.max(0, prev - PAGE_STEP_PX));
  const reset = () => setOffset(0);

  return {
    registerViewport,
    registerTrack,
    offset,
    pageForward,
    pageBackward,
    reset,
    hasMore: offset < maxOffset,
    hasLess: offset > 0,
  };
}

// ページ送りボタンは押しっぱなしで連続送りできる。ワンタップ=1ステップのみだと、
// 複数ステップ送るのに小さい丸ボタン（1.6rem四方）へ連打が必要になり、hasMore/hasLessの
// 変化でボタン自体の出現・消滅が起きて位置がわずかに動くため、タップが外れて地図
// キャンバス側の誤操作（ダブルタップズーム等）を誘発しやすい。押しっぱなしでの連続送りは
// この連打そのものを不要にする。
//
// クリック（マウス・タッチ・キーボードのEnter/Spaceいずれも最終的にonClickへ集約される）
// を「1回押した分」の唯一の実行経路として維持しつつ、pointerdown/upだけで「長押し中の
// 追加リピート」を制御する。素早いワンタップはpointerdown後すぐにpointerupするため
// delayMs待ちのタイマーが発火する前に解除され、onClickの1回だけが実行される。長押し時
// だけタイマー発火後にintervalMsごとの追加ステップが走る。長押し後に指を離すと通常どおり
// clickイベントも発火するが、直前にリピートが一度でも発火していれば「既に十分送った後の
// 余計な1回」になるためheldRefで判定して無視する。
// canRepeatは呼び出し側のhasMore/hasLessをそのまま渡す。ページ送りが上限/下限に達すると
// 呼び出し元のJSXがボタン自体を描画しなくなり（押している最中でも起こりうる）、その
// 瞬間pointerup/leaveがこの要素へ届かない可能性があるため、タイマー発火のたびに
// canRepeatRef（render毎に最新値へ更新）を確認し、falseならタイマー自身を止めて
// 放置されたintervalが動き続けないようにする。
function useHoldRepeat(action: () => void, canRepeat: boolean, delayMs = 450, intervalMs = 120) {
  const actionRef = useRef(action);
  const canRepeatRef = useRef(canRepeat);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // 直前のpointerdown長押しで実際にリピートが1回でも発火したか（発火直後のclickを
  // 抑止するための判定に使う）。
  const heldRef = useRef(false);

  const clearTimers = () => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  // ref書き込みはレンダー中に行えない（react-hooks/refsルール）ため、コミット後の
  // 副作用として同期する。setTimeout/setIntervalのコールバックは複数レンダーを
  // またいで生存するため、古いレンダーのaction/canRepeatを掴んだままにならないよう
  // 常に最新値を参照できるようにする。
  useEffect(() => {
    actionRef.current = action;
    canRepeatRef.current = canRepeat;
  });

  // グループの折りたたみ等でボタン自体がアンマウントされてもタイマーが残り続けない
  // ようにする。
  useEffect(() => clearTimers, []);

  const fireIfPossible = () => {
    if (!canRepeatRef.current) {
      clearTimers();
      return;
    }
    actionRef.current();
  };

  const handlePointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return; // 主ボタン（左クリック・タッチ・ペン）以外は対象外
    clearTimers();
    heldRef.current = false;
    timeoutRef.current = setTimeout(() => {
      heldRef.current = true;
      fireIfPossible();
      intervalRef.current = setInterval(fireIfPossible, intervalMs);
    }, delayMs);
  };

  const stop = () => clearTimers();

  const handleClick = () => {
    if (heldRef.current) {
      heldRef.current = false;
      return;
    }
    actionRef.current();
  };

  return {
    onPointerDown: handlePointerDown,
    onPointerUp: stop,
    onPointerLeave: stop,
    onPointerCancel: stop,
    onClick: handleClick,
  };
}

// チップ本体の共通コンポーネント。単独チップ（グループ化されないレイヤー）とグループ
// チップ（複数レイヤーを1つのカテゴリへ束ねたもの）の両方で同じ「本体ボタン+隣の
// ▶/▼ボタン」の2ボタン構成を使う。単独チップは本体タップ=ON/OFF・▶/▼=凡例展開の
// 別アクションだが、グループチップは束ねた個々のレイヤーのON/OFFが一意に決まらず
// 一括ON/OFFは設けない（誤操作リスク）ため、本体タップも展開トグルと同じ展開/収納に
// する（呼び出し側でonTapにonExpandToggleと同じ関数を渡す）。
// MapOverlayControlsの内側に定義するとレンダーのたびに新しい関数（＝別のコンポーネント型）
// になり、Reactが毎回アンマウント/再マウントしてDOMノードの同一性が失われる（展開直後に
// 別要素へ差し替わり、テストや実機のフォーカス・aria状態が壊れる）ため、モジュール直下の
// 安定した関数として定義する。panelRects/rowRefsは親の状態のためprops経由で受け取る。
// groupTint（MapOverlayGroup）→CSSクラスの対訳表。ChipButtonはチップ1個ごとに呼ばれるため
// モジュール直下の定数として1回だけ作る（レンダーごとの再生成を避ける）。
const GROUP_TINT_CLASSES: Record<MapOverlayGroup, string> = {
  road: styles.iconChipGroupRoad,
  environment: styles.iconChipGroupEnvironment,
  spot: styles.iconChipGroupSpot,
};

function ChipButton({
  Icon,
  label,
  chipLabel,
  active,
  disabled,
  title,
  onTap,
  canExpand,
  isExpanded,
  onExpandToggle,
  panelContent,
  panelRect,
  registerRow,
  expandDirection = "right",
  expandViaSelf,
  groupTint,
  dataStatus,
}: {
  Icon: (props: { size?: number }) => ReactElement;
  label: string;
  chipLabel: string;
  active: boolean;
  disabled?: boolean;
  title?: string;
  onTap: () => void;
  canExpand: boolean;
  isExpanded: boolean;
  onExpandToggle: () => void;
  panelContent: ReactElement;
  panelRect: PanelRect | undefined;
  registerRow: (el: HTMLDivElement | null) => void;
  /** 展開方向。
   * "down"（▼→▲、行の直下へ通常のドキュメントフローで展開）と"right"（▶→▽回転、
   * document.bodyへポータルしてposition: fixedで行の右に浮かせる。個々のメンバータイル・
   * 単独チップ（ルート等）の凡例展開はこちら）は自身がpanelContentを描画する。
   * "flat"（観測グループ本体、▼→▲）は、独立カード（サブフレーム）に閉じ込めず、地図の
   * チップ列と地続きに展開する。矢印の見た目は"down"と同じだが、自身は内訳を描画しない。
   * 呼び出し元（MapOverlayControls本体）がこのボタンの直後にメンバーをchipRowの直接の
   * 子として差し込む。 */
  expandDirection?: "right" | "down" | "flat";
  /** 観測グループ本体だけに立てる印。true のときは隣接する▶/▼の丸トグルボタン自体を
   * 描画せず、本体ボタンのactive見た目とaria-expandedで開閉状態を表す。本体タップは
   * 元々onTapにtoggleExpandedと同じ関数を渡しているため、押下対象は変わらない
   * （挙動はそのまま、見た目と意味づけだけを変える）。単独チップ（ON/OFFと凡例展開が
   * 別アクション）はこの対象外で、独立した丸トグルを持つ。active見た目には
   * .iconChipActive（青、ON/OFFチップと同じ＝「地図に反映されている」の意味）ではなく
   * .iconChipExpanded（展開中は薄色でON、展開解除は灰色でOFFを示す。CSS側は
   * .groupHeaderChipマーカーとgroupTintの組み合わせで折りたたみ=灰色・展開=そのグループの
   * 薄色塗りを出す）を使う。見出し自体はメンバーのON/OFFを表さないため、青
   * （.iconChipActive）を使うと「このグループの内容が地図に出ている」と誤読されてしまう。 */
  expandViaSelf?: boolean;
  /** 最上位グループ（道路/環境/スポット）の色分け。未指定＝どのグループにも属さない
   * 単独チップ（ルート等）は無色のまま。 */
  groupTint?: MapOverlayGroup;
  /** レイヤーのデータ取得状態。LayerChip（サイドバー）と同じ
   * 「active && dataStatus != null」の間だけアイコン右上へ小さな状態ドットを添える。 */
  dataStatus?: LayerDataStatus;
}) {
  const arrowGlyph = expandDirection === "right" ? "▶" : "▼";
  const arrowOpenClass = expandDirection === "right" ? styles.expandArrowOpen : styles.expandArrowDownOpen;
  const isActiveVisual = expandViaSelf ? isExpanded : active;
  const groupTintClass = groupTint ? GROUP_TINT_CLASSES[groupTint] : "";
  // グループ見出し（観測、expandViaSelf=true）だけに付く印。展開中は薄色でON、展開解除は
  // 灰色でOFFを示す。メンバータイルは常に枠線だけグループ色のままにしたいため、見出しだけを
  // 区別するマーカークラスをCSS側のコンパウンドセレクタ（.groupHeaderChip.iconChipGroupRaw
  // 等）で使う。
  const headerMarkerClass = expandViaSelf ? styles.groupHeaderChip : "";
  // レイヤーのデータ取得状態。LayerChip.tsxと同じ「ONの間だけ」判定（OFF中はチップ自体の
  // 見た目でON/OFFが分かるため出さない）。
  const showStatusDot = active && dataStatus != null;
  const statusLabel = dataStatus ? LAYER_DATA_STATUS_LABELS[dataStatus] : undefined;
  const chipTitle = showStatusDot && statusLabel ? (title ? `${title}（${statusLabel}）` : statusLabel) : title;
  return (
    <div ref={registerRow} className={styles.chipRowItem}>
      <div className={styles.iconToggleRow}>
        <button
          type="button"
          aria-pressed={expandViaSelf ? undefined : active}
          aria-expanded={expandViaSelf ? isExpanded : undefined}
          disabled={disabled}
          title={chipTitle}
          onClick={onTap}
          className={
            isActiveVisual
              ? `${styles.iconChip} ${groupTintClass} ${headerMarkerClass} ${expandViaSelf ? styles.iconChipExpanded : styles.iconChipActive}`
              : `${styles.iconChip} ${groupTintClass} ${headerMarkerClass}`
          }
        >
          <Icon />
          {/* 状態→CSSクラスの対訳表をコンポーネント内に持たず、LayerDataStatusの値と
              そろえたクラス名（MapOverlayControls.module.css: iconStatusDot_loading等）を
              直接組み立てて参照する（LayerChip.tsxと同じ設計原則8）。 */}
          {showStatusDot && dataStatus && (
            <span aria-hidden="true" className={`${styles.iconStatusDot} ${styles[`iconStatusDot_${dataStatus}`]}`} />
          )}
          <span className={styles.iconLabel}>{chipLabel}</span>
        </button>
        {canExpand && !expandViaSelf && (
          <button
            type="button"
            onClick={onExpandToggle}
            aria-expanded={isExpanded}
            aria-label={`${label}の凡例を${isExpanded ? "隠す" : "表示"}`}
            title="凡例を表示"
            className={isExpanded ? `${styles.expandToggle} ${styles.expandToggleActive}` : styles.expandToggle}
          >
            <span aria-hidden="true" className={isExpanded ? `${styles.expandArrow} ${arrowOpenClass}` : styles.expandArrow}>
              {arrowGlyph}
            </span>
          </button>
        )}
      </div>
      {isExpanded &&
        (expandDirection === "right" || expandDirection === "down") &&
        panelRect &&
        createPortal(
          <div
            className={styles.detailPanel}
            style={{ top: panelRect.top, left: panelRect.left, maxWidth: panelRect.maxWidth, maxHeight: panelRect.maxHeight }}
          >
            {panelContent}
          </div>,
          document.body
        )}
    </div>
  );
}

// 地図の上に重ねるのは「地図を見ながら頻繁に切り替える」ON/OFFチップと、▶で開く凡例
// だけ。絞り込みの編集・色分けモードの選択など「変更を伴う設定」はすべてサイドバー
// （MapLayersPanel）で行う（地図上の▶はあくまで確認用）。このコンポーネントはレイヤー
// 固有の知識を持たない汎用の描画係で、レイヤーが増えてもここは変更不要（mapLayers.tsの
// コメント参照）。
export default function MapOverlayControls({
  layers,
  onToggle,
  onLegendEntryToggle,
  onLegendAxisSetHidden,
}: MapOverlayControlsProps) {
  // 凡例は既定で非表示にし、チップ横の▶を押したレイヤーのぶんだけ薄いポップオーバーで
  // 出す（常時表示すると地図の視界を圧迫するため）。開閉はキーのSetで個別管理する。
  // キーはレイヤーID（単独チップ）・`member:${id}`（道路/環境/スポットグループの
  // メンバー）・グループキー`group:road`/`group:environment`/`group:spot`（グループ本体の
  // 開閉）・`${groupKey}:legend`（アイコンの意味凡例）のいずれか。
  // グループ本体の開閉はfloatingパネルを持たない（memberの一覧をchipRowへインラインで
  // 差し込むだけ）ため複数グループを同時に開いても重ならないが、それ以外
  // （member:/単独チップ/${groupKey}:legend）はdocument.bodyへポータルするfloatingパネルの
  // ため、複数同時に開くと近接する行同士でパネルが重なり両方とも判読不能になる
  // （降水ナウキャストと風の凡例を続けて開いた場合等）。
  // toggleExpanded側でfloatingパネル系のキーは排他（新しく開いたら他を閉じる）にする。
  // グループ本体の開閉（GROUP_VISIBILITY_KEYS）だけをlocalStorageへ永続化する（上記
  // MAP_OVERLAY_EXPANDED_GROUPS_STORAGE_KEYのコメント参照。floatingパネル系のキーは
  // 保存対象に含めない一時的な状態のまま）。
  const [expandedIds, setExpandedIds] = useStoredState<ReadonlySet<string>>(
    MAP_OVERLAY_EXPANDED_GROUPS_STORAGE_KEY,
    new Set(),
    {
      serialize: (v) => serializeStringSet(v, (key) => GROUP_VISIBILITY_KEYS.has(key)),
      deserialize: (raw) => deserializeStringSet(raw, (key) => GROUP_VISIBILITY_KEYS.has(key)),
    }
  );
  // 内訳パネルの表示位置（viewport基準のpx）。アイコン列（chipRow）は縦スクロール可能
  // （レイヤー数が多い画面向け）だが、CSSの仕様上overflow-yを指定するとoverflow-xも
  // 暗黙にauto扱いになり、パネルをposition: absoluteでこの行の右へはみ出させる方式だと
  // chipRowにクリップされて何も見えなくなる。document.bodyへポータルし、押した瞬間の
  // 行の実際の画面位置をJSで測ってposition: fixedで配置することでクリップを回避する。
  const [panelRects, setPanelRects] = useState<Partial<Record<string, PanelRect>>>({});
  const rowRefs = useRef<Partial<Record<string, HTMLDivElement | null>>>({});
  // .chipRowの、はみ出し分のページ送り（usePagedOverflow参照）。JSXのprops側で
  // オブジェクトのメンバー式（例: chipRowPaging.registerTrack）を直接参照すると、
  // react-hooks/refs lintルールが「レンダー中のref参照」と誤検知するため（返り値にref操作を
  // 含む関数を持つカスタムフックのため保守的に判定される）、ここで一度分割代入し裸の変数として
  // JSXへ渡す。
  const {
    registerViewport: registerChipRowViewport,
    registerTrack: registerChipRowTrack,
    offset: chipRowOffset,
    pageForward: pageChipRowForward,
    pageBackward: pageChipRowBackward,
    hasMore: chipRowHasMore,
    hasLess: chipRowHasLess,
  } = usePagedOverflow("y");

  // 道路/環境/スポットグループで「表示する項目を選ぶ」設定。グループ見出しのⓘボタンから、
  // 配下メンバーの表示・非表示を選べる設定パネルを開く。グループ本体を開くと、ここで
  // 非表示に選んだもの以外だけが並ぶ（絞り込みは各グループ内で完結し、既定＝何も非表示に
  // 選んでいない状態では全件表示）。キーは`${scope}:${memberId}`（scope="road"|
  // "environment"|"spot"、グループ間でIDが衝突しても名前空間で区別できるようにする）。
  // localStorageへ永続化する（レイヤー構成が変わり存在しないIDが残っても、
  // renderVisibilitySettings側は現在渡された項目とのマッチングでしか使わないため実害はない）。
  const [hiddenIds, setHiddenIds] = useStoredState<ReadonlySet<string>>(
    MAP_OVERLAY_HIDDEN_IDS_STORAGE_KEY,
    new Set(),
    {
      serialize: (v) => serializeStringSet(v, () => true),
      deserialize: (raw) => deserializeStringSet(raw, () => true),
    }
  );

  // 非表示に選んだ項目に表示中のレイヤーが紐づいている場合、その場でレイヤー自体も
  // OFFにする。設定パネルからチップが消えた後もレイヤーが地図に描画され続け、かつ
  // チップが無いのでOFFにする手段も無くなる、という状態を防ぐ。逆方向（非表示解除＝
  // 再表示）はチップを選べるようにするだけで、レイヤーを自動でONにはしない
  // （「隠す/出す」はチップの見た目の設定であり、ON/OFFの意思決定はユーザーが個別に行う
  // という既存方針、member.onはこの関数の外＝呼び出し元のonTapが唯一の変更経路のまま）。
  function toggleHidden(hiddenKey: string, layerId: MapLayerId | undefined, isOn: boolean | undefined) {
    const isCurrentlyHidden = hiddenIds.has(hiddenKey);
    setHiddenIds((prev) => {
      const next = new Set(prev);
      if (isCurrentlyHidden) {
        next.delete(hiddenKey);
      } else {
        next.add(hiddenKey);
      }
      return next;
    });
    if (!isCurrentlyHidden && layerId && isOn) {
      onToggle(layerId, false);
    }
  }

  // 「表示する項目を選ぶ」設定パネル内、各項目の情報アイコンで説明文(panelHint)を
  // 開閉する状態。個々の凡例展開（member:/axis:等）と同じく「今ちょっと確認のために
  // 開いている」一時的な状態のため、localStorageへは永続化しない
  // （serializeStringSet/deserializeStringSetの対象に含めない）。キーは
  // `${scope}:${item.key}`でhiddenIdsと同じ名前空間の作り方に揃える。
  const [openInfoKeys, setOpenInfoKeys] = useState<ReadonlySet<string>>(new Set());
  function toggleInfo(key: string) {
    setOpenInfoKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  // anchor="right"（行の右へ）/"down"（行の直下へ）。いずれもdocument.bodyへポータルして
  // position: fixedで浮かせる（下記ChipButton参照）。chipRowのoverflow-y: auto
  // （＝暗黙にoverflow-xもauto）の内側でposition: absolute配置すると、パネルが
  // chipRowのスクロール可能領域に算入されてしまい、パネル1個ぶん右にはみ出ただけで
  // chipRowに横スクロールバーが出てしまうため、ポータルで完全にchipRowの外へ出す。
  const toggleExpanded = (id: string, anchor: "right" | "down" = "right") => {
    const isOpening = !expandedIds.has(id);
    if (isOpening) {
      const row = rowRefs.current[id];
      if (row) {
        const rect = row.getBoundingClientRect();
        const top = anchor === "down" ? rect.bottom + PANEL_GAP_PX : rect.top;
        const rawLeft = anchor === "down" ? rect.left : rect.right + PANEL_GAP_PX;
        // 画面右端からのはみ出し対策。画面右端に近いタイル（推定グループ末尾の軸等）だと
        // rawLeftが既にビューポート
        // 右端に近く、下のmaxWidth計算のMath.max(160, ...)フロアにより最小幅160pxが
        // 強制されてもleft自体を動かさないままだとパネルがビューポート外へはみ出して
        // しまう。leftをこの分だけ画面内へ押し戻し、パネルが必ずMIN_PANEL_WIDTH_PXぶん
        // 画面内に収まるようにする（画面幅自体がそれより狭い極端なケースはPANEL_GAP_PX
        // まで詰める）。
        const left = Math.min(rawLeft, Math.max(PANEL_GAP_PX, window.innerWidth - MIN_PANEL_WIDTH_PX - PANEL_GAP_PX));
        // 画面下端からのはみ出し対策。position: fixedのためtopが画面下端に近いと、
        // CSS既定の最大高さ（16rem）ぶんが
        // ビューポート外へはみ出してしまい、パネル自身のoverflow-y: autoでスクロールしても
        // ビューポート外の部分には原理的に到達できない（fixed要素はドキュメントのスクロール
        // 領域に算入されないため）。横方向のmaxWidthを画面幅から逆算するのと同じ考え方で、
        // 利用可能な高さがCSS既定の上限より狭ければmaxHeightを縮め、パネル自体をその場の
        // 残りスペースに収める（縮めた分はパネル自身のoverflow-y: autoで内部スクロール）。
        const availableHeight = window.innerHeight - top - PANEL_GAP_PX;
        const maxHeight = Math.max(120, Math.min(DETAIL_PANEL_MAX_HEIGHT_PX, availableHeight));
        setPanelRects((prev) => ({
          ...prev,
          [id]: { top, left, maxWidth: Math.max(MIN_PANEL_WIDTH_PX, window.innerWidth - left - PANEL_GAP_PX), maxHeight },
        }));
      }
    }
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        // floatingパネル系のキー（member:/axis:/単独チップ/${groupKey}:legend）は排他:
        // 新しく開くキーがグループ本体の開閉（GROUP_VISIBILITY_KEYS）でなければ、他の
        // floatingパネル系キーをすべて閉じてから開く。グループ本体同士はfloatingパネルを
        // 持たないため対象外のまま複数同時に開ける。
        if (!GROUP_VISIBILITY_KEYS.has(id)) {
          for (const existing of next) {
            if (!GROUP_VISIBILITY_KEYS.has(existing)) next.delete(existing);
          }
        }
        next.add(id);
      }
      return next;
    });
  };

  // ページ送り（▲▼/◀▶）を押すと、position: fixedの凡例パネルは行に追従できず表示が
  // ずれたままになるため閉じる。ページ送り自体はグループを開いたまま行いたい操作のため、
  // グループ自体の展開状態（GROUP_VISIBILITY_KEYS）は対象にせず、フローティングパネル系の
  // キー（member:/axis:/単独チップ/${groupKey}:legend）だけを閉じる。
  const closeFloatingPanels = () => {
    setExpandedIds((prev) => {
      const next = new Set([...prev].filter((key) => GROUP_VISIBILITY_KEYS.has(key)));
      return next.size === prev.size ? prev : next;
    });
  };

  // ▲▼/◀▶それぞれの「押しっぱなしで連続送り」（useHoldRepeat参照）。
  // closeFloatingPanels()はページ送りのたびに呼ぶ（何も開いていなければsetExpandedIdsが
  // 同一参照を返すため再レンダーは発生せず、繰り返し呼んでも無害）。
  const chipRowBackwardHold = useHoldRepeat(() => {
    closeFloatingPanels();
    pageChipRowBackward();
  }, chipRowHasLess);
  const chipRowForwardHold = useHoldRepeat(() => {
    closeFloatingPanels();
    pageChipRowForward();
  }, chipRowHasMore);

  // 観測グループの1メンバー。推定グループの軸タイルと同じ「アイコン+略名の四角タイル+
  // 隣に付随する凡例展開ボタン」をChipButtonの再利用で表す（見た目を全要素で統一する）。
  // 観測グループ自体は▼縦積み（ChipButtonのexpandDirection="down"）のため、メンバー
  // 個々の凡例は▶で右へ展開する（縦に並んだ他のメンバーと重ならないよう、グループ本体と
  // 直交する向きにする）。凡例を持つメンバーはON/OFFに関わらず常に▶が付く（推定グループの
  // 軸タイルがON/OFFに関わらず▼を出すのと揃える。legendDetailsはレイヤー定義由来の固定
  // 内容でありON/OFFで内容が変わらないため、OFF中に「オンにすると何が出るか」を先に
  // 確認できる利点もある）。
  // legendDetailsが空でもsummaryがあれば▶を出す（道路種別・路面はregionZoomTooWide中
  // legendDetailsが空配列になる＝ズームインを促す案内文（summary、page.tsx:
  // roadTypeSummary/roadSurfaceSummary参照）だけが内容になる想定のため、canExpandを
  // legendDetailsの有無だけで判定すると▶自体が消えて案内文を開けなくなる。単独チップ側
  // （本ファイル末尾のcanExpand= hasLegendDetails || Boolean(layer.summary)）と同じ
  // 判定へ揃える）。
  function renderRawMemberTile(member: OverlayLayerChip, groupTint: "road" | "environment" | "spot") {
    const key = `member:${member.id}`;
    const Icon = LAYER_ICONS[member.id] ?? AxisRampIcon;
    const hasLegend = Boolean(member.legendDetails && member.legendDetails.length > 0);
    const canExpand = Boolean(!member.disabled && (hasLegend || member.summary));
    return (
      <ChipButton
        key={key}
        Icon={Icon}
        label={member.label}
        chipLabel={member.chipLabel ?? member.label}
        active={Boolean(member.on && !member.disabled)}
        disabled={member.disabled}
        title={member.title}
        onTap={() => onToggle(member.id, !member.on)}
        canExpand={canExpand}
        isExpanded={canExpand && expandedIds.has(key)}
        onExpandToggle={() => toggleExpanded(key)}
        expandDirection="right"
        groupTint={groupTint}
        dataStatus={member.dataStatus}
        panelContent={
          canExpand ? (
            hasLegend ? (
              renderLegendDetails(member.legendDetails!, onLegendEntryToggle, onLegendAxisSetHidden)
            ) : (
              <p className={styles.detailNotice}>{member.summary}</p>
            )
          ) : (
            <></>
          )
        }
        panelRect={panelRects[key]}
        registerRow={(el) => {
          rowRefs.current[key] = el;
        }}
      />
    );
  }

  // 「観測データ」グループの▼内容: 独立したカード（サブフレーム）に閉じ込めず、
  // chipRowの直接の子として観測チップの直後に地続きで差し込む。category小見出し
  // （道路状態・交通・安全）は表示せず、MAP_LAYER_CATEGORY_ORDER順のフラットな一覧に
  // する（順序自体はcategory順を保つが、見出しテキストは出さない）。メンバー本体
  // （renderRawMemberTile）はChipButtonが自前でchipRowItemを返すため、ここでは
  // 追加のラッパーを挟まずそのままchipRowの子として返す。
  function orderObservedMembers(members: readonly OverlayLayerChip[]): readonly OverlayLayerChip[] {
    return MAP_LAYER_CATEGORY_ORDER.flatMap((category) => members.filter((m) => m.category === category));
  }

  // メンバー増加で展開直後に画面下端を超えて見切れることを避けるため、Ⓘの設定パネル
  // （renderVisibilitySettings）で非表示に選んだメンバーはここで除外する。groupTint/scopeは
  // 常に同じグループ値（"road"|"environment"|"spot"のいずれか）を渡すため1引数に統合してある。
  function renderObservedMemberRows(
    members: readonly OverlayLayerChip[],
    group: "road" | "environment" | "spot"
  ): ReactElement[] {
    return orderObservedMembers(members)
      .filter((member) => !hiddenIds.has(`${group}:${member.id}`))
      .map((member) => renderRawMemberTile(member, group));
  }

  // 道路/環境/スポットグループ見出しの「表示する項目を選ぶ」設定パネル。各項目に表示/
  // 非表示のチェックボックスを持たせ、ここで選んだ項目だけがグループ展開時に並ぶ。
  // 折りたたみ時だけ見出しの脇に出す独立した入口にする（展開後は絞り込み済みの項目自体の
  // アイコンが並ぶため、その場に同じ一覧をもう一度出すと二重表示になってかえって読み
  // にくい）。呼び出し側（chipGroups.flatMapの中）が `!isExpanded` のときだけこの関数を
  // 呼ぶことで担保する。ChipButtonは使わず、同じ「小さい丸ボタン+document.bodyへ
  // ポータルする内訳パネル」の仕組み（toggleExpanded/panelRects/rowRefs）を直接流用する
  // 軽量な専用実装にする。キーは`${groupKey}:legend`でexpandedIds等の既存Setにそのまま
  // 同居できる。
  function renderVisibilitySettings(
    groupKey: string,
    groupLabel: string,
    scope: MapOverlayGroup,
    items: readonly {
      key: string;
      Icon: (props: { size?: number }) => ReactElement;
      label: string;
      /** 対応するレイヤーID（あれば）。非表示に選んだ瞬間そのレイヤーがONならOFFにするために使う
       * （toggleHidden参照）。推定グループの専用レイヤーを持たない軸（勾配・舗装質・夜間）は
       * undefinedのまま渡す。 */
      layerId?: MapLayerId;
      on?: boolean;
      /** 行の右側に個別の情報アイコンを出し、押すと表示する説明文。未設定なら情報
       * アイコン自体を出さない。 */
      description?: string;
    }[]
  ) {
    const legendKey = `${groupKey}:legend`;
    const isOpen = expandedIds.has(legendKey);
    const rect = panelRects[legendKey];
    return (
      <div
        key={legendKey}
        ref={(el) => {
          rowRefs.current[legendKey] = el;
        }}
        className={styles.chipRowItem}
      >
        <div className={styles.iconToggleRow}>
          <button
            type="button"
            onClick={() => toggleExpanded(legendKey, "down")}
            aria-expanded={isOpen}
            aria-label={`${groupLabel}の表示項目を${isOpen ? "隠す" : "設定"}`}
            title="表示する項目を選ぶ"
            className={isOpen ? `${styles.expandToggle} ${styles.expandToggleActive}` : styles.expandToggle}
          >
            <InfoIcon size={12} />
          </button>
        </div>
        {isOpen &&
          rect &&
          createPortal(
            <div className={styles.detailPanel} style={{ top: rect.top, left: rect.left, maxWidth: rect.maxWidth, maxHeight: rect.maxHeight }}>
              <ul className={styles.detailList}>
                {items.flatMap((item) => {
                  const hiddenKey = `${scope}:${item.key}`;
                  const isHidden = hiddenIds.has(hiddenKey);
                  // infoKeyはhiddenKeyと同じ`${scope}:${item.key}`名前空間だが別のSet
                  // （openInfoKeys）で管理するため、非表示設定と情報アイコンの開閉は
                  // 互いに影響しない。
                  const infoKey = hiddenKey;
                  const isInfoOpen = openInfoKeys.has(infoKey);
                  const row = (
                    <li key={item.key} className={styles.detailRow}>
                      <button
                        type="button"
                        onClick={() => toggleHidden(hiddenKey, item.layerId, item.on)}
                        aria-pressed={!isHidden}
                        aria-label={`${item.label}を${isHidden ? "表示する" : "表示しない"}`}
                        className={
                          isHidden
                            ? styles.visibilityCheckbox
                            : `${styles.visibilityCheckbox} ${styles.visibilityCheckboxChecked}`
                        }
                      >
                        {isHidden ? "" : "✓"}
                      </button>
                      <item.Icon size={16} />
                      <span className={styles.detailRowLabel}>{item.label}</span>
                      {item.description && (
                        <button
                          type="button"
                          onClick={() => toggleInfo(infoKey)}
                          aria-expanded={isInfoOpen}
                          aria-label={`${item.label}の説明を${isInfoOpen ? "隠す" : "表示"}`}
                          title="説明を表示"
                          className={
                            isInfoOpen
                              ? `${styles.visibilityInfoButton} ${styles.visibilityInfoButtonActive}`
                              : styles.visibilityInfoButton
                          }
                        >
                          <InfoIcon size={12} />
                        </button>
                      )}
                    </li>
                  );
                  if (!item.description || !isInfoOpen) return [row];
                  return [
                    row,
                    <li key={`${item.key}:info`} className={styles.visibilityInfoRow}>
                      <p className={styles.detailNotice}>{item.description}</p>
                    </li>,
                  ];
                })}
              </ul>
            </div>,
            document.body
          )}
      </div>
    );
  }

  // グループ見出しをタップしたとき（展開↔折りたたみのどちらの向きでも）、開いたままの
  // 凡例（上のrenderGroupLegendToggle）があれば閉じる。展開後は凡例ボタン自体を描画しない
  // ため見た目には現れないが、開いたままのbooleanを放置すると、後で見出しを再度タップして
  // 折りたたみに戻したときに、ユーザーがⓘを押していないのに凡例が開いたまま再出現して
  // しまう（stateがexpandedIdsに残り続けるため）。見出しタップのたびに明示的に閉じることで
  // 「凡例は自分でⓘを押したときだけ開く」という状態を保つ。
  function closeGroupLegend(groupKey: string) {
    const legendKey = `${groupKey}:legend`;
    setExpandedIds((prev) => {
      if (!prev.has(legendKey)) return prev;
      const next = new Set(prev);
      next.delete(legendKey);
      return next;
    });
  }

  const chipGroups = buildChipGroups(layers);

  return (
    <div className={styles.wrapper}>
      {chipRowHasLess && (
        <button
          type="button"
          className={styles.pageButton}
          {...chipRowBackwardHold}
          aria-label="上を表示"
          title="上を表示"
        >
          ▲
        </button>
      )}
      <div className={styles.chipRowViewport} ref={registerChipRowViewport}>
        <div
          className={styles.chipRow}
          ref={registerChipRowTrack}
          style={{ transform: `translateY(-${chipRowOffset}px)` }}
        >
        {chipGroups.flatMap((group) => {
          // 道路/環境/スポットグループは「▼縦積み・地続き展開」の構成を共有する。▼を
          // 開くと、独立したカードに閉じ込めず、メンバーをchipRowの直接の子として
          // グループチップの直後に地続きで差し込む。ChipButton自身はexpandDirection="flat"で
          // ▼矢印の見た目だけを持ち、内訳は描画しない（renderObservedMemberRowsを別途
          // sibling要素として返す）。3グループとも見た目・挙動が完全に同一のため、
          // 1つの分岐にまとめる。
          const flatGroup =
            group.key === "group:road" ? "road" : group.key === "group:environment" ? "environment" : group.key === "group:spot" ? "spot" : undefined;
          if (flatGroup) {
            const RepresentativeIcon = MAP_OVERLAY_GROUP_ICONS[flatGroup];
            const isExpanded = expandedIds.has(group.key);
            const label = MAP_OVERLAY_GROUP_LABELS[flatGroup];
            const chipLabel = MAP_OVERLAY_GROUP_CHIP_LABELS[flatGroup];
            const header = (
              <ChipButton
                key={group.key}
                Icon={RepresentativeIcon}
                label={label}
                chipLabel={chipLabel}
                // 評価軸グループと同じ理由（上のコメント参照）でactiveは無視され、見出しの
                // active見た目は展開状態(isExpanded)から決まる。
                active={false}
                title={`${label}[${group.members.length}件をタップで一覧]`}
                onTap={() => {
                  toggleExpanded(group.key);
                  closeGroupLegend(group.key);
                }}
                canExpand
                isExpanded={isExpanded}
                onExpandToggle={() => toggleExpanded(group.key)}
                expandDirection="flat"
                expandViaSelf
                groupTint={flatGroup}
                panelContent={<></>}
                panelRect={panelRects[group.key]}
                registerRow={(el) => {
                  rowRefs.current[group.key] = el;
                }}
              />
            );
            // 評価軸グループと同じ理由（上のコメント参照）で、折りたたみ中だけ見出しの脇に
            // 「アイコンの意味」凡例の入口を出し、展開後は消す。ラッパーdivのkeyは折りたたみ/
            // 展開のどちらでも同じ値に固定し、headerのDOMノードを保つ（評価軸グループと
            // 同じ理由）。展開時は元どおりメンバーを縦積みするため.observedExpandedColumn
            // （chipRowと同じcolumn flex）、折りたたみ時は見出し+凡例トグルの横並びのため
            // .headerLegendRowを使う。
            return [
              <div
                key={`${group.key}:row`}
                className={isExpanded ? styles.observedExpandedColumn : styles.headerLegendRow}
              >
                {header}
                {isExpanded
                  ? renderObservedMemberRows(group.members, flatGroup)
                  : renderVisibilitySettings(
                      group.key,
                      label,
                      flatGroup,
                      orderObservedMembers(group.members).map((member) => ({
                        key: member.id,
                        Icon: LAYER_ICONS[member.id] ?? AxisRampIcon,
                        label: member.chipLabel ?? member.label,
                        layerId: member.id,
                        on: member.on,
                        description: member.panelHint,
                      }))
                    )}
              </div>,
            ];
          }

          // どのグループにも属さない単独チップ（route等）。
          const layer = group.members[0];
          // 二次軸rampレイヤーはレジストリ生成物から自動で増えるためレイヤーIDごとの
          // 専用アイコンを持たず、共通のAxisRampIconへフォールバックする
          // （undefinedのままJSXへ渡すとReactが「Element type is invalid」で落ちる）。
          const Icon = LAYER_ICONS[layer.id] ?? AxisRampIcon;
          const hasLegendDetails = Boolean(layer.legendDetails && layer.legendDetails.length > 0);
          const canExpand = layer.on && !layer.disabled && (hasLegendDetails || Boolean(layer.summary));
          const isExpanded = canExpand && expandedIds.has(layer.id);
          const panelContent =
            layer.legendDetails && layer.legendDetails.length > 0 ? (
              renderLegendDetails(layer.legendDetails, onLegendEntryToggle, onLegendAxisSetHidden)
            ) : (
              <p className={styles.detailNotice}>{layer.summary}</p>
            );
          return (
            <ChipButton
              key={layer.id}
              Icon={Icon}
              label={layer.label}
              chipLabel={layer.chipLabel ?? layer.label}
              active={layer.on && !layer.disabled}
              disabled={layer.disabled}
              title={layer.title}
              onTap={() => onToggle(layer.id, !layer.on)}
              canExpand={canExpand}
              isExpanded={isExpanded}
              onExpandToggle={() => toggleExpanded(layer.id)}
              dataStatus={layer.dataStatus}
              panelContent={panelContent}
              panelRect={panelRects[layer.id]}
              registerRow={(el) => {
                rowRefs.current[layer.id] = el;
              }}
            />
          );
        })}
        </div>
      </div>
      {chipRowHasMore && (
        <button
          type="button"
          className={styles.pageButton}
          {...chipRowForwardHold}
          aria-label="下を表示"
          title="下を表示"
        >
          ▼
        </button>
      )}
    </div>
  );
}
