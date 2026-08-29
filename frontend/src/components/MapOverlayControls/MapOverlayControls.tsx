"use client";

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactElement } from "react";
import { createPortal } from "react-dom";
import { useStoredState } from "@/hooks/useStoredState";
import {
  MAP_LAYER_CATEGORY_ORDER,
  MAP_LAYER_DATA_NATURE_CHIP_LABELS,
  MAP_LAYER_DATA_NATURE_LABELS,
  type MapLayerCategory,
  type MapLayerDataNature,
  type MapLayerId,
} from "@/components/Map/mapLayers";
import type { SecondaryAxisSummary } from "@/components/Map/secondaryAxes";
import { PRIMARY_ATTRIBUTE_CHIP_LABELS, PRIMARY_ATTRIBUTE_LAYER_IDS } from "@/components/Map/primaryAttributes";
import type { LegendEntry, LegendFilterSummaryAxis } from "@/components/Map/legendFilter";
import { axisIconFor } from "@/components/Map/axisIconPalette";
import {
  AccidentIcon,
  AxisRampIcon,
  DesignationIcon,
  DynamicDataIcon,
  ElevationIcon,
  EstimatedIndexIcon,
  InfoIcon,
  ObservedDataIcon,
  RaindropIcon,
  RoadIcon,
  RoadSurfaceIcon,
  StopPoiIcon,
  SupplyPoiIcon,
  TunnelIcon,
  OnewayIcon,
  RouteIcon,
  ThunderIcon,
  TornadoIcon,
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
   * あるときは軸ごとの内訳だけで十分なため使わない（レイヤー名や絞り込みの1行要約を
   * 重ねて出すと、▶を押した本人には自明な情報の繰り返しになるという実機フィードバックを
   * 受けて廃止した）。 */
  summary?: string | null;
  /** ▶を開いたときに出す、軸ごとの全カテゴリ内訳（表示中/非表示のいずれも含む）。
   * 絞り込み中かどうかに関わらず、レイヤーがONで凡例を持つならこれだけで開閉できる
   * （以前は絞り込み中のレイヤーしか▶が出なかったが、無条件のレイヤーでも凡例を
   * 確認したいという実機フィードバックを受け、legendDetailsの有無だけで判定するよう変更）。 */
  legendDetails?: readonly LegendFilterSummaryAxis[];
  /** 観測グループ内の小見出し分け（改善計画T86→T166）用。mapLayers.ts:
   * MapLayerDescriptor.categoryをそのまま渡す。未指定＝route等のdynamicレイヤーは
   * 次数グループに属さず単独チップのまま。 */
  category?: MapLayerCategory;
  /** 地図チップ最上位のグルーピング単位（改善計画T166、次数反転）。mapLayers.ts:
   * MapLayerDescriptor.dataNatureをそのまま渡す。categoryを持つチップは必ずこれで
   * 観測/推定のどちらかへ束ねられる（未指定は"raw"扱い）。 */
  dataNature?: MapLayerDataNature;
  /** 改善計画T334: 「表示する項目を選ぶ」設定パネル（renderVisibilitySettings）で、
   * この項目の行に個別の情報アイコンを出し、押すと表示する説明文。mapLayers.ts:
   * MapLayerDescriptor.panelHintをそのまま渡す。未設定なら情報アイコン自体を出さない。
   * ▶パネル本体（renderRawMemberTile等）へ常時表示する用途にはもう使わない
   * （T317同日追記で「読みにくい」とされ撤去済みのため、このフィールドは設定パネル
   * 内の任意開閉表示専用）。 */
  panelHint?: string;
}

interface MapOverlayControlsProps {
  layers: readonly OverlayLayerChip[];
  onToggle: (id: MapLayerId, on: boolean) => void;
  /** 改善計画T308: 二次軸(推定指標)一覧。page.tsx側でaxisCatalog.secondaryAxes
   * （useAxisCatalog、軸スタジオの公開軸を含む実行時フェッチ）をそのまま渡す。 */
  secondaryAxes: readonly SecondaryAxisSummary[];
}

// 次数（観測/推定）単位でグルーピングされたチップの中身。categoryを持たないレイヤー
// （route等）は単独チップ（members.length === 1）としてまとめて表現し、単独/グループの
// 分岐をレンダリング側で1本化する（T128から続く設計、実装時の想定どおり「1件だけの
// グループ」として同じコンポーネントで扱う）。"group:raw"/"group:composite"は
// members.length===0でも（推定側はSECONDARY_AXESの薄字項目があるため）チップ自体を出す。
interface ChipGroup {
  key: string;
  members: readonly OverlayLayerChip[];
}

// categoryを持つレイヤーをdataNature（観測/推定/動的、改善計画T166→T171で3値目追加）で
// 3グループへ束ね、categoryを持たないレイヤー（route等のkind="dynamic"。動的データ
// グループとは別物なので混同しないこと）は元の並び順のまま末尾へ単独チップとして追加する。
// 推定グループは、対応する表示レイヤーを持つチップが1件も無くてもSECONDARY_AXESの
// 薄字項目（勾配・舗装質・夜間）を見せるため常に出す。観測・動的グループはcategoryを持つ
// メンバーが1件以上あるときだけ出す。
function buildChipGroups(layers: readonly OverlayLayerChip[]): ChipGroup[] {
  const groups: ChipGroup[] = [];
  // 表示順は推定→観測（実機フィードバックにより入替え。以前は観測→推定だった）→動的
  // （改善計画T171で新設したばかりで既存2グループより関心の的が絞られるため末尾）。
  const estimatedMembers = layers.filter((layer) => layer.category && layer.dataNature === "composite");
  groups.push({ key: "group:composite", members: estimatedMembers });
  const observedMembers = layers.filter((layer) => layer.category && (layer.dataNature ?? "raw") === "raw");
  if (observedMembers.length > 0) groups.push({ key: "group:raw", members: observedMembers });
  const dynamicMembers = layers.filter((layer) => layer.category && layer.dataNature === "dynamic");
  if (dynamicMembers.length > 0) groups.push({ key: "group:dynamic", members: dynamicMembers });
  for (const layer of layers) {
    if (!layer.category) groups.push({ key: layer.id, members: [layer] });
  }
  return groups;
}

