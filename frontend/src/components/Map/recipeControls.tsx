"use client";

import { useState } from "react";
import { InfoIcon } from "./icons";
import styles from "./recipeControls.module.css";

// レシピ入力フォーム（研究タブの各レシピパネル）共通のUI部品。T113でTrafficStressRecipePanel
// 専用に実装したものを、2つ目のレシピ（安全度レシピ）登場を機に汎用化した（改善計画:
// 安全度レシピ。「今後ほかの2次データのレシピが増えると思うので、くくり出してほしい」という
// ユーザー要望への対応）。段階数・色パレットは呼び出し側がpropsで渡すため、レシピごとの
// 段階数・配色差（例: 交通ストレスの緑〜赤、安全度のteal〜dark-red）はこのファイルの変更
// なしで吸収できる。

// 基準値のレベルピッカー。levelsぶんのボタンを並べ、選択値以下の段階をcolorsの色で塗って
// 進捗バー風に見せる。
export function LevelPicker({
  levels,
  colors,
  value,
  onChange,
  groupLabel,
}: {
  levels: number[];
  colors: Record<number, string>;
  value: number;
  onChange: (next: number) => void;
  groupLabel: string;
}) {
  return (
    <div className={styles.levelPicker} role="group" aria-label={groupLabel}>
      {levels.map((level) => (
        <button
          key={level}
          type="button"
          aria-pressed={value === level}
          aria-label={String(level)}
          data-filled={level <= value}
          className={styles.levelSegment}
          style={{ "--level-color": colors[level] } as React.CSSProperties}
          onClick={() => onChange(level)}
        >
          {level}
        </button>
      ))}
    </div>
  );
}

// 補正値のステッパー。-/+ボタン付きの数値入力欄。負値・正値に応じて呼び出し側が渡す色
// （地図の色分けの最低/最高段階から算出）で塗り、「0中心に変動する」ことを色だけで
// 確実に伝える（数値入力欄自体は残しているため直接タイプでの入力も引き続きできる）。
export function AdjustmentStepper({
  label,
  value,
  onChange,
  negativeColor,
  positiveColor,
}: {
  label: string;
  value: number;
  onChange: (next: number) => void;
  negativeColor: string;
  positiveColor: string;
}) {
  const color = value < 0 ? negativeColor : value > 0 ? positiveColor : undefined;
  return (
    <span className={styles.stepper}>
      <button
        type="button"
        className={styles.stepperButton}
        aria-label={`${label}を1減らす`}
        onClick={() => onChange(value - 1)}
      >
        −
      </button>
      <input
        type="number"
        step="1"
        aria-label={label}
        value={value}
        onChange={(e) => {
          const next = Number(e.target.value);
          if (Number.isNaN(next)) return;
          onChange(next);
        }}
        className={styles.stepperInput}
        style={color ? { background: color, borderColor: color, color: "#ffffff" } : undefined}
      />
      <button
        type="button"
        className={styles.stepperButton}
        aria-label={`${label}を1増やす`}
        onClick={() => onChange(value + 1)}
      >
        ＋
      </button>
    </span>
  );
}

// フィールドラベル+情報アイコン。タップでも確実に開くクリック式の開閉ボタン
// （MapOverlayControlsのaria-expanded凡例トグルと同じ規約）。説明本体（infoTooltip）は
// open/onToggleを渡す呼び出し側が、DOM上input/tr等の後ろへ別要素として配置する
// （このコンポーネント自身はラベル行だけを返す）。`className`は任意の追加クラス
// （改善計画T118のモバイル幅溢れ修正: highway別基準値テーブル内では
// nowrap/flex-shrink:0を打ち消して折り返しを許可する必要があり、呼び出し側の
// module.cssでその上書きクラスを定義してここへ渡す）。
function formatSignedTerm(value: number): string {
  return value >= 0 ? `+${value}` : `${value}`;
}

