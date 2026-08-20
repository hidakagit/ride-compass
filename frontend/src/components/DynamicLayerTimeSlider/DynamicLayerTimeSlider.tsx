"use client";

import styles from "./DynamicLayerTimeSlider.module.css";

/** スライダーの1フレーム分の表示内容。時刻の計算・整形は呼び出し側
 * （precipitationNowcast.ts/windLayer.ts）が済ませた結果だけを渡す
 * （このコンポーネント自体はレイヤー固有の時刻形式を一切知らない）。 */
export interface DynamicLayerTimeSliderFrame {
  label: string;
  badge?: string;
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
  /** 他レイヤー（複数の時刻依存レイヤーが同時ONのとき）に引っ張られて、このレイヤー自身の
   * データ範囲外の時刻を指しているときtrue（例: 風バーを風だけが持つ48時間先まで動かすと、
   * ±1時間程度しかデータの無い降水ナウキャスト側がこの状態になる。改善計画、実機
   * フィードバック「対応データなしと明示する」）。true の間はスライダーを出さずグレーアウトの
   * メッセージへ差し替える（loading/errorと同じ扱い）。このコンポーネント自体は「範囲外」の
   * 判定方法を知らない汎用UIのため、判定は呼び出し側（各レイヤーのデータ層）が行う。 */
  unavailable?: boolean;
  /** unavailable=true のときに表示するメッセージ。 */
  unavailableLabel?: string;
  /** スライダー本体（input[type=range]）のaria-label。 */
  ariaLabel: string;
}

// 時刻依存レイヤー（降水ナウキャストT171・風T178等）共通の時刻スライダーUI（改善計画T170）。
// 地図の視界を圧迫しないよう（設計原則12）、時刻依存レイヤーがONの間だけpage.tsxが
// 条件付きでマウントする。実際の時刻の計算・URL組み立ては各レイヤー専用のデータ層
// （precipitationNowcast.ts/windLayer.ts）に閉じ、このコンポーネントはframesのindexを
// 操作するだけの汎用UIに徹する（複数の時刻依存レイヤーが同時にONのときは、page.tsxが
// このコンポーネントを縦に複数マウントする）。
export default function DynamicLayerTimeSlider({
  frames,
  index,
  onIndexChange,
  currentIndex,
  onNow,
  loading,
  loadingLabel,
  error,
  unavailable,
  unavailableLabel,
  ariaLabel,
}: DynamicLayerTimeSliderProps) {
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
  if (unavailable) {
    return (
      <div className={styles.wrapper}>
        <p className={styles.unavailable}>{unavailableLabel}</p>
      </div>
    );
  }

  const frame = frames[Math.min(index, frames.length - 1)];

  return (
    <div className={styles.wrapper}>
      <div className={styles.row}>
        <span className={styles.time}>
          {frame.label}
          {frame.badge && <span className={styles.badge}>{frame.badge}</span>}
        </span>
        <input
          type="range"
          className={styles.slider}
          min={0}
          max={frames.length - 1}
          step={1}
          value={index}
          aria-label={ariaLabel}
          onChange={(e) => onIndexChange(Number(e.target.value))}
        />
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
  );
}
