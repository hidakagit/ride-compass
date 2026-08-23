"use client";

import { useEffect, useRef } from "react";
import useEmblaCarousel from "embla-carousel-react";
import { WheelGesturesPlugin } from "embla-carousel-wheel-gestures";
import styles from "./DynamicLayerTimeSlider.module.css";

/** スライダーの1フレーム分の表示内容。T183再設計でONの全レイヤーのフレーム時刻を統合した
 * 1本の共有タイムラインを表すようになったため、時刻ラベルのみを持つ（旧badgeフィールドは
 * 「レイヤー固有の実況/予測ラベル」用だったが、1つの目盛りに複数レイヤーが同時に対応しうる
 * 設計では意味を持たなくなったため撤去、dynamicWeather.ts: formatDynamicFrameTime参照）。
 * labelは左端の指標の上に出す1行サマリ用（実機フィードバック「今の位置の正しい日時は
 * 左端ではなく上に出して」）で、日付をまたぐタイムラインの曖昧さを避けるため常に日付を
 * 含むフル表記（dynamicWeather.ts: formatDynamicFrameTime）。hourMarkはルーラーの目盛りの
 * 線を太くするかどうか（呼び出し側=page.tsxが正時判定して渡す）。降水ナウキャスト
 * （5分刻み、〜60分先）の区間では正時フレームがまばらにしか無く目盛りもまばらに、延長予報
 * （1時間刻み、〜48時間先）の区間では全フレームが正時のため毎コマに目盛りが付く。スライダー
 * 自体はコマ（インデックス）ごとに等間隔で並ぶ設計のままのため、目盛りをフレームごとの
 * 正時判定で間引くだけで「近い将来は目盛りがまばら＝連続的に細かく動かせる、遠い将来は
 * 毎コマに目盛り＝1時間刻みで止まる」という実際の間隔設計がひと目で伝わる（間隔設計自体は
 * 変更しない）。tickLabelは目盛りの線の下に出す短い文字（実機フィードバック「目盛りは
 * 日付部分は不要、時刻のみ。時刻も細いところは分だけにする等」）。日付を持たず、正時なら
 * 「HH:mm」・そうでなければ分のみ2桁（page.tsx: formatDynamicFrameHourMinute/
 * formatDynamicFrameMinuteOnly）。undefined/空文字ならこのコマには文字を出さない
 * （延長予報のように毎コマ正時が続く区間で毎コマぶん文字まで出すと、1コマの目盛り間隔
 * （TICK_SPACING_HOUR_PX）に対して文字幅の方が広く重なってしまう、実機Playwright確認で
 * 発覚したため、page.tsx側で正時ラベルはさらに間引いて渡す）。 */
export interface DynamicLayerTimeSliderFrame {
  label: string;
  hourMark?: boolean;
  tickLabel?: string;
}

// 1コマぶんの目盛り間隔（px、正時以外＝降水ナウキャストの5分刻み等の密なコマ）。
// 実機フィードバック「もう少し目盛りを細かく」を受け、元の22pxから縮小した。
const TICK_SPACING_PX = 18;
// 正時（hourMark）ぶんの目盛り間隔（px）。実機フィードバック「1時間間隔のときはもう少し
// 目盛り間隔を広く」への対応。延長予報区間（60分以降、全コマが正時＝1時間刻み）はこちらを
// 使う。初期画面に全コマが収まっている必要はなく、スクロールできれば足りるという前提
// （同フィードバック）のため、広げた分だけルーラー全体の総幅・スクロール量が伸びることは
// 許容する。
const TICK_SPACING_HOUR_PX = 28;
// スクロール位置を合わせる「左端の目印」(.leftIndicator)の、ビューポート左端からの固定
// オフセット（px）。個々のコマの幅（正時/非正時で異なる）とは独立した値のため、常に
// TICK_SPACING_PXの半分のまま変えない。EmblaのカスタムalignもこのINDICATOR_OFFSET_PXを
// 単一の情報源として使う（下記emblaOptions.align参照）。
const INDICATOR_OFFSET_PX = TICK_SPACING_PX / 2;

