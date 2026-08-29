"use client";

// 動的材料の状態別表現契約（改善計画T414、docs/tasks/T400.md「2. 動的要素…は状態（ルートの
// 有無）に応じてパラメータの出所と塗る対象が変わる」節）のうち、風の必要パラメータ
// （時刻＋向き）の「向き」を指定するコンパス型UI部品。時刻は既存の共有タイムライン
// （DynamicLayerTimeSlider、page.tsx）を引き続き使う——向きは0〜360度の円環データのため、
// 同じ横スクロールルーラーは流用できず（端と端が隣接するという性質を横一直線のルーラーでは
// 表現できない）、新規実装が必要だった。
//
// ライブラリ選定（T400.md「未決定だった論点の決着」節で事前調査済み）: 自前でSVG+
// pointer-eventsの角度計算を実装する代わりに `@fseehawer/react-circular-slider`
// （TypeScript完全対応・依存ライブラリ無し・MIT）を採用した。`value`/`onChange`による
// 制御コンポーネントとして使え、`knobPosition="top"`が0度を真上（北）に固定できるため、
// コンパスの見た目（北=0・時計回り）と素直に一致する。
//
// touch-action: 地図の上/近くに置く前提のため、BottomSheet等と同じくパン・ズーム
// ジェスチャーとの競合を避ける必要がある（T400.mdが実装時の要検証事項として明記）。
// ラッパーへtouch-action: noneを指定し、ドラッグ操作がライブラリのポインタハンドラだけに
// 渡るようにする。実機（実デバイスでのタッチ操作）での最終確認はT414実装時点で未実施——
// 実機確認が可能な環境がある場合は改めて確認すること。

import CircularSlider from "@fseehawer/react-circular-slider";
import styles from "./WindBearingSlider.module.css";

const CARDINAL_LABELS = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"] as const;

/** 0〜360度の向きを8方位の日本語ラベルへ変換する（コンパスの中央に出す読み上げ用）。 */
export function cardinalLabel(bearingDeg: number): string {
  const normalized = ((bearingDeg % 360) + 360) % 360;
  const index = Math.round(normalized / 45) % 8;
  return CARDINAL_LABELS[index];
}

interface WindBearingSliderProps {
  /** 0〜360度（北=0、時計回り）。 */
  value: number;
  onChange: (bearingDeg: number) => void;
  /** スライダー本体（role="slider"相当を持つライブラリ内部要素）のaria-label。 */
  ariaLabel: string;
}

// スライダーの表示直径（px）。DynamicLayerTimeSlider（.panel）と並べて地図下部へ置く前提の
// ため、時刻スライダーの高さと大きく乖離しないコンパクトなサイズにする。
const SLIDER_WIDTH_PX = 96;

export default function WindBearingSlider({ value, onChange, ariaLabel }: WindBearingSliderProps) {
  return (
    <div className={styles.wrapper}>
      <div className={styles.panel} aria-label={ariaLabel}>
        <CircularSlider
          width={SLIDER_WIDTH_PX}
          min={0}
          max={360}
          direction={1}
          knobPosition="top"
          value={value}
          onChange={(next) => onChange(typeof next === "number" ? next : Number(next))}
          hideLabelValue
          knobSize={18}
          progressSize={6}
          trackSize={6}
          progressColorFrom="#4990E2"
          progressColorTo="#80C3F3"
          trackColor="#dde1e6"
        >
          <span className={styles.centerValue}>{`${Math.round(value)}°`}</span>
          <span className={styles.centerCardinal}>{cardinalLabel(value)}</span>
        </CircularSlider>
      </div>
    </div>
  );
}
