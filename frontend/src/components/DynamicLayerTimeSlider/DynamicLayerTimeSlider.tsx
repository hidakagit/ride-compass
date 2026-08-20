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
   * windLayer.ts: nearestFrameIndexToNowを呼び出し側が計算した値）。「現在」ボタンの
   * ジャンプ先、かつindexと一致する間はボタンを無効化する判定にも使う。 */
  currentIndex: number;
  /** フレーム一覧の取得中（初回フェッチがまだ終わっていない）。 */
  loading: boolean;
  /** loading中に表示するメッセージ（レイヤーごとに文言が異なるため呼び出し側から渡す）。 */
  loadingLabel: string;
  /** 取得に失敗したときのメッセージ。非nullのときスライダー自体は出さない。 */
  error: string | null;
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
  loading,
  loadingLabel,
  error,
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
            未来側を見ていたスライダー位置を、ワンタップで「現在」（precipitationNowcast.ts:
            latestObservedFrameIndex・windLayer.ts: nearestFrameIndexToNow）へ戻す。
            既に「現在」を見ているときはno-opのため無効化する（MapOverlayControls.tsxの
            全レイヤー一括OFFボタンと同じ、押しても何も起きない状態を無効表示にする方針）。 */}
        <button
          type="button"
          className={styles.nowButton}
          onClick={() => onIndexChange(currentIndex)}
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