/** コマ1つぶんの目盛り間隔（px）。正時（hourMark）はTICK_SPACING_HOUR_PX、それ以外は
 * TICK_SPACING_PXを使う。 */
function frameWidth(frame: DynamicLayerTimeSliderFrame): number {
  return frame.hourMark ? TICK_SPACING_HOUR_PX : TICK_SPACING_PX;
}

interface DynamicLayerTimeSliderProps {
  frames: readonly DynamicLayerTimeSliderFrame[];
  /** framesのindex。framesが空、またはまだ範囲外なら効果なし（呼び出し側でclamp済み前提）。 */
  index: number;
  onIndexChange: (index: number) => void;
  /** 「現在」に相当するframesのindex（precipitationNowcast.ts: latestObservedFrameIndex・
   * windLayer.ts: nearestFrameIndexToNowを呼び出し側が計算した値）。「現在」ボタンを
   * 無効化する判定（index===currentIndexの間はno-op）にのみ使う。ジャンプ先の決定は
   * onNowが担う（このindexそのものへは飛ばない、下記onNowのコメント参照）。 */
  currentIndex: number;
  /** 「現在」ボタンを押したときの処理。呼び出し側（page.tsx）が実時刻(new Date())へ
   * 共有の対象時刻を戻す想定（改善計画、実機フィードバック「現在リセットすると23:00になって
   * 上バーが消えた」）。以前はonIndexChange(currentIndex)、つまり「このレイヤー自身の
   * "現在"フレームの時刻」へ共有時刻を合わせていたが、風は1時間刻みでcurrentIndexが
   * 実時刻より最大59分過去の正時に丸まる（例: 23:25の実時刻でcurrentIndex=23:00）。
   * 降水ナウキャストは「現在」より前のフレームを持たない（trimToCurrentAndFuture参照）ため、
   * 風側の「現在」ボタンでこの過去寄りの時刻へ共有時刻を合わせると、降水側が範囲外
   * （unavailable）になってしまう不具合があった。実時刻そのものへ戻せば両レイヤーとも
   * 自分の最寄りフレームへ素直に追従し、この食い違いが起きない。 */
  onNow: () => void;
  /** フレーム一覧の取得中（初回フェッチがまだ終わっていない）。 */
  loading: boolean;
  /** loading中に表示するメッセージ（レイヤーごとに文言が異なるため呼び出し側から渡す）。 */
  loadingLabel: string;
  /** 取得に失敗したときのメッセージ。非nullのときスライダー自体は出さない。 */
  error: string | null;
  /** スライダー本体（role="slider"のルーラー）のaria-label。 */
  ariaLabel: string;
}

// 時刻依存レイヤー（降水ナウキャストT171・風T178等）共通の時刻スライダーUI（改善計画T170）。
// 地図の視界を圧迫しないよう（設計原則12）、時刻依存レイヤーが1つ以上ONの間だけpage.tsxが
// 条件付きでマウントする。実際の時刻の計算・URL組み立ては各レイヤー専用のデータ層
// （precipitationNowcast.ts/windLayer.ts）に閉じ、このコンポーネントはframesのindexを
// 操作するだけの汎用UIに徹する。T183再設計以降、ONの全レイヤーのフレーム時刻を
// dynamicWeather.ts: mergeFrameTimesで1本の共有タイムラインへ統合しているため、
// 複数の時刻依存レイヤーが同時にONでもこのコンポーネント自体は1つだけマウントする
// （旧設計は各レイヤーごとに独立したスライダーを縦に複数マウントしていたが、
// 「同じ日時を示した状態で連動させたい」という実機フィードバックを受け1本化した）。
//
// T255（UIライブラリ導入Phase3）でEmbla Carousel（+wheel-gesturesプラグイン）へ移行。
// 可変幅コマ・ホイールの横スクロール変換・離した位置への吸着はEmbla標準機能でカバーし、
// 自前だった設定確定タイマー・ドラッグのpointerイベント処理・ホイール変換のnative
// リスナーを撤去した。左端固定の目印に対する位置合わせは、Emblaのカスタムalign関数
// （align: (viewSize, snapSize) => INDICATOR_OFFSET_PX - snapSize / 2、下記emblaOptions）で
// 「コマの中心をINDICATOR_OFFSET_PXへ合わせる」既存の操作感をそのまま再現する。
// キーボード操作（Arrow/Home/End）・role="slider"のARIAはEmbla側が提供しないため、
// 従来どおり自前で用意する。
const emblaOptions = {
  axis: "x" as const,
  align: (viewSize: number, snapSize: number) => INDICATOR_OFFSET_PX - snapSize / 2,
  containScroll: false as const,
  dragFree: false,
};

