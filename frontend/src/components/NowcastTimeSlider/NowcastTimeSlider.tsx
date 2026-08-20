"use client";

import { formatNowcastFrameTime, type NowcastFrame } from "@/components/Map/precipitationNowcast";
import styles from "./NowcastTimeSlider.module.css";

interface NowcastTimeSliderProps {
  frames: readonly NowcastFrame[];
  /** framesのindex。framesが空、またはまだ範囲外なら効果なし（呼び出し側でclamp済み前提）。 */
  index: number;
  onIndexChange: (index: number) => void;
  /** フレーム一覧の取得中（初回フェッチがまだ終わっていない）。 */
  loading: boolean;
  /** 取得に失敗した（両方の時刻一覧が取れなかった）ときのメッセージ。 */
  error: string | null;
}

// 降水ナウキャストの時刻スライダー（改善計画T170）。地図の視界を圧迫しないよう
// （設計原則12）、時刻依存レイヤー（降水ナウキャスト、mapLayers.ts:
// precipitationNowcast）がONのときだけpage.tsxが条件付きでマウントする。スライダー自体は
// framesのindexだけを操作し、実際の時刻・URL計算はprecipitationNowcast.ts側に閉じる
// （このコンポーネントはUIのみを持つ）。
export default function NowcastTimeSlider({ frames, index, onIndexChange, loading, error }: NowcastTimeSliderProps) {
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
        <p className={styles.loading}>降水ナウキャストの時刻を取得中...</p>
      </div>
    );
  }

  const frame = frames[Math.min(index, frames.length - 1)];
  const timeLabel = formatNowcastFrameTime(frame.validtime);

  return (
    <div className={styles.wrapper}>
      <div className={styles.row}>
        <span className={styles.time}>
          {timeLabel}
          <span className={styles.badge}>{frame.isForecast ? "予測" : "実況"}</span>
        </span>
        <input
          type="range"
          className={styles.slider}
          min={0}
          max={frames.length - 1}
          step={1}
          value={index}
          aria-label="降水ナウキャストの表示時刻"
          onChange={(e) => onIndexChange(Number(e.target.value))}
        />
      </div>
    </div>
  );
}