// レイヤーIDごとの自作アイコン（icons.tsx）。地図上は文字だけのチップだとスペースを
// 圧迫するという実機フィードバックを受け、小さいアイコン+短いラベルの縦並びへ変更した。
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
  // 改善計画T405: way_id→wind_penalty配信層（評価軸グループとしての風）。専用アイコンは
  // 持たず、同じ風のデータを扱うwindVectorと同じWindIconを流用する（T406でのUI統合時に
  // 見た目の区別が必要になれば見直す、暫定チップという位置づけのため）。
  windAxis: WindIcon,
  thunderNowcast: ThunderIcon,
  tornadoNowcast: TornadoIcon,
  route: RouteIcon,
};

// 次数グループチップ（改善計画T166、T171で3種目「動的」を追加）を代表するアイコン。
const DATA_NATURE_ICONS: Record<MapLayerDataNature, (props: { size?: number }) => ReactElement> = {
  raw: ObservedDataIcon,
  composite: EstimatedIndexIcon,
  dynamic: DynamicDataIcon,
};

// 推定グループの軸タイル（改善計画: 実機フィードバック「2次要素はアイコンだけで区別が
// つくように」への対応）。member.id（MapLayerId）や自動生成のramp軸レイヤーIDにひも付く
// LAYER_ICONSとは別に、axis.iconId（secondaryAxes.ts、改善計画T310で軸自身のデータへ移設）
// から`axisIconFor()`（axisIconPalette.tsx）で引く理由: stop_density・accidentは専用
// レイヤーIDがLAYER_ICONSの対象外（axisMapLayerId経由の生成物）で、そのままでは
// AxisRampIcon（汎用フォールバック）に埋もれてしまうため。renderAxisTileはmemberの
// 有無に関わらずこちらで引く。

// アイコン行と▶トグルの間の間隔（CSS変数--space-2と一致させる。内訳パネルの位置を
// JSで計算する際、CSS側の見た目の間隔と揃えるために数値でも持つ必要がある）。
const PANEL_GAP_PX = 8;
// 内訳パネルの既定の最大高さ（MapOverlayControls.module.css: .detailPanelBaseの
// `max-height: min(45vh, 16rem)`のうちrem側の値と一致させる。PANEL_GAP_PXと同じ理由で、
// 画面下端からのはみ出し対策（下記toggleExpanded参照）をJS側で計算するために数値でも
// 持つ必要がある）。
const DETAIL_PANEL_MAX_HEIGHT_PX = 256; // 16rem（ブラウザ既定のroot font-size 16pxベース）
// 内訳パネルの最小幅（実機フィードバック「凡例が見切れる」への対応、2026-08-27）。
// 画面右端に近いタイル（例: 推定グループ末尾の軸）の▼/▶を押すと、rect.right基準の
// leftが既にビューポート右端に近く、この最小幅すら確保できないままpanelRect.leftを
// 使ってしまい、パネルがビューポート外へはみ出して読めなくなっていた。leftをこの分
// だけビューポート内へ押し戻すことで、パネル自身が必ずこの最小幅ぶんは画面内に収まる
// ようにする（下記toggleExpanded参照）。
const MIN_PANEL_WIDTH_PX = 160;
// グループ本体の開閉キー（改善計画T199、下記toggleExpandedのコメント参照）。
// floatingパネルを持たないため排他制御の対象外にする。
const GROUP_VISIBILITY_KEYS = new Set(["group:composite", "group:raw", "group:dynamic"]);

// グループの開閉・表示項目の設定をlocalStorageへ永続化する（改善計画、ユーザー要望
// 「グループの選択状態等は保持しておいて、次開いた時に同じ状態にして。時間経過で変動する
// 要素以外は、過去の設定内容はlocalStorage等で保持してほしい」）。page.tsxのlayerVisibility
// （各レイヤーのON/OFF自体）は既にuseStoredStateで永続化済みのため、ここではMapOverlayControls
// 固有の「見せ方」の設定（グループ本体の開閉・非表示に選んだメンバー/軸）だけを対象にする。
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
// entry.colorで塗る（改善計画: 「道路種別が支配的な場合、色がすべて灰色で違和感がある」
// への対応で道路の種類も濃淡パレット（COLOR_HIGHWAY_*）を持つようになったため、凡例と
// 地図の見た目を一致させる。路面の種類等widthを持たないカテゴリは従来どおり色ドット）。
function renderLegendSwatch(entry: LegendEntry) {
  if (entry.width === undefined) {
    return <span className={styles.detailSwatchDot} style={{ background: entry.color }} />;
  }
  const height = `${Math.max(2, entry.width)}px`;
  if (entry.dashed) {
    return (
      <span
        className={`${styles.detailSwatchBar} ${styles.detailSwatchBarDashed}`}
        style={{
          height,
          backgroundImage: `repeating-linear-gradient(to right, ${entry.color} 0, ${entry.color} 2px, transparent 2px, transparent 4px)`,
        }}
      />
    );
  }
  return <span className={styles.detailSwatchBar} style={{ height, background: entry.color }} />;
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
              // 「不明・他」等の受け皿カテゴリは他の項目と同列の判定値ではないため、区切り線で
              // 分離する（改善計画T89、MapLayersPanel.tsxの同種の区切りと対応）。
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
        </div>
      ))}
    </div>
  );
}

// 改善計画T374（ユーザー指摘、2026-08-27）: T370〜T373のドラッグスクロール方式
// （useDragScroll、削除済み）は、地図とのピンチズーム競合を避けるための既存対策
// （.iconChip自身のtouch-action: none）と正面衝突し続け、ドラッグ検知・クリック抑止・
// setPointerCapture等の後追いパッチが積み重なって煩雑化した上、実際のスクロール発生が
// 既存のhandleChipRowScroll（スクロールで凡例パネルを閉じる処理、position: fixedパネルが
// 行に追従できないため）を誤って誘発し「グループの展開状態ごと全部閉じてしまう」不具合も
// 引き起こした。要件は「はみ出したアイコンを直感的に確認できればよい」だけなので、
// ドラッグ操作を伴うスクロール自体をやめ、はみ出した分だけ▼/▶ボタンでページ送りする
// 方式へ変更する（ユーザー提案の設計）。ボタンのクリックはtouch-actionの影響を受けない
// （touch-actionはpan/zoom等の"ジェスチャー"だけを制御する仕様で、タップ由来のclickは
// 対象外）ため、.iconChipのtouch-action: noneと衝突しない。ドラッグ検知・クリック抑止・
// scrollイベント経由の副作用が丸ごと不要になる。
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

  const measure = () => {
    const viewport = viewportRef.current;
    const track = trackRef.current;
    if (!viewport || !track) return;
    const viewportSize = axis === "x" ? viewport.clientWidth : viewport.clientHeight;
    const trackSize = axis === "x" ? track.scrollWidth : track.scrollHeight;
    const nextMax = Math.max(0, trackSize - viewportSize);
    setMaxOffset(nextMax);
    setOffset((prev) => Math.min(prev, nextMax));
  };

  // viewport（表示領域）・track（実コンテンツ）はコールバックrefのため、どちらが先に
  // アタッチされるか（マウント順）に依存せず、両方揃った時点でResizeObserverを張り直す
  // （どちらかがアンマウントされたら破棄する）。ResizeObserverを使うことで、軸の増減・
  // 展開/収納・フィルタ設定・画面回転等、はみ出し量に影響しうる変化を網羅的に検知する
  // （個々の変化のたびに手動でmeasure()を呼ぶ箇所を列挙する保守コストを避ける）。
  const rewireObserver = () => {
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
  };

  const registerViewport = (el: HTMLDivElement | null) => {
    viewportRef.current = el;
    rewireObserver();
  };
  const registerTrack = (el: HTMLDivElement | null) => {
    trackRef.current = el;
    rewireObserver();
  };

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