export default function DynamicLayerTimeSlider({
  frames,
  index,
  onIndexChange,
  currentIndex,
  onNow,
  loading,
  loadingLabel,
  error,
  ariaLabel,
}: DynamicLayerTimeSliderProps) {
  const [emblaRef, emblaApi] = useEmblaCarousel(emblaOptions, [WheelGesturesPlugin({ forceWheelAxis: "x" })]);
  // 直近に自分がonIndexChangeへ報告した（またはpropsのindexとして反映済みの）index。
  // 確定（settle）時に検出したindexをここへ書き、「propsのindexが自分のドラッグ由来か・
  // 現在ボタン等の外部由来か」を判定する（外部由来のときだけプログラムでスクロールし直す。
  // 自分のドラッグが呼んだonIndexChangeでpropsが更新されるたびにまたスクロールし直す
  // 無限ループを避けるため）。
  const syncedIndexRef = useRef(index);
  // 初回マウント時はアニメーションさせず即座に開始位置へ合わせるための印。
  const hasMountedRef = useRef(false);

  // propsのindexが変化したら、ルーラーのスクロール位置を合わせる（「現在」ボタン等、
  // 自分のドラッグ操作以外でindexが変わったときだけ実際にスクロールする、上記コメント
  // 参照）。
  useEffect(() => {
    if (!emblaApi) return;
    const alreadySynced = index === syncedIndexRef.current;
    if (hasMountedRef.current && alreadySynced) return;
    syncedIndexRef.current = index;
    const prefersReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    emblaApi.scrollTo(index, !hasMountedRef.current || prefersReducedMotion);
    hasMountedRef.current = true;
  }, [emblaApi, index]);

  // 選ばれたコマが変わるたびonIndexChangeへ報告する。旧実装は「スクロール中の毎フレーム
  // 報告すると再描画・地図への反映が過剰に走るため、止まってからの1回にまとめる」設計で
  // settle相当のタイミングを狙っていたが、Emblaの`settle`イベントは実機検証で
  // （高速な合成ドラッグの後）発火しないケースが確認された。`select`イベントは
  // 「最寄りのスナップ位置（=選択中のコマ）が変わった瞬間」にのみ発火し、ドラッグ中の
  // 毎フレームでは発火しない（コマを跨いだ時だけ）ため、過剰報告の懸念自体は`select`でも
  // 生じない。
  useEffect(() => {
    if (!emblaApi) return;
    const handleSelect = () => {
      const next = emblaApi.selectedScrollSnap();
      if (next !== syncedIndexRef.current) {
        syncedIndexRef.current = next;
        onIndexChange(next);
      }
    };
    emblaApi.on("select", handleSelect);
    return () => {
      emblaApi.off("select", handleSelect);
    };
  }, [emblaApi, onIndexChange]);

  // キーボード操作（実機フィードバック「横スクロールでメモリの方が移動するように」で
  // ネイティブinput[type=range]をやめたため、矢印キー等の操作性は自前で用意する必要がある。
  // Emblaはキーボード操作を提供しないため引き続き自前）。onIndexChangeを直接呼び、
  // スクロール位置の追従は上のuseEffect（外部由来のindex変化）に任せる。
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (frames.length === 0) return;
    let next: number | null = null;
    if (e.key === "ArrowRight") next = Math.min(frames.length - 1, index + 1);
    else if (e.key === "ArrowLeft") next = Math.max(0, index - 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = frames.length - 1;
    if (next !== null && next !== index) {
      e.preventDefault();
      onIndexChange(next);
    }
  };

  if (error) {
    return (
      <div className={styles.wrapper}>
        <p className={styles.error}>{error}</p>
      </div>
    );
  }
  if (loading || frames.length === 0) {
    return (
      <div className={styles.wrapper}>
        <p className={styles.loading}>{loadingLabel}</p>
      </div>
    );
  }

  const frame = frames[Math.min(index, frames.length - 1)];

  return (
    <div className={styles.wrapper}>
      <div className={styles.panel}>
        {/* 現在選択中のコマの正確な日時（日付付き）。実機フィードバック「今の位置の正しい
            日時は左端ではなく上に出して」を受け、ルーラーの上へ1行で出す（以前はルーラーの
            左に横並びだった）。ルーラー側の目盛り文字（tickLabel）は日付を持たないため、
            日付をまたいだときの曖昧さはこの1行だけが解消する。 */}
        <div className={styles.timeHeader}>{frame.label}</div>
        <div className={styles.controlsRow}>
          {/* 実機フィードバック「見た目は現状のままで良くて、横スクロールでメモリの方が
              移動するようにしたい」への対応。ネイティブのinput[type=range]（つまみをドラッグ・
              目盛りへコマ送り）をやめ、横スクロールで目盛り自体を動かすルーラーに置き換えた。
              左端固定の目印（.leftIndicator、実機フィードバック「左端を表示時刻にして」）に
              対して、スクロールでどのコマを合わせるかを選ぶ操作感になる（Emblaのalign関数で
              実現、ファイル冒頭のemblaOptionsコメント参照）。 */}
          <div
            ref={emblaRef}
            className={styles.rulerViewport}
            onKeyDown={handleKeyDown}
            role="slider"
            tabIndex={0}
            aria-label={ariaLabel}
            aria-orientation="horizontal"
            aria-valuemin={0}
            aria-valuemax={frames.length - 1}
            aria-valuenow={index}
            aria-valuetext={frame.label}
          >
            <div className={styles.rulerTrack}>
              {frames.map((f, i) => (
                <div key={i} className={f.hourMark ? styles.tickHour : styles.tickMinor} style={{ width: frameWidth(f) }}>
                  <span className={styles.tickMark} aria-hidden="true" />
                  {/* 空文字でも.tickLabelの高さ・行送りは常に確保する（CSS側、コマによって
                      縦位置がガタつかないようにするコメント参照）ため、tickLabel無しのコマも
                      このspan自体は描画する。 */}
                  <span className={styles.tickLabel}>{f.tickLabel ?? ""}</span>
                </div>
              ))}
            </div>
            <div className={styles.leftIndicator} style={{ left: INDICATOR_OFFSET_PX }} aria-hidden="true" />
          </div>
          {/* 「現在」に戻るボタン（実機フィードバック「現況に戻すボタンも横に追加して」）。
              未来・過去側を見ていたスライダー位置を、ワンタップで実時刻へ戻す（onNowコメント
              参照）。既に「現在」を見ているときはno-opのため無効化する（MapOverlayControls.tsxの
              全レイヤー一括OFFボタンと同じ、押しても何も起きない状態を無効表示にする方針）。 */}
          <button
            type="button"
            className={styles.nowButton}
            onClick={onNow}
            disabled={index === currentIndex}
            aria-label={`${ariaLabel}を現在に戻す`}
            title="現在に戻す"
          >
            現在
          </button>
        </div>
      </div>
    </div>
  );
}
