"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from "react";
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
// 許容する。コマごとに幅が異なるため、位置計算はindex * 定数の単純な乗算ではなく
// tickOffsets（下記）の累積和で求める（frameWidth/tickCenterが唯一の情報源）。
const TICK_SPACING_HOUR_PX = 28;
// スクロール位置を合わせる「左端の目印」(.leftIndicator)の、ビューポート左端からの固定
// オフセット（px、スクロールしても動かない）。個々のコマの幅（正時/非正時で異なる）とは
// 独立した値のため、常にTICK_SPACING_PXの半分のまま変えない。
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
  const viewportRef = useRef<HTMLDivElement>(null);
  // 直近に自分がonIndexChangeへ報告した（またはpropsのindexとして反映済みの）index。
  // スクロール確定時に検出したindexをここへ書き、「propsのindexが自分のスクロール由来か・
  // 現在ボタン等の外部由来か」を判定する（外部由来のときだけプログラムでスクロールし直す。
  // 自分のスクロールが呼んだonIndexChangeでpropsが更新されるたびにまたスクロールし直す
  // 無限ループを避けるため）。
  const syncedIndexRef = useRef(index);
  // 初回マウント時はアニメーションさせず即座に開始位置へ合わせるための印。
  const hasMountedRef = useRef(false);
  const settleTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // 各コマの左端オフセット（tickOffsets[i]、トラック内のpxの累積和）。正時/非正時でコマ幅が
  // 異なる（frameWidth）ため、以前のようなindex * 定数の単純な乗算では位置が求まらない。
  // framesが変わらない限り同じ参照を返す（useLayoutEffect/handleScrollのuseCallback依存に
  // 使うため、毎レンダー新しい配列/関数になるのを避ける）。
  const tickOffsets = useMemo(() => {
    const offsets: number[] = [];
    let acc = 0;
    for (const f of frames) {
      offsets.push(acc);
      acc += frameWidth(f);
    }
    return offsets;
  }, [frames]);
  // コマiの中心のトラック内オフセット（px）。scrollLeftがこの値からINDICATOR_OFFSET_PXを
  // 引いた位置のとき、コマiの中心が.leftIndicatorへちょうど重なる。
  const tickCenter = useCallback(
    (i: number): number => {
      const f = frames[i];
      return f ? tickOffsets[i] + frameWidth(f) / 2 : 0;
    },
    [frames, tickOffsets]
  );

  // propsのindexが変化したら、ルーラーのスクロール位置を合わせる（「現在」ボタン等、
  // 自分のスクロール操作以外でindexが変わったときだけ実際にスクロールする、上記コメント
  // 参照）。レイアウト確定後・ペイント前に合わせたいのでuseLayoutEffect
  // （useEffectだと初回マウント時に一瞬scrollLeft=0が見えてしまう）。
  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const alreadySynced = index === syncedIndexRef.current;
    if (hasMountedRef.current && alreadySynced) return;
    syncedIndexRef.current = index;
    const targetLeft = tickCenter(index) - INDICATOR_OFFSET_PX;
    // jsdom（テスト環境）はElement.scrollToを実装しないため、scrollLeftへの直接代入へ
    // フォールバックする（挙動としてはbehavior: "auto"と同じ即時ジャンプ）。
    if (typeof viewport.scrollTo === "function") {
      const prefersReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      viewport.scrollTo({ left: targetLeft, behavior: hasMountedRef.current && !prefersReducedMotion ? "smooth" : "auto" });
    } else {
      viewport.scrollLeft = targetLeft;
    }
    hasMountedRef.current = true;
  }, [index, tickCenter]);

  // スクロールが落ち着いたタイミング（連続するscrollイベントが一定時間止まったとき）で
  // 左端の目印に最も近いコマを確定させ、onIndexChangeへ報告する。スクロール中の毎フレーム
  // 報告すると再描画・地図への反映が過剰に走るため、ドラッグ/ホイールが止まってからの1回に
  // まとめる（自前ドラッグ実装のためCSSのscroll-snapには頼らず、この確定処理自体が
  // 「最寄りのコマへ寄せる」役割を兼ねる）。
  const handleScroll = () => {
    const viewport = viewportRef.current;
    if (!viewport || frames.length === 0) return;
    if (settleTimerRef.current) clearTimeout(settleTimerRef.current);
    settleTimerRef.current = setTimeout(() => {
      // コマごとに幅が異なる（frameWidth）ため、単純な除算ではなく「コマの中心が
      // .leftIndicatorに最も近い」コマを総当たりで探す（コマ数は最大でも数十〜百程度の
      // オーダーのため、スクロール確定時の1回だけの実行なら線形探索で十分）。
      const target = viewport.scrollLeft + INDICATOR_OFFSET_PX;
      let next = 0;
      let nearestDist = Infinity;
      for (let i = 0; i < frames.length; i++) {
        const dist = Math.abs(tickCenter(i) - target);
        if (dist < nearestDist) {
          nearestDist = dist;
          next = i;
        }
      }
      // CSSのscroll-snapに頼らない自前ドラッグのため、最寄りのコマの厳密な位置へここで
      // 明示的に寄せる（ドラッグ/ホイールを離した位置が必ずしもコマの区切りぴったりとは
      // 限らないため）。
      const targetLeft = tickCenter(next) - INDICATOR_OFFSET_PX;
      if (Math.abs(viewport.scrollLeft - targetLeft) > 0.5) {
        if (typeof viewport.scrollTo === "function") {
          viewport.scrollTo({ left: targetLeft, behavior: "smooth" });
        } else {
          viewport.scrollLeft = targetLeft;
        }
      }
      if (next !== syncedIndexRef.current) {
        syncedIndexRef.current = next;
        onIndexChange(next);
      }
    }, 90);
  };

  // 普通のマウスホイール（トラックパッドの横スワイプと違い、縦方向のdeltaYしか出ない）を
  // 横スクロールへ変換する（実機フィードバック「ルーラースクロールできない」。横スクロール
  // 専用のこの要素は、素のブラウザ既定動作だと縦方向のホイール入力に反応しない）。横方向の
  // 入力（トラックパッドの横スワイプ等、ブラウザのネイティブpan-xで既に効く）の方が大きい
  // ときは変換しない。ReactのonWheelはReact 17以降ルート委譲がpassive: trueで登録される
  // ため、合成イベント内でpreventDefaultを呼んでも無効化されない（コンソール警告になる
  // だけ）。ネイティブのaddEventListenerでpassive: falseとして登録する必要があるため、
  // ここはuseEffectで直接DOMへ張る。
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const handleWheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
      viewport.scrollLeft += e.deltaY;
      e.preventDefault();
    };
    viewport.addEventListener("wheel", handleWheel, { passive: false });
    return () => viewport.removeEventListener("wheel", handleWheel);
  }, [loading, error, frames.length]);

  // ポインタでのドラッグ操作（実機フィードバック「ルーラースクロールできない」）。当初は
  // タッチ/トラックパッドをブラウザのネイティブ横スクロール（touch-action: pan-x）に任せ、
  // マウスドラッグだけ自前で足す設計にしていたが、実機で「スマホで変わらず横スクロールで
  // バーを動かせない」との再報告を受けた。ネイティブのタッチスクロールは検証環境
  // （Playwright+CDPのタッチイベント合成）では再現できたものの、実機のブラウザ実装差
  // （iOS Safari等）に起因する可能性が高く切り分けが難しいため、タッチ/マウス/ペンいずれも
  // ポインタイベントで自前ドラッグする設計へ統一し、ブラウザのネイティブスクロールには
  // 依存しない（CSS側もtouch-action: noneへ変更、下記参照）。他の地図上コントロール
  // （MapOverlayControls.tsxの.iconChip等）も同様に「touch-action: none+実際のジェスチャーは
  // JSで処理」という方針のため、この方が既存の設計とも一貫する。
  const dragRef = useRef<{ pointerId: number; startClientX: number; startScrollLeft: number } | null>(null);
  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    // 実機フィードバック「マウスをハンドアイコンに変わるが動かない/タッチでも反応しない」
    // への対応。preventDefaultを呼んでいなかったため、mousedown+dragがブラウザ既定の
    // テキスト選択ドラッグとして処理され、pointermove自体はスクリプトへ届いても既定動作と
    // 競合して見た目に反映されていなかったと考えられる。ここで既定動作を止める。
    e.preventDefault();
    dragRef.current = { pointerId: e.pointerId, startClientX: e.clientX, startScrollLeft: viewport.scrollLeft };
    // 一部のブラウザ/状況（例: 既にキャプチャ済みのポインタ）ではsetPointerCaptureが
    // 例外を投げることがあるが、ドラッグ自体はpointermoveのイベント委譲だけでも機能するため
    // 致命的ではない。
    try {
      viewport.setPointerCapture(e.pointerId);
    } catch {
      // no-op
    }
  };
  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    const viewport = viewportRef.current;
    if (!drag || drag.pointerId !== e.pointerId || !viewport) return;
    e.preventDefault();
    viewport.scrollLeft = drag.startScrollLeft - (e.clientX - drag.startClientX);
  };
  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId === e.pointerId) dragRef.current = null;
  };

  // キーボード操作（実機フィードバック「横スクロールでメモリの方が移動するように」で
  // ネイティブinput[type=range]をやめたため、矢印キー等の操作性は自前で用意する必要がある）。
  // ArrowLeft/Right=1コマ、Home/End=両端へ。onIndexChangeを直接呼び、スクロール位置の追従は
  // 上のuseLayoutEffect（外部由来のindex変化）に任せる。
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
  // トラックの左右パディング。左指標（.leftIndicator、ルーラー左端から固定オフセット
  // INDICATOR_OFFSET_PX内側の固定位置、実機フィードバック「左端を表示時刻にして」）に
  // 最後のコマの中心も届くよう、右側は「ビューポート幅 - 最後のコマの幅」を確保する
  // （左側パディングは0のまま。ファイル冒頭のtickCenter/frameWidthコメント参照、
  // layoutEffect/handleScrollの計算はこの前提で書いている）。
  const trackPaddingRight = `calc(100% - ${frameWidth(frames[frames.length - 1])}px)`;

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
              対して、スクロールでどのコマを合わせるかを選ぶ操作感になる。 */}
          <div
            ref={viewportRef}
            className={styles.rulerViewport}
            onScroll={handleScroll}
            onKeyDown={handleKeyDown}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            role="slider"
            tabIndex={0}
            aria-label={ariaLabel}
            aria-orientation="horizontal"
            aria-valuemin={0}
            aria-valuemax={frames.length - 1}
            aria-valuenow={index}
            aria-valuetext={frame.label}
          >
            <div className={styles.rulerTrack} style={{ paddingRight: trackPaddingRight }}>
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