// 改善計画T380フォローアップ（ユーザー指摘、2026-08-27）「押し続けるとそのまま送って
// ほしい」「誤タップで背後の地図を拡大してしまうことがある」への対応。従来はワンタップ
// =1ステップのみで、複数ステップ送るには小さい丸ボタン（1.6rem四方）へ素早く連打する
// 必要があった。連打中はhasMore/hasLessの変化でボタン自体の出現・消滅が起きて位置が
// わずかに動くため、タップが外れて地図キャンバス側に着弾しやすく、それが2連続になると
// 地図側のダブルタップズームとして誤って解釈されていたと考えられる。「押しっぱなしで
// 連続送り」を用意すれば連打そのものが不要になり、地図への誤タップの機会を減らせる。
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
// チップ（改善計画T128、複数レイヤーを1つのカテゴリへ束ねたもの）の両方で同じ
// 「本体ボタン+隣の▶/▼ボタン」の2ボタン構成を使う。単独チップは本体タップ=ON/OFF・
// ▶/▼=凡例展開の別アクションだが、グループチップは束ねた個々のレイヤーのON/OFFが
// 一意に決まらず一括ON/OFFは設けない（誤操作リスク、改善計画T128の実装メモ参照）ため、
// 本体タップも展開トグルと同じ展開/収納にする（呼び出し側でonTapにonExpandToggleと
// 同じ関数を渡す）。
// MapOverlayControlsの内側に定義するとレンダーのたびに新しい関数（＝別のコンポーネント型）
// になり、Reactが毎回アンマウント/再マウントしてDOMノードの同一性が失われる（展開直後に
// 別要素へ差し替わり、テストや実機のフォーカス・aria状態が壊れる）ため、モジュール直下の
// 安定した関数として定義する。panelRects/rowRefsは親の状態のためprops経由で受け取る。
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
  tileVariant,
  expandViaSelf,
  groupTint,
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
  /** 推定グループの軸タイルだけに付ける印。CSS側（.chipRowItemAxis）で2つのことをする:
   * (1) ▼トグルをアイコンの右ではなく下へ積む（画面幅を問わず常時）。
   * (2) モバイル幅のみ、アイコン+略名の正方形タイルをアイコンのみへ縮小し、略名テキスト
   * （.iconLabel）を視覚的に隠す（アクセシビリティ上の名前は保つvisually-hidden、
   * 消すのではない。隠した略名は▼展開パネル側にrenderAxisTileが.detailAxisLabelとして
   * 出す）。フルブラウザでは観測グループのメンバー（一次要素）と同じサイズ・略名表示の
   * まま変えない（実機フィードバック「フルブラウザの場合は一次メンバと同じサイズの
   * アイコン、軸略名入りのものを出して」への対応）。 */
  tileVariant?: "axis";
  /** 展開方向（改善計画T169、地図UIのマトリックス化）。
   * "down"（▼→▲、行の直下へ通常のドキュメントフローで展開）と"right"（▶→▽回転、
   * document.bodyへポータルしてposition: fixedで行の右に浮かせる。個々のメンバータイル・
   * 単独チップ（ルート等）の凡例展開はこちら）は従来どおり自身がpanelContentを描画する。
   * "flat"（観測グループ本体、▼→▲）と"flatRight"（推定グループ本体、▶→◀）は、独立カード
   * （サブフレーム）に閉じ込めず、地図のチップ列と地続きに展開してほしいという実機
   * フィードバックへの対応。矢印の見た目はそれぞれ"down"/"right"と同じだが、自身は
   * 内訳を描画しない。呼び出し元（MapOverlayControls本体）がこのボタンの直後（"flat"）
   * または同じ行の続き（"flatRight"）にメンバーをchipRowの直接の子として差し込む。 */
  expandDirection?: "right" | "down" | "flat" | "flatRight";
  /** 観測/推定グループ本体だけに立てる印（実機フィードバック「展開三角アイコンをなくし、
   * 展開状態は推定と観測アイコンの状態で表現して」への対応）。true のときは隣接する
   * ▶/▼の丸トグルボタン自体を描画せず、本体ボタンのactive見た目とaria-expandedで
   * 開閉状態を表す。本体タップは元々onTapにtoggleExpandedと同じ関数を渡しているため、
   * 押下対象は変わらない（挙動はそのまま、見た目と意味づけだけを変える）。軸タイル・
   * 観測メンバー・単独チップ（ON/OFFと凡例展開が別アクション）はこの対象外で、
   * 従来どおり独立した丸トグルを持つ。
   * active見た目には.iconChipActive（青、ON/OFFチップと同じ＝「地図に反映されている」の
   * 意味）ではなく.iconChipExpanded（実機フィードバック「展開中は薄色でON、展開解除は
   * 灰色でOFFを示して」、CSS側は.groupHeaderChipマーカーとgroupTintの組み合わせで
   * 折りたたみ=灰色・展開=そのグループの薄色塗りを出す）を使う。見出し自体はメンバーの
   * ON/OFFを表さないため、青（.iconChipActive）を使うと「このグループの内容が地図に
   * 出ている」と誤読されてしまう。 */
  expandViaSelf?: boolean;
  /** 次数グループ（推定/観測/動的）の色分け（実機フィードバック「それぞれのタイル及びその
   * グループ配下を少しずつ色を変えてグルーピングして」）。未指定＝category/dataNatureを
   * 持たない単独チップ（ルート等）は無色のまま。 */
  groupTint?: "raw" | "composite" | "dynamic";
}) {
  const arrowGlyph = expandDirection === "right" || expandDirection === "flatRight" ? "▶" : "▼";
  const arrowOpenClass = expandDirection === "right" ? styles.expandArrowOpen : styles.expandArrowDownOpen;
  const isActiveVisual = expandViaSelf ? isExpanded : active;
  const groupTintClass = groupTint === "raw" ? styles.iconChipGroupRaw : groupTint === "composite" ? styles.iconChipGroupComposite : groupTint === "dynamic" ? styles.iconChipGroupDynamic : "";
  // グループ見出し（推定/観測/動的、expandViaSelf=true）だけに付く印（実機フィードバック
  // 「展開中は薄色でON、展開解除は灰色でOFFを示して」）。メンバータイルは常に枠線だけ
  // グループ色のままにしたいため、見出しだけを区別するマーカークラスをCSS側の
  // コンパウンドセレクタ（.groupHeaderChip.iconChipGroupRaw等）で使う。
  const headerMarkerClass = expandViaSelf ? styles.groupHeaderChip : "";
  return (
    <div
      ref={registerRow}
      className={tileVariant === "axis" ? `${styles.chipRowItem} ${styles.chipRowItemAxis}` : styles.chipRowItem}
    >
      <div className={styles.iconToggleRow}>
        <button
          type="button"
          aria-pressed={expandViaSelf ? undefined : active}
          aria-expanded={expandViaSelf ? isExpanded : undefined}
          disabled={disabled}
          title={title}
          onClick={onTap}
          className={
            isActiveVisual
              ? `${styles.iconChip} ${groupTintClass} ${headerMarkerClass} ${expandViaSelf ? styles.iconChipExpanded : styles.iconChipActive}`
              : `${styles.iconChip} ${groupTintClass} ${headerMarkerClass}`
          }
        >
          <Icon />
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
// （MapLayersPanel）で行う（地図上の▶はあくまで確認用で、以前あった「タップでサイドバーへ
// ジャンプ」動線はここが確認専用になったことで廃止した）。このコンポーネントはレイヤー
// 固有の知識を持たない汎用の描画係で、レイヤーが増えてもここは変更不要（mapLayers.tsの
// コメント参照）。
export default function MapOverlayControls({ layers, onToggle, secondaryAxes }: MapOverlayControlsProps) {
  // 凡例を常時表示すると地図の視界を圧迫するという実機フィードバックを受け、既定は
  // 非表示にし、チップ横の▶を押したレイヤーのぶんだけ薄いポップオーバーで出す。
  // 開閉はキーのSetで個別管理する。キーはレイヤーID（単独チップ）・`member:${id}`
  // （観測グループのメンバー）・`axis:${axisId}`（推定グループの軸タイル）・
  // グループキー`group:composite`/`group:raw`/`group:dynamic`（改善計画T166、次数
  // グループ本体の開閉）・`${groupKey}:legend`（アイコンの意味凡例）のいずれか。
  // グループ本体の開閉はfloatingパネルを持たない（member/axisの一覧をchipRowへ
  // インラインで差し込むだけ）ため複数グループを同時に開いても重ならないが、
  // それ以外（member:/axis:/単独チップ/${groupKey}:legend）はdocument.bodyへ
  // ポータルするfloatingパネルのため、複数同時に開くと近接する行同士でパネルが
  // 重なり両方とも判読不能になる不具合が実機で確認された（統合レビュー2026-08-22
  // 指摘、改善計画T199: 降水ナウキャストと風の凡例を続けて開いた場合）。
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
  // 暗黙にauto扱いになり、そのままではパネルをposition: absoluteでこの行の右へ
  // はみ出させる従来方式だとchipRowにクリップされて何も見えなくなる（実機フィードバック
  // 「▶を押しても何も出ない」＝この不具合）。document.bodyへポータルし、押した瞬間の
  // 行の実際の画面位置をJSで測ってposition: fixedで配置することでクリップを回避する。
  const [panelRects, setPanelRects] = useState<Partial<Record<string, PanelRect>>>({});
  const rowRefs = useRef<Partial<Record<string, HTMLDivElement | null>>>({});
  // 改善計画T374: .chipRow（縦）・.estimatedFlatRow（横）それぞれの、はみ出し分の
  // ページ送り（usePagedOverflow参照）。JSXのprops側でオブジェクトのメンバー式
  // （例: chipRowPaging.registerTrack）を直接参照すると、react-hooks/refs lintルールが
  // 「レンダー中のref参照」と誤検知するため（返り値にref操作を含む関数を持つカスタム
  // フックのため保守的に判定される）、ここで一度分割代入し裸の変数としてJSXへ渡す。
  const {
    registerViewport: registerChipRowViewport,
    registerTrack: registerChipRowTrack,
    offset: chipRowOffset,
    pageForward: pageChipRowForward,
    pageBackward: pageChipRowBackward,
    hasMore: chipRowHasMore,
    hasLess: chipRowHasLess,
  } = usePagedOverflow("y");
  const {
    registerViewport: registerEstimatedRowViewport,
    registerTrack: registerEstimatedRowTrack,
    offset: estimatedRowOffset,
    pageForward: pageEstimatedRowForward,
    pageBackward: pageEstimatedRowBackward,
    hasMore: estimatedRowHasMore,
    hasLess: estimatedRowHasLess,
  } = usePagedOverflow("x");

  // 観測/推定/動的グループで「表示する項目を選ぶ」設定（改善計画T181）。ユーザー報告
  // 「縦アイコンが多くて見切れるようになってきた」への対応として、グループ見出しの
  // Ⓘボタン（従来は読み取り専用の「アイコンの意味」凡例だった）を、配下メンバー/軸の
  // 表示・非表示を選べる設定パネルへ拡張する。グループ本体を開くと、ここで非表示に
  // 選んだもの以外だけが並ぶ（絞り込みは各グループ内で完結し、既定＝何も非表示に
  // 選んでいない状態では従来どおり全件表示）。キーは`${scope}:${memberOrAxisId}`
  // （scope="raw"|"composite"|"dynamic"、グループ間でIDが衝突しても名前空間で区別
  // できるようにする）。ユーザー要望「過去の設定内容はlocalStorageで保持してほしい」を
  // 受け、localStorageへ永続化する（レイヤー構成が変わり存在しないIDが残っても、
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
  // OFFにする（実機フィードバック「設定で非表示にした場合、裏でレイヤ表示ONになっていれば
  // OFFにして」）。設定パネルからチップが消えた後もレイヤーが地図に描画され続け、かつ
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

  // 改善計画T334: 「表示する項目を選ぶ」設定パネル内、各項目の情報アイコンで説明文
  // (panelHint)を開閉する状態。個々の凡例展開（member:/axis:等）と同じく「今ちょっと
  // 確認のために開いている」一時的な状態のため、localStorageへは永続化しない
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

  // anchor="right"（従来どおり行の右へ）/"down"（行の直下へ）。いずれもdocument.bodyへ
  // ポータルしてposition: fixedで浮かせる（下記ChipButton参照）。▼方向（推定グループの
  // 軸タイル）を最初はchipRowItem内の通常のフロー+position: absoluteで実装したが、
  // chipRowのoverflow-y: auto（＝暗黙にoverflow-xもauto）の内側にある限りabsolute配置でも
  // chipRowのスクロール可能領域に算入されてしまい、パネル1個ぶん右にはみ出ただけで
  // chipRowに横スクロールバーが出てしまう不具合が実機で見つかった（▶方向で以前解決した
  // のと同じ種類の問題）。▶方向と同じくポータルで完全にchipRowの外へ出すことで解消する。
  const toggleExpanded = (id: string, anchor: "right" | "down" = "right") => {
    const isOpening = !expandedIds.has(id);
    if (isOpening) {
      const row = rowRefs.current[id];
      if (row) {
        const rect = row.getBoundingClientRect();
        const top = anchor === "down" ? rect.bottom + PANEL_GAP_PX : rect.top;
        const rawLeft = anchor === "down" ? rect.left : rect.right + PANEL_GAP_PX;
        // 画面右端からのはみ出し対策（実機フィードバック「凡例が見切れる」への対応）。
        // 画面右端に近いタイル（推定グループ末尾の軸等）だとrawLeftが既にビューポート
        // 右端に近く、下のmaxWidth計算のMath.max(160, ...)フロアにより最小幅160pxが
        // 強制されてもleft自体を動かさないままだとパネルがビューポート外へはみ出して
        // しまう。leftをこの分だけ画面内へ押し戻し、パネルが必ずMIN_PANEL_WIDTH_PXぶん
        // 画面内に収まるようにする（画面幅自体がそれより狭い極端なケースはPANEL_GAP_PX
        // まで詰める）。
        const left = Math.min(rawLeft, Math.max(PANEL_GAP_PX, window.innerWidth - MIN_PANEL_WIDTH_PX - PANEL_GAP_PX));
        // 画面下端からのはみ出し対策（実機フィードバック「スクロールできないことがある」）。
        // position: fixedのためtopが画面下端に近いと、CSS既定の最大高さ（16rem）ぶんが
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
        // floatingパネル系のキー（member:/axis:/単独チップ/${groupKey}:legend）は排他
        // （改善計画T199）: 新しく開くキーがグループ本体の開閉（GROUP_VISIBILITY_KEYS）で
        // なければ、他のfloatingパネル系キーをすべて閉じてから開く。グループ本体同士は
        // floatingパネルを持たないため対象外のまま複数同時に開ける。
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

  // 改善計画T374: ページ送り（▲▼/◀▶）を押すと、position: fixedの凡例パネルは
  // 行に追従できず表示がずれたままになるため閉じる。以前（T370〜T373のドラッグ
  // スクロール、handleChipRowScroll）はexpandedIdsを丸ごとクリアしており、
  // グループ自体の展開状態（GROUP_VISIBILITY_KEYS）まで一緒に閉じてしまい
  // 「観測/動的グループを開いて送ろうとすると全部折りたたまれる」不具合になっていた。
  // ページ送り自体はグループを開いたまま行いたい操作のため、フローティングパネル系の
  // キー（member:/axis:/単独チップ/${groupKey}:legend）だけを対象にする。
  const closeFloatingPanels = () => {
    setExpandedIds((prev) => {
      const next = new Set([...prev].filter((key) => GROUP_VISIBILITY_KEYS.has(key)));
      return next.size === prev.size ? prev : next;
    });
  };

  // 改善計画T380フォローアップ: ▲▼/◀▶それぞれの「押しっぱなしで連続送り」
  // （useHoldRepeat参照）。closeFloatingPanels()は既存のクリックハンドラと同じく
  // ページ送りのたびに呼ぶ（何も開いていなければsetExpandedIdsが同一参照を返すため
  // 再レンダーは発生せず、繰り返し呼んでも無害）。
  const chipRowBackwardHold = useHoldRepeat(() => {
    closeFloatingPanels();
    pageChipRowBackward();
  }, chipRowHasLess);
  const chipRowForwardHold = useHoldRepeat(() => {
    closeFloatingPanels();
    pageChipRowForward();
  }, chipRowHasMore);
  const estimatedRowBackwardHold = useHoldRepeat(() => {
    closeFloatingPanels();
    pageEstimatedRowBackward();
  }, estimatedRowHasLess);
  const estimatedRowForwardHold = useHoldRepeat(() => {
    closeFloatingPanels();
    pageEstimatedRowForward();
  }, estimatedRowHasMore);

  // 観測グループの1メンバー（改善計画T166→T169でタイル化）。推定グループの軸タイルと
  // 同じ「アイコン+略名の四角タイル+隣に付随する凡例展開ボタン」をChipButtonの再利用で
  // 表す（見た目を全要素で統一するというユーザー指摘への対応）。観測グループ自体は
  // ▼縦積み（ChipButtonのexpandDirection="down"）のため、メンバー個々の凡例は▶で
  // 右へ展開する（縦に並んだ他のメンバーと重ならないよう、グループ本体と直交する
  // 向きにする）。凡例を持つメンバーは常に▶が付く（実機フィードバック「道路種別や路面等に
  // ▶を付けて」への対応。以前はON時のみ▶を出していたが、推定グループの軸タイルが
  // ON/OFFに関わらず▼を出すのと不揃いだったため、ONに依存しない判定へ揃えた。
  // legendDetailsはレイヤー定義由来の固定内容でありON/OFFで内容が変わらないため、
  // OFF中に「オンにすると何が出るか」を先に確認できる利点もある）。
  // legendDetailsが空でもsummaryがあれば▶を出す（実機フィードバック「たまに凡例を出す
  // ための▶が消える」への対応。道路種別・路面はregionZoomTooWide中legendDetailsが空配列
  // になる＝ズームインを促す案内文（summary、page.tsx: roadTypeSummary/roadSurfaceSummary
  // 参照）だけが内容になる想定だが、canExpandがlegendDetailsの有無だけで判定していたため
  // ▶自体が消えて案内文を開けなくなっていた。単独チップ側（本ファイル末尾のcanExpand=
  // hasLegendDetails || Boolean(layer.summary)）と同じ判定へ揃える）。
  function renderRawMemberTile(member: OverlayLayerChip, groupTint: "raw" | "dynamic") {
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
        panelContent={
          canExpand ? (
            hasLegend ? (
              renderLegendDetails(member.legendDetails!)
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

  // 推定グループの各軸の下に出す材料一覧（改善計画T167、T308でaxisMaterials（軸id→
  // 一次属性、静的axis-catalog.json由来）からSecondaryAxisSummary.primaryAttributeIds
  // （軸スタジオ作成軸も含む実行時カタログ由来）へ切替）。一次属性を、表示レイヤーの
  // 有無で2行に分ける。レイヤーを持つ材料は「効いているものを探す」ときにそのまま
  // 地図上で確認できる旨、レイヤーを持たない材料（車線数・制限速度・交差点・街灯・
  // 自動車通行可否）は地図では見えない材料として薄字で正直に見せる（略名は
  // PRIMARY_ATTRIBUTE_CHIP_LABELS、primaryAttributes.tsのコメントどおりT167用に
  // 4文字以下で全属性ぶん揃えてある）。
  function renderMaterialsNote(materials: readonly string[]) {
    const withLayer = materials.filter((attrId) => PRIMARY_ATTRIBUTE_LAYER_IDS[attrId] !== undefined);
    const withoutLayer = materials.filter((attrId) => PRIMARY_ATTRIBUTE_LAYER_IDS[attrId] === undefined);
    if (withLayer.length === 0 && withoutLayer.length === 0) return null;
    return (
      <>
        {withLayer.length > 0 && (
          <p className={styles.detailNotice}>
            材料: {withLayer.map((attrId) => PRIMARY_ATTRIBUTE_CHIP_LABELS[attrId] ?? attrId).join("・")}
          </p>
        )}
        {withoutLayer.length > 0 && (
          <p className={`${styles.detailNotice} ${styles.detailRowHidden}`}>
            地図では未表示の材料: {withoutLayer.map((attrId) => PRIMARY_ATTRIBUTE_CHIP_LABELS[attrId] ?? attrId).join("・")}
          </p>
        )}
      </>
    );
  }

  // 「観測データ」グループの▼内容: 独立したカード（サブフレーム）に閉じ込めず、
  // chipRowの直接の子として観測チップの直後に地続きで差し込む（実機フィードバック
  // 「サブフレームの中で縦並びになるのではなく、観測チップと同列に縦並びで展開してほしい」
  // への対応、以前のrenderObservedGroupPanel＝カード化を廃止）。category小見出し
  // （道路状態・交通・安全）は表示せず、MAP_LAYER_CATEGORY_ORDER順のフラットな一覧に
  // する（実機フィードバック「道路状態や交通・安全等のグルーピングを消して」への対応。
  // 順序自体はcategory順を保つが、見出しテキストは出さない）。メンバー本体
  // （renderRawMemberTile）はChipButtonが自前でchipRowItemを返すため、ここでは
  // 追加のラッパーを挟まずそのままchipRowの子として返す。
  function orderObservedMembers(members: readonly OverlayLayerChip[]): readonly OverlayLayerChip[] {
    return MAP_LAYER_CATEGORY_ORDER.flatMap((category) => members.filter((m) => m.category === category));
  }

  // メンバー増加（観測グループは現状8件）で展開直後に画面下端を超えて見切れるという
  // 実機フィードバックを受け、Ⓘの設定パネル（renderVisibilitySettings）で非表示に
  // 選んだメンバーはここで除外する（改善計画T181）。
  function renderObservedMemberRows(
    members: readonly OverlayLayerChip[],
    groupTint: "raw" | "dynamic",
    scope: "raw" | "dynamic"
  ): ReactElement[] {
    return orderObservedMembers(members)
      .filter((member) => !hiddenIds.has(`${scope}:${member.id}`))
      .map((member) => renderRawMemberTile(member, groupTint));
  }

  // 観測/推定/動的グループ見出しの「表示する項目を選ぶ」設定パネル（改善計画T181）。
  // 以前は読み取り専用の「アイコンの意味」凡例（一覧を見せるだけ）だったが、ユーザー
  // 報告「縦アイコンが多くて見切れるようになってきた」への対応として、各項目に表示/
  // 非表示のチェックボックスを持たせ、ここで選んだ項目だけがグループ展開時に並ぶように
  // 拡張した。折りたたみ時だけ見出しの脇に出す独立した入口にする方針は維持する（展開後は
  // 絞り込み済みの項目自体のアイコンが並ぶため、その場に同じ一覧をもう一度出すと二重表示に
  // なってかえって読みにくい）。呼び出し側（chipGroups.flatMapの中）が `!isExpanded` の
  // ときだけこの関数を呼ぶことで担保する。ChipButtonは使わず、同じ「小さい丸ボタン+
  // document.bodyへポータルする内訳パネル」の仕組み（toggleExpanded/panelRects/rowRefs）を
  // 直接流用する軽量な専用実装にする。キーは`${groupKey}:legend`でexpandedIds等の
  // 既存Setにそのまま同居できる。
  function renderVisibilitySettings(
    groupKey: string,
    groupLabel: string,
    scope: "raw" | "composite" | "dynamic",
    items: readonly {
      key: string;
      Icon: (props: { size?: number }) => ReactElement;
      label: string;
      /** 対応するレイヤーID（あれば）。非表示に選んだ瞬間そのレイヤーがONならOFFにするために使う
       * （toggleHidden参照）。推定グループの専用レイヤーを持たない軸（勾配・舗装質・夜間）は
       * undefinedのまま渡す。 */
      layerId?: MapLayerId;
      on?: boolean;
      /** 改善計画T334: 行の右側に個別の情報アイコンを出し、押すと表示する説明文。
       * 未設定なら情報アイコン自体を出さない。 */
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
                  // 改善計画T334: infoKeyはhiddenKeyと同じ`${scope}:${item.key}`名前空間だが
                  // 別のSet（openInfoKeys）で管理するため、非表示設定と情報アイコンの開閉は
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

  // 推定グループの1軸タイル（改善計画T166→T169でタイル化）。観測グループのメンバータイルと
  // 同じChipButtonを使い、見た目を統一する。専用の表示レイヤーを持つ軸（車の圧迫感・
  // 停止密度・事故密度）はlayersから対応するチップを引いてON/OFFタイルに、専用レイヤーの
  // 無い軸（勾配・舗装質・夜間）はdisabled＝タップ不能の情報タイルにする（secondaryAxes.ts
  // 参照）。推定グループ自体は▶横並び（ChipButtonのexpandDirection="right"）のため、
  // 軸タイル個々の凡例・材料一覧（改善計画T167）は▼で下へ展開する（横に並んだ他の軸と
  // 重ならないよう、グループ本体と直交する向きにする）。材料一覧はON/OFFに関わらず
  // 「材料になっている一次属性が何か」を確認できるようcanExpandへ含めるが、色の凡例は
  // 実際に地図へ描画されているときだけ意味を持つためON時のみ含める。ONにする操作自体は
  // 個別レイヤーのトグル（onToggle経由）に任せ、材料の連動ONはpage.tsx側
  // （handleLayerToggle）が行う（このコンポーネントはレイヤー固有の知識を持たない汎用
  // 描画係のまま、というファイル冒頭のコメント方針を維持する）。
  function renderAxisTile(axis: SecondaryAxisSummary, members: readonly OverlayLayerChip[]) {
    const key = `axis:${axis.axisId}`;
    const member = axis.layerId ? members.find((m) => m.id === axis.layerId) : undefined;
    const materialsNote = renderMaterialsNote(axis.primaryAttributeIds);
    const Icon = axisIconFor(axis.iconId);
    if (!member) {
      // 改善計画T318: 専用レイヤーを持たない軸は、以前は代役案内文（旧proxy_hint）を
      // 出していたが、show_map_iconのON/OFFで「そもそも表示するかどうか」を選べる
      // ようになったため撤去した。この分岐に来る軸はshow_map_icon=trueのまま専用
      // レイヤーを持たないだけなので、タップ不能の情報タイル（アイコン+略称のみ）
      // として引き続き存在させる。
      const canExpand = materialsNote !== null;
      return (
        <ChipButton
          key={key}
          Icon={Icon}
          label={axis.label}
          chipLabel={axis.chipLabel}
          active={false}
          disabled
          onTap={() => {}}
          canExpand={canExpand}
          isExpanded={canExpand && expandedIds.has(key)}
          onExpandToggle={() => toggleExpanded(key, "down")}
          expandDirection="down"
          tileVariant="axis"
          groupTint="composite"
          panelContent={
            <div className={styles.detailBody}>
              {/* モバイルではタイル本体の略名を.chipRowItemAxisで視覚的に隠す（横並びを
                  1行に近づけるための縮小、ChipButtonのtileVariantコメント参照）ため、
                  隠した分をここで見出しとして出す。デスクトップでは冗長になるが、
                  タイル本体にも同じ文字が出ているだけで害はない。 */}
              <div className={styles.detailAxisLabel}>{axis.chipLabel}</div>
              {materialsNote}
            </div>
          }
          panelRect={panelRects[key]}
          registerRow={(el) => {
            rowRefs.current[key] = el;
          }}
        />
      );
    }
    const hasLegend = Boolean(member.legendDetails && member.legendDetails.length > 0);
    const showLegend = Boolean(member.on && !member.disabled && hasLegend);
    const canExpand = showLegend || materialsNote !== null;
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
        onExpandToggle={() => toggleExpanded(key, "down")}
        expandDirection="down"
        tileVariant="axis"
        groupTint="composite"
        panelContent={
          <div className={styles.detailBody}>
            <div className={styles.detailAxisLabel}>{axis.chipLabel}</div>
            {showLegend && renderLegendDetails(member.legendDetails!)}
            {materialsNote}
          </div>
        }
        panelRect={panelRects[key]}
        registerRow={(el) => {
          rowRefs.current[key] = el;
        }}
      />
    );
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
          // 推定グループ。▶を開くと、独立したカードに閉じ込めず、6軸のタイルを推定チップと
          // 同じ上端・同じ間隔の横並びとして地続きに展開する（観測グループの▼縦並び地続き化
          // と対になる実機フィードバック「推定も▶で同じ上端・同じ列間で横並び展開してほしい」
          // への対応）。ChipButton自身はexpandDirection="flatRight"で▶→◀（180度回転）の
          // 見た目だけを持ち、内訳は描画しない。header自体も横並びの先頭要素として
          // .estimatedFlatRowに含める（アイコン+トグルと軸タイルの上端を揃えるため）。
          if (group.key === "group:composite") {
            const RepresentativeIcon = DATA_NATURE_ICONS.composite;
            const isExpanded = expandedIds.has(group.key);
            const label = MAP_LAYER_DATA_NATURE_LABELS.composite;
            const chipLabel = MAP_LAYER_DATA_NATURE_CHIP_LABELS.composite;
            const header = (
              <ChipButton
                key={group.key}
                Icon={RepresentativeIcon}
                label={label}
                chipLabel={chipLabel}
                // 次数グループ本体は展開/収納の見出しであり、タップしてもレイヤーの
                // ON/OFFは切り替わらない（実機フィードバック「観測/推定はONにならなくて
                // いい」への対応。以前はメンバーが1件でもONならこの見出し自体も
                // アクティブ表示にしていたが、材料の連動ON（T167）で意図せず「推定」
                // 全体が光って見える不具合になっていた）。activeはexpandViaSelf=trueの下では
                // 無視され、見出しのactive見た目は展開状態(isExpanded)から決まる
                // （実機フィードバック「展開三角アイコンをなくし、展開状態は推定と観測
                // アイコンの状態で表現して」への対応）。
                active={false}
                title={`${label}[${secondaryAxes.length}件をタップで一覧]`}
                onTap={() => {
                  toggleExpanded(group.key);
                  closeGroupLegend(group.key);
                }}
                canExpand
                isExpanded={isExpanded}
                onExpandToggle={() => toggleExpanded(group.key)}
                expandDirection="flatRight"
                expandViaSelf
                groupTint="composite"
                panelContent={<></>}
                panelRect={panelRects[group.key]}
                registerRow={(el) => {
                  rowRefs.current[group.key] = el;
                }}
              />
            );
            // 折りたたみ中だけ、見出しの脇に「アイコンの意味」凡例の入口を出す（実機
            // フィードバック「アイコンだけで区別が付くように」への提案からユーザーが選んだ
            // 方針。展開後は軸タイル自体のアイコンが並ぶため、この入口は消す）。ラッパーdivの
            // key（`${group.key}:row`）は折りたたみ/展開のどちらでも同じ値に固定する。
            // classNameと中身（凡例トグル/軸タイル）だけを状態で出し分け、divそのものは
            // 同一のDOMノードとして保つことで、直接の子であるheader（ChipButton）が
            // 展開の瞬間にアンマウント/再マウントされてfocus・aria状態が失われるのを防ぐ
            // （以前divのkeyを折りたたみ/展開で別の値にしていたところ、実機ではなくテストで
            // 展開直後にaria-expandedの取得元DOMノードが差し替わっている不具合が発覚した）。
            return [
              <div key={`${group.key}:row`} className={styles.headerLegendRow}>
                {header}
                {isExpanded && (
                  <>
                    {estimatedRowHasLess && (
                      <button
                        type="button"
                        className={`${styles.pageButton} ${styles.pageButtonHorizontal}`}
                        {...estimatedRowBackwardHold}
                        aria-label="左を表示"
                        title="左を表示"
                      >
                        ◀
                      </button>
                    )}
                    <div className={styles.estimatedFlatRowViewport} ref={registerEstimatedRowViewport}>
                      <div
                        className={styles.estimatedFlatRow}
                        ref={registerEstimatedRowTrack}
                        style={{ transform: `translateX(-${estimatedRowOffset}px)` }}
                      >
                        {secondaryAxes
                          .filter((axis) => !hiddenIds.has(`composite:${axis.axisId}`))
                          .map((axis) => renderAxisTile(axis, group.members))}
                      </div>
                    </div>
                    {estimatedRowHasMore && (
                      <button
                        type="button"
                        className={`${styles.pageButton} ${styles.pageButtonHorizontal}`}
                        {...estimatedRowForwardHold}
                        aria-label="右を表示"
                        title="右を表示"
                      >
                        ▶
                      </button>
                    )}
                  </>
                )}
                {!isExpanded &&
                  renderVisibilitySettings(
                      group.key,
                      label,
                      "composite",
                      secondaryAxes.map((axis) => {
                        const axisMember = axis.layerId ? group.members.find((m) => m.id === axis.layerId) : undefined;
                        return {
                          key: axis.axisId,
                          Icon: axisIconFor(axis.iconId),
                          label: axis.chipLabel,
                          layerId: axis.layerId,
                          on: axisMember?.on,
                          description: axis.panelHint,
                        };
                      })
                    )}
              </div>,
            ];
          }

          // 観測グループ。▼を開くと、独立したカードに閉じ込めず、道路種別・路面などの
          // メンバーをchipRowの直接の子として観測チップの直後に地続きで差し込む（実機
          // フィードバック「サブフレームの中でなく、観測チップと同列に縦並びで展開してほしい」
          // への対応）。ChipButton自身はexpandDirection="flat"で▼矢印の見た目だけを持ち、
          // 内訳は描画しない（renderObservedMemberRowsを別途sibling要素として返す）。
          if (group.key === "group:raw") {
            const RepresentativeIcon = DATA_NATURE_ICONS.raw;
            const isExpanded = expandedIds.has(group.key);
            const label = MAP_LAYER_DATA_NATURE_LABELS.raw;
            const chipLabel = MAP_LAYER_DATA_NATURE_CHIP_LABELS.raw;
            const header = (
              <ChipButton
                key={group.key}
                Icon={RepresentativeIcon}
                label={label}
                chipLabel={chipLabel}
                // group:compositeと同じ理由（上のコメント参照）でactiveは無視され、
                // 見出しのactive見た目は展開状態(isExpanded)から決まる。
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
                groupTint="raw"
                panelContent={<></>}
                panelRect={panelRects[group.key]}
                registerRow={(el) => {
                  rowRefs.current[group.key] = el;
                }}
              />
            );
            // group:compositeと同じ理由（上のコメント参照）で、折りたたみ中だけ見出しの脇に
            // 「アイコンの意味」凡例の入口を出し、展開後は消す。ラッパーdivのkeyは折りたたみ/
            // 展開のどちらでも同じ値に固定し、headerのDOMノードを保つ（group:compositeと
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
                  ? renderObservedMemberRows(group.members, "raw", "raw")
                  : renderVisibilitySettings(
                      group.key,
                      label,
                      "raw",
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

          // 動的グループ（改善計画T171、新設）。観測グループ（group:raw、直上）と全く同じ
          // 「▼縦積み・地続き展開」の構成を使う（renderObservedMemberRows/orderObservedMembers
          // は名称に反しobserved固有の処理を持たない汎用関数のため、そのまま再利用する）。
          if (group.key === "group:dynamic") {
            const RepresentativeIcon = DATA_NATURE_ICONS.dynamic;
            const isExpanded = expandedIds.has(group.key);
            const label = MAP_LAYER_DATA_NATURE_LABELS.dynamic;
            const chipLabel = MAP_LAYER_DATA_NATURE_CHIP_LABELS.dynamic;
            const header = (
              <ChipButton
                key={group.key}
                Icon={RepresentativeIcon}
                label={label}
                chipLabel={chipLabel}
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
                groupTint="dynamic"
                panelContent={<></>}
                panelRect={panelRects[group.key]}
                registerRow={(el) => {
                  rowRefs.current[group.key] = el;
                }}
              />
            );
            return [
              <div
                key={`${group.key}:row`}
                className={isExpanded ? styles.observedExpandedColumn : styles.headerLegendRow}
              >
                {header}
                {isExpanded
                  ? renderObservedMemberRows(group.members, "dynamic", "dynamic")
                  : renderVisibilitySettings(
                      group.key,
                      label,
                      "dynamic",
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

          // categoryを持たない単独チップ（route等のdynamicレイヤー）。
          const layer = group.members[0];
          // 二次軸rampレイヤー（改善計画T145b）はレジストリ生成物から自動で増えるため
          // レイヤーIDごとの専用アイコンを持たず、共通のAxisRampIconへフォールバックする
          // （undefinedのままJSXへ渡すとReactが「Element type is invalid」で落ちる）。
          const Icon = LAYER_ICONS[layer.id] ?? AxisRampIcon;
          const hasLegendDetails = Boolean(layer.legendDetails && layer.legendDetails.length > 0);
          const canExpand = layer.on && !layer.disabled && (hasLegendDetails || Boolean(layer.summary));
          const isExpanded = canExpand && expandedIds.has(layer.id);
          const panelContent =
            layer.legendDetails && layer.legendDetails.length > 0 ? (
              renderLegendDetails(layer.legendDetails)
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
