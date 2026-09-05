"use client";

import { useEffect, useRef } from "react";
import useEmblaCarousel from "embla-carousel-react";
import { WheelGesturesPlugin } from "embla-carousel-wheel-gestures";
import styles from "./DynamicLayerTimeSlider.module.css";

/** スライダーの1フレーム分の表示内容。ONの全レイヤーのフレーム時刻を統合した1本の
 * 共有タイムラインを表すため、時刻ラベルのみを持つ（レイヤー固有の実況/予測ラベルは、
 * 1つの目盛りに複数レイヤーが同時に対応しうる設計では意味を持たないため持たない、
 * dynamicWeather.ts: formatDynamicFrameTime参照）。
 * labelは左端の指標の上に出す1行サマリ用で、日付をまたぐタイムラインの曖昧さを避けるため
 * 常に日付を含むフル表記（dynamicWeather.ts: formatDynamicFrameTime）。hourMarkはルーラーの
 * 目盛りの線を太くするかどうか（呼び出し側=page.tsxが正時判定して渡す）。降水ナウキャスト
 * （5分刻み、〜60分先）の区間では正時フレームがまばらにしか無く目盛りもまばらに、延長予報
 * （1時間刻み、〜48時間先）の区間では全フレームが正時のため毎コマに目盛りが付く。スライダー
 * 自体はコマ（インデックス）ごとに等間隔で並ぶ設計のままのため、目盛りをフレームごとの
 * 正時判定で間引くだけで「近い将来は目盛りがまばら＝連続的に細かく動かせる、遠い将来は
 * 毎コマに目盛り＝1時間刻みで止まる」という実際の間隔設計がひと目で伝わる（間隔設計自体は
 * 変更しない）。tickLabelは目盛りの線の下に出す短い文字。日付を持たず、正時なら
 * 「HH:mm」・そうでなければ分のみ2桁（RideConditionBar/departureTimeline.ts:
 * buildDepartureFrames参照）。undefined/空文字ならこのコマには文字を出さない
 * （延長予報のように毎コマ正時が続く区間で毎コマぶん文字まで出すと、1コマの目盛り間隔
 * [TICK_SPACING_HOUR_PX]に対して文字幅の方が広く重なってしまうため、呼び出し側で
 * 正時ラベルはさらに間引いて渡す）。 */
export interface DynamicLayerTimeSliderFrame {
  label: string;
  hourMark?: boolean;
  tickLabel?: string;
}

// 1コマぶんの目盛り間隔（px、正時以外＝降水ナウキャストの5分刻み等の密なコマ）。
const TICK_SPACING_PX = 18;
// 正時（hourMark）ぶんの目盛り間隔（px）。延長予報区間（60分以降、全コマが正時＝1時間刻み）
// はこちらを使う。初期画面に全コマが収まっている必要はなく、スクロールできれば足りるという
// 前提のため、広げた分だけルーラー全体の総幅・スクロール量が伸びることは許容する。
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
  /** 「現在」に相当するframesのindex。「現在」ボタンを無効化する判定
   * （index===currentIndexの間はno-op）にのみ使う。ジャンプ先の決定はonNowが担う
   * （このindexそのものへは飛ばない、下記onNowのコメント参照）。 */
  currentIndex: number;
  /** 「現在」ボタンを押したときの処理。呼び出し側が実時刻（`new Date()`）へ選択中の時刻を
   * 戻す想定。onIndexChange(currentIndex)を呼ばないのは、currentIndexはframesの目盛り
   * 間隔に丸めた近似値であり、実時刻そのものより粗いため。 */
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

// ドラッグ/横スクロールで時刻を選ぶ汎用タイムラインUI。frames/index/onIndexChangeだけを
// 操作し、時刻の計算・生成元（気象レイヤーのフレーム列か、それ以外の合成タイムラインか）は
// 一切知らない。呼び出し側（`RideConditionBar`: 出発時刻ピッカー）がタイムラインの生成・
// 現在時刻との対応付けを担う。
//
// Embla Carousel（+wheel-gesturesプラグイン）を使う。可変幅コマ・ホイールの横スクロール
// 変換・離した位置への吸着はEmbla標準機能でカバーする。左端固定の目印に対する位置合わせは、
// Emblaのカスタムalign関数（align: (viewSize, snapSize) => INDICATOR_OFFSET_PX - snapSize / 2、
// 下記emblaOptions）で「コマの中心をINDICATOR_OFFSET_PXへ合わせる」操作感を実現する。
// キーボード操作（Arrow/Home/End）・role="slider"のARIAはEmbla側が提供しないため自前で
// 用意する。
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

  // 選ばれたコマが変わるたびonIndexChangeへ報告する。Emblaの`settle`イベントは高速な
  // ドラッグの後に発火しないことがあるため使わない。`select`イベントは「最寄りのスナップ
  // 位置（=選択中のコマ）が変わった瞬間」にのみ発火し、ドラッグ中の毎フレームでは発火しない
  // （コマを跨いだ時だけ）ため、スクロール中に過剰報告されることもない。
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

  // キーボード操作。ネイティブinput[type=range]ではなく横スクロールのルーラーのため、
  // 矢印キー等の操作性はEmblaが提供しない分を自前で用意する。onIndexChangeを直接呼び、
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

  // 1コマ戻る/進むボタン。ドラッグは大まかな位置合わせ、このボタンはピンポイントの
  // 1コマ単位調整という役割分担。キーボードのArrowLeft/Rightと同じ移動量だが、
  // タップ操作の主要導線として並べる。
  const stepIndex = (delta: number) => {
    if (frames.length === 0) return;
    const next = Math.min(frames.length - 1, Math.max(0, index + delta));
    if (next !== index) onIndexChange(next);
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
        {/* 現在選択中のコマの正確な日時（日付付き）。ルーラーの上へ1行で出す。ルーラー側の
            目盛り文字（tickLabel）は日付を持たないため、日付をまたいだときの曖昧さはこの
            1行だけが解消する。 */}
        <div className={styles.timeHeader}>{frame.label}</div>
        <div className={styles.controlsRow}>
          {/* 1つ前のコマへ（上記stepIndexコメント参照）。 */}
          <button
            type="button"
            className={styles.stepButton}
            onClick={() => stepIndex(-1)}
            disabled={index <= 0}
            aria-label={`${ariaLabel}を1つ前へ`}
            title="1つ前へ"
          >
            ‹
          </button>
          {/* ネイティブのinput[type=range]（つまみをドラッグ・目盛りへコマ送り）ではなく、
              横スクロールで目盛り自体を動かすルーラー。左端固定の目印（.leftIndicator）に
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
          {/* 1つ次のコマへ（上記「1つ前のコマへ」ボタンと対）。 */}
          <button
            type="button"
            className={styles.stepButton}
            onClick={() => stepIndex(1)}
            disabled={index >= frames.length - 1}
            aria-label={`${ariaLabel}を1つ次へ`}
            title="1つ次へ"
          >
            ›
          </button>
          {/* 「現在」に戻るボタン。未来・過去側を見ていたスライダー位置を、ワンタップで
              実時刻へ戻す（onNowコメント参照）。既に「現在」を見ているときはno-opのため
              無効化する（MapOverlayControls.tsxの全レイヤー一括OFFボタンと同じ、押しても
              何も起きない状態を無効表示にする方針）。 */}
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