// 「車の圧迫感」「安全度」パネルの先頭に置く読み取り専用の参照セクション（改善計画:
// 車との近さ材料の共有元化）。両軸が共有する「道路適正」「自動車密度」の現在値
// （研究モードで上書き中ならその値、既定ならDEFAULT_*）を一覧表示し、「この軸がどの
// 土台の上に成り立っているか」を視覚的に示す。編集はできない（編集は道路適正/自動車密度
// パネル側で行う）。highway別基準値テーブル自体はここでは繰り返さず、専用パネルへの
// 導線だけにする（12行の読み取り専用テーブルを3枚目・4枚目にも複製しないため）。
export function CarClosenessReferenceSection({
  roadSuitabilityRecipe,
  motorVehicleDensityRecipe,
}: {
  roadSuitabilityRecipe: {
    cycleway_track_adjustment: number;
    cycleway_lane_adjustment: number;
    cycleway_shared_adjustment: number;
  };
  motorVehicleDensityRecipe: {
    maxspeed_low_threshold: number;
    maxspeed_low_adjustment: number;
    maxspeed_high_threshold: number;
    maxspeed_high_adjustment: number;
    lanes_high_threshold: number;
    lanes_high_adjustment: number;
    designation_adjustment: number;
  };
}) {
  return (
    <details className={styles.referenceSection}>
      <summary className={styles.referenceHeader}>
        <span aria-hidden="true" className={styles.referenceChevron} />
        土台: 道路適正＋自動車密度[車との近さ](読み取り専用)
      </summary>
      <div className={styles.referenceBody}>
        <p className={styles.referenceIntro}>
          この軸は「道路適正」「自動車密度」レシピの上に成り立っています。編集はそれぞれのパネルで行ってください。
        </p>
        <ul className={styles.referenceList}>
          <li>
            専用レーン: {formatSignedTerm(roadSuitabilityRecipe.cycleway_track_adjustment)} ／ 自転車レーン:{" "}
            {formatSignedTerm(roadSuitabilityRecipe.cycleway_lane_adjustment)} ／ 共有レーン:{" "}
            {formatSignedTerm(roadSuitabilityRecipe.cycleway_shared_adjustment)}
          </li>
          <li>
            制限速度{motorVehicleDensityRecipe.maxspeed_low_threshold}km/h以下:{" "}
            {formatSignedTerm(motorVehicleDensityRecipe.maxspeed_low_adjustment)} ／ 制限速度
            {motorVehicleDensityRecipe.maxspeed_high_threshold}km/h以上:{" "}
            {formatSignedTerm(motorVehicleDensityRecipe.maxspeed_high_adjustment)}
          </li>
          <li>
            車線数{motorVehicleDensityRecipe.lanes_high_threshold}以上:{" "}
            {formatSignedTerm(motorVehicleDensityRecipe.lanes_high_adjustment)}
          </li>
          <li>指定路線: {formatSignedTerm(motorVehicleDensityRecipe.designation_adjustment)}</li>
        </ul>
        <p className={styles.referenceIntro}>道路種別ごとの基準値は「道路適正」パネルで確認できます。</p>
      </div>
    </details>
  );
}

// TRAFFIC_STRESS_COLORSの最小/最大段階の色を補正値ステッパーの負値/正値表示に使う
// （改善計画: 車との近さ材料の共有元化のレビュー指摘。4パネル中3パネルが
// `TRAFFIC_STRESS_COLORS[1]`/`[5]`を、RoadSuitabilityRecipePanelだけが値域の違い
// （道路適正の基準値は1〜4で5段階目を使わない）から`[1]`/`[4]`を、それぞれのファイルへ
// 個別にハードコードしていた。呼び出し側ごとに使う範囲が異なるため単一の共有定数には
// できないが、「TRAFFIC_STRESS_COLORSから最小・最大段階の色を引く」という手順自体は
// ここへ1箇所へ集約する）。
export function adjustmentEndpointColors(
  colors: Record<number, string>,
  minLevel: number,
  maxLevel: number,
): { negativeColor: string; positiveColor: string } {
  return { negativeColor: colors[minLevel], positiveColor: colors[maxLevel] };
}

// TRecipeの中で値がnumber型のキーだけを抽出する（base_by_highwayのようなobject型の
// フィールドを持つRoadSuitabilityRecipeでも、ScalarInput/ThresholdAdjustmentRowの対象を
// 数値フィールドだけに安全に絞り込むため）。
type NumericKeys<TRecipe> = { [K in keyof TRecipe]: TRecipe[K] extends number ? K : never }[keyof TRecipe];

export interface ScalarFieldDescriptor<TRecipe, TKey extends NumericKeys<TRecipe> = NumericKeys<TRecipe>> {
  key: TKey;
  label: string;
  description: string;
}

