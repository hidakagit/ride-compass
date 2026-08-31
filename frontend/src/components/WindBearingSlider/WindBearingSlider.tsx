"use client";

// 動的材料の状態別表現契約（改善計画T414、docs/tasks/T400.md「2. 動的要素…は状態（ルートの
// 有無）に応じてパラメータの出所と塗る対象が変わる」節）のうち、向きに依存する材料（風・
// 勾配）の「向き」を指定するコンパス型UI部品。時刻は（それに依存する材料[風]に限り）既存の
// 共有タイムライン（DynamicLayerTimeSlider、page.tsx）を引き続き使う——向きは0〜360度の
// 円環データのため、同じ横スクロールルーラーは流用できず（端と端が隣接するという性質を
// 横一直線のルーラーでは表現できない）、新規実装が必要だった。
//
// 勾配（第2の具体例、時刻非依存・向きのみ依存）も本コンポーネントを再利用する。
// value/onChange/ariaLabelという既存props自体が元々「向きだけ」を扱う汎用的な形のため、
// 風・勾配で個別にダイヤルを持たず、page.tsxの単一共有state（travelBearingDeg、
// ユーザー指摘2026-08-31「軸毎やレイヤ毎に走行方位が決められるけれど、1つでいい」を
// 受けて統合）を本コンポーネント1個（TravelBearingControl経由でマウント）で扱う
// 形へ揃えた。
//
// ユーザー指摘（2026-08-31、「コンパスは、例えばやじろべえ（→をくるくる回す形）に
// 変えられる？　触りにくい&進行方向を直感的に示していない」）: 従来は
// `@fseehawer/react-circular-slider`（円環+小さなノブをドラッグする形）を使っていたが、
// (1)ノブが移動するため掴み直しづらい（trackDraggableでリング全周へ広げる対症療法を
// 一度試みたが、根本的にノブ位置に依存する操作感自体は変わらなかった）、(2)円環上の
// 位置という抽象表現が「向き」を直感的に示さない、という2点の指摘を受け、自前実装の
// 「中心から伸びる矢印を直接つかんで回す」ダイヤルへ作り替えた。矢印自体が指す方向が
// そのまま値であるため直感的で、当たり判定も円全体（ノブの小さな一点ではない）に
// 広がる。角度計算はRouteSettingsPanel.tsx: startBoundaryDrag（帯グラフの境界ドラッグ）と
// 同じ「pointerdown起点でwindowへ直接pointermove/upを登録する」パターンを踏襲する
// （pointer captureが環境によって確実に効くとは限らないため使わない、という同じ理由）。

import { useRef } from "react";
import { WindDirectionArrowIcon } from "@/components/Map/icons";
import styles from "./WindBearingSlider.module.css";

const CARDINAL_LABELS = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"] as const;

/** 0〜360度の向きを8方位の日本語ラベルへ変換する（コンパスの読み上げ用）。
 * backend/app/domain/geo.py: compass_labelの二重実装——ラベル配列・丸めアルゴリズムとも
 * 同じ値を保つこと（既知の入出力ペアでドリフト検知するWindBearingSlider.test.ts参照）。 */
export function cardinalLabel(bearingDeg: number): string {
  const normalized = ((bearingDeg % 360) + 360) % 360;
  const index = Math.round(normalized / 45) % 8;
  return CARDINAL_LABELS[index];
}

function normalizeDeg(deg: number): number {
  return ((deg % 360) + 360) % 360;
}

interface WindBearingSliderProps {
  /** 0〜360度（北=0、時計回り）。 */
  value: number;
  onChange: (bearingDeg: number) => void;
  /** ダイヤル本体（role="slider"）のaria-label。 */
  ariaLabel: string;
}

// ユーザー要望（2026-08-31、「矢印をくるくる回すなら、矢印小さくすればもう少し
// 省スペースできない？」）: 以前のCircularSlider版（SLIDER_WIDTH_PX=96）に合わせていた
// フットプリントを縮小した。当たり判定は円環の一部ではなくこの円全体（当たり判定の
// 広さ自体はDIAL_SIZE_PXの縮小後も従来のリング1本[6px幅]よりずっと広い）。
const DIAL_SIZE_PX = 68;
// 矢印の長さ（px）。ダイヤルの直径いっぱいに近いサイズにして「中心から伸びる矢印」を
// 一目で認識できるようにする。
const ARROW_SIZE_PX = 44;
// キーボード操作（矢印キー）1回あたりの移動量。ドラッグに比べて大きな単位で十分
// （方向指定はドラッグ操作を主として想定しているため）。
const KEY_STEP_DEG = 5;

export default function WindBearingSlider({ value, onChange, ariaLabel }: WindBearingSliderProps) {
  const dialRef = useRef<HTMLDivElement>(null);

  // 中心からポインタ位置までの角度（北=0、時計回り）を求める。dx/dyが両方0
  // （ポインタが中心そのもの）でもatan2(0,0)=0を返すため安全（NaNにならない）。
  function angleFromPoint(clientX: number, clientY: number): number {
    const dial = dialRef.current;
    if (!dial) return value;
    const rect = dial.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const dx = clientX - cx;
    const dy = clientY - cy;
    const radians = Math.atan2(dx, -dy);
    return normalizeDeg((radians * 180) / Math.PI);
  }

  function startDrag(e: React.PointerEvent<HTMLDivElement>) {
    onChange(angleFromPoint(e.clientX, e.clientY));
    const handlePointerMove = (moveEvent: PointerEvent) => {
      onChange(angleFromPoint(moveEvent.clientX, moveEvent.clientY));
    };
    const handlePointerUp = () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    let delta = 0;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") delta = -KEY_STEP_DEG;
    else if (e.key === "ArrowRight" || e.key === "ArrowUp") delta = KEY_STEP_DEG;
    else return;
    e.preventDefault();
    onChange(normalizeDeg(value + delta));
  }

  const roundedValue = Math.round(value);
  return (
    <div className={styles.wrapper}>
      <div className={styles.panel}>
        <div
          ref={dialRef}
          className={styles.dial}
          style={{ width: DIAL_SIZE_PX, height: DIAL_SIZE_PX }}
          role="slider"
          aria-label={ariaLabel}
          aria-valuemin={0}
          aria-valuemax={360}
          aria-valuenow={roundedValue}
          aria-valuetext={`${roundedValue}度（${cardinalLabel(value)}）`}
          tabIndex={0}
          onPointerDown={startDrag}
          onKeyDown={handleKeyDown}
        >
          <span
            aria-hidden="true"
            className={styles.arrow}
            style={{ width: ARROW_SIZE_PX, height: ARROW_SIZE_PX, transform: `rotate(${value}deg)` }}
          >
            <WindDirectionArrowIcon size={ARROW_SIZE_PX} />
          </span>
        </div>
        <p className={styles.readout}>
          {roundedValue}° {cardinalLabel(value)}
        </p>
      </div>
    </div>
  );
}