// 単一の補正値フィールド（ラベル+ステッパー+説明）の入力欄（改善計画: 車との近さ材料の
// 共有元化のレビュー指摘。RoadSuitabilityRecipePanel/MotorVehicleDensityRecipePanel/
// SafetyRecipePanelの3ファイルへ実質同一の内容がコピペされていたのをここへ集約）。
export function ScalarInput<TRecipe, TKey extends NumericKeys<TRecipe>>({
  field,
  recipe,
  onChange,
  negativeColor,
  positiveColor,
}: {
  field: ScalarFieldDescriptor<TRecipe, TKey>;
  recipe: TRecipe;
  onChange: (recipe: TRecipe) => void;
  negativeColor: string;
  positiveColor: string;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  const value = recipe[field.key] as number;
  return (
    <>
      <div className={styles.field}>
        <FieldLabel label={field.label} open={infoOpen} onToggle={() => setInfoOpen((v) => !v)} />
        <AdjustmentStepper
          label={field.label}
          value={value}
          onChange={(next) => onChange({ ...recipe, [field.key]: next } as TRecipe)}
          negativeColor={negativeColor}
          positiveColor={positiveColor}
        />
      </div>
      {infoOpen && <p className={styles.infoTooltip}>{field.description}</p>}
    </>
  );
}

export interface ThresholdAdjustmentFieldDescriptor<
  TRecipe,
  TThresholdKey extends NumericKeys<TRecipe> = NumericKeys<TRecipe>,
  TAdjustmentKey extends NumericKeys<TRecipe> = NumericKeys<TRecipe>,
> {
  thresholdKey: TThresholdKey;
  adjustmentKey: TAdjustmentKey;
  label: string;
  description: string;
  thresholdSuffix: string;
}

// 閾値+補正値の対フィールド（改善計画: 車との近さ材料の共有元化のレビュー指摘。
// MotorVehicleDensityRecipePanel/TrafficStressRecipePanelの2ファイルへ実質同一の内容が
// コピペされていたのをここへ集約）。補正値のステッパーと変動条件（閾値）を同じ行に
// 横並びで置く。
export function ThresholdAdjustmentRow<
  TRecipe,
  TThresholdKey extends NumericKeys<TRecipe>,
  TAdjustmentKey extends NumericKeys<TRecipe>,
>({
  field,
  recipe,
  onChange,
  negativeColor,
  positiveColor,
}: {
  field: ThresholdAdjustmentFieldDescriptor<TRecipe, TThresholdKey, TAdjustmentKey>;
  recipe: TRecipe;
  onChange: (recipe: TRecipe) => void;
  negativeColor: string;
  positiveColor: string;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  const thresholdValue = recipe[field.thresholdKey] as number;
  const adjustmentValue = recipe[field.adjustmentKey] as number;
  return (
    <>
      <div className={styles.field}>
        <FieldLabel label={field.label} open={infoOpen} onToggle={() => setInfoOpen((v) => !v)} />
        <span className={styles.pairControls}>
          <AdjustmentStepper
            label={field.label}
            value={adjustmentValue}
            onChange={(next) => onChange({ ...recipe, [field.adjustmentKey]: next } as TRecipe)}
            negativeColor={negativeColor}
            positiveColor={positiveColor}
          />
          <span className={styles.thresholdInline}>
            <span className={styles.thresholdCaption}>条件</span>
            <input
              type="number"
              step="1"
              aria-label={`${field.label}の条件`}
              value={thresholdValue}
              onChange={(e) => {
                const next = Number(e.target.value);
                if (Number.isNaN(next)) return;
                onChange({ ...recipe, [field.thresholdKey]: next } as TRecipe);
              }}
              className={styles.thresholdInput}
            />
            <span className={styles.thresholdSuffix}>{field.thresholdSuffix}</span>
          </span>
        </span>
      </div>
      {infoOpen && <p className={styles.infoTooltip}>{field.description}</p>}
    </>
  );
}

export function FieldLabel({
  label,
  open,
  onToggle,
  className,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  className?: string;
}) {
  return (
    <span className={className ? `${styles.fieldLabel} ${className}` : styles.fieldLabel}>
      {label}
      <button
        type="button"
        className={styles.infoButton}
        aria-expanded={open}
        aria-label={`${label}の説明を${open ? "隠す" : "表示"}`}
        onClick={onToggle}
      >
        <InfoIcon />
      </button>
    </span>
  );
}
