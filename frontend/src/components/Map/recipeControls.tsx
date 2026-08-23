"use client";

import { useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import * as RadioGroup from "@radix-ui/react-radio-group";
import { InfoIcon } from "./icons";
import LayerChip from "./LayerChip";
import styles from "./recipeControls.module.css";

// レシピ入力フォーム（研究タブの各レシピパネル）共通のUI部品。T113でCarStressRecipePanel
// 専用に実装したものを、2つ目のレシピ（当時の安全度レシピ。安全度軸自体はT148で削除済み）
// 登場を機に汎用化した（改善計画: 安全度レシピ。「今後ほかの2次データのレシピが増えると
// 思うので、くくり出してほしい」というユーザー要望への対応）。段階数・色パレットは
// 呼び出し側がpropsで渡すため、レシピごとの段階数・配色差はこのファイルの変更なしで
// 吸収できる。

// 研究タブ各パネルの最上位の折りたたみ（改善計画: 研究タブのレイアウト改善。ユーザー
// フィードバック「地図の見え方のようなデザインに合わせて、折りたたみを工夫したり表示非表示を
// スマートにして」への対応）。MapLayersPanel.module.cssの.layerSection/.layerHeader/
// .layerTitle/.chevron/.layerBodyをcomposesでそのまま再利用し、地図側のレイヤー折りたたみと
// 同一の見た目・挙動にする。ON/OFFチップも同じLayerChip部品を流用（表示チップの「表示」→
// このチップは「上書き」）。
//
// 以前は「上書きする」チェックボックス1つが開閉と有効/無効を兼ねていたため、値を確認する
// だけでも上書きを有効化する（＝地図やルート生成に即座に影響する）しかなかった。
// MapLayersPanelの「OFF中でも絞り込み操作でき、操作すると自動でONになる」設計
// （handleRoadLegendToggle等）と同じ考え方で、開閉（details）と有効/無効（チップ）を分離する。
// 上書き無効中も中身は既定値で表示・編集でき、値を変更すると上書きが自動でONになる
// （呼び出し側はonRecipeChange等をwithAutoEnableで包んで渡す）。
export function RecipePanelSection({
  title,
  overrideAriaLabel,
  overrideEnabled,
  onOverrideEnabledChange,
  children,
}: {
  title: string;
  /** LayerChipのariaLabel（例:「車の圧迫感のレシピを上書き」）。titleは`[...]`の
   * 補足文言を含むことがあるため、チップのアクセシブル名は別途渡す。 */
  overrideAriaLabel: string;
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <details className={styles.panelSection}>
      <summary className={styles.panelHeader}>
        <h3 className={styles.panelTitle}>
          <span aria-hidden="true" className={styles.panelChevron} />
          {title}
        </h3>
        {/* MapLayersPanel.tsxのhandleRoadLegendToggle等と同じ理由でpreventDefault/
            stopPropagationする（summary内クリックのdetails開閉デフォルト動作との衝突回避）。 */}
        <LayerChip
          label="上書き"
          ariaLabel={overrideAriaLabel}
          on={overrideEnabled}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onOverrideEnabledChange(!overrideEnabled);
          }}
        />
      </summary>
      <div className={styles.panelBody}>
        {!overrideEnabled && (
          <p className={styles.panelOffHint}>上書きはOFFです[値を変更すると自動でONになります]</p>
        )}
        {children}
      </div>
    </details>
  );
}

// overrideEnabledがfalseの間に値が変更されたら、変更自体は伝えつつ上書きも自動で有効化する
// ラッパー（MapLayersPanel.tsxのhandleRoadLegendToggle等と同じ「操作したら自動でON」パターン）。
export function withAutoEnable<T>(
  overrideEnabled: boolean,
  onOverrideEnabledChange: (enabled: boolean) => void,
  setter: (next: T) => void,
): (next: T) => void {
  return (next) => {
    if (!overrideEnabled) onOverrideEnabledChange(true);
    setter(next);
  };
}

// 基準値のレベルピッカー。levelsぶんのボタンを並べ、選択値以下の段階をcolorsの色で塗って
// 進捗バー風に見せる。単一選択（常にどれか1つだけ選ばれる）のためRadix RadioGroupで実装する
// （T253併用導入。以前は`role="group"`+個別`aria-pressed`ボタンの自前実装で矢印キーでの
// 移動ができなかったが、RadioGroupは`role="radio"`＋roving tabindexでの矢印キー移動を
// 標準で提供する）。見た目（塗りつぶし段階の表現）は従来どおり独自の`data-filled`属性＋
// `--level-color`で行うため、CSS（.levelSegment）は変更不要。
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
    <RadioGroup.Root
      className={styles.levelPicker}
      aria-label={groupLabel}
      value={String(value)}
      onValueChange={(next) => onChange(Number(next))}
    >
      {levels.map((level) => (
        <RadioGroup.Item
          key={level}
          value={String(level)}
          aria-label={String(level)}
          data-filled={level <= value}
          className={styles.levelSegment}
          style={{ "--level-color": colors[level] } as React.CSSProperties}
        >
          {level}
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
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
// （MapOverlayControlsのaria-expanded凡例トグルと同じ規約）。説明本体はRadix Popoverで
// フローティング表示する（T253併用導入。以前は呼び出し側がopen/onToggleを受け取り、
// DOM上input/tr等の後ろへ`<p>`/`<tr>`を個別に配置していたが、呼び出し側ごとに配置形が
// バラバラだった（div直後の<p> vs テーブル行内の<tr colSpan>）。Popoverはトリガー位置基準の
// フローティング表示のためDOM上の配置形に依存せず、開閉状態もこのコンポーネント自身が
// 持つため呼び出し側は`description`を渡すだけでよくなった）。`className`は任意の追加クラス
// （改善計画T118のモバイル幅溢れ修正: highway別基準値テーブル内では
// nowrap/flex-shrink:0を打ち消して折り返しを許可する必要があり、呼び出し側の
// module.cssでその上書きクラスを定義してここへ渡す）。

// 「車の圧迫感」パネルの先頭に置く読み取り専用の参照セクション（改善計画: 車との近さ
// 材料の共有元化）。車ストレスが参照する「道路適正」「自動車密度」の現在値（研究モードで
// 上書き中ならその値、既定ならDEFAULT_*）を一覧表示し、「この軸がどの土台の上に成り
// 立っているか」を視覚的に示す。編集はできない（編集は道路適正/自動車密度パネル側で行う）。
// highway別基準値テーブル自体はここでは繰り返さず、専用パネルへの導線だけにする
// （12行の読み取り専用テーブルを複製しないため）。当初は安全度パネルとも共有していたが、
// 安全度軸はT148で削除された。
//
// 改善計画: 研究タブのレイアウト改善（ユーザーフィードバック「土台部分が冗長」）。
// 以前は前置き文2つ（「〜の上に成り立っています。編集は〜」「道路種別ごとの基準値は〜」）＋
// 「／」区切りの長文箇条書き4行という構成で冗長すぎた。前置きは見出しの
// `[編集は各パネルで]`へ集約し、値は現在値そのものが伝わればよいので短いタグの一覧
// （.referenceTags）に変える。
function formatSignedTerm(value: number): string {
  return value >= 0 ? `+${value}` : `${value}`;
}

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
        土台: 道路適正＋自動車密度[編集は各パネルで]
      </summary>
      <div className={styles.referenceBody}>
        <ul className={styles.referenceTags}>
          <li className={styles.referenceTag}>
            専用レーン: {formatSignedTerm(roadSuitabilityRecipe.cycleway_track_adjustment)}
          </li>
          <li className={styles.referenceTag}>
            自転車レーン: {formatSignedTerm(roadSuitabilityRecipe.cycleway_lane_adjustment)}
          </li>
          <li className={styles.referenceTag}>
            共有レーン: {formatSignedTerm(roadSuitabilityRecipe.cycleway_shared_adjustment)}
          </li>
          <li className={styles.referenceTag}>
            {motorVehicleDensityRecipe.maxspeed_low_threshold}km/h以下:{" "}
            {formatSignedTerm(motorVehicleDensityRecipe.maxspeed_low_adjustment)}
          </li>
          <li className={styles.referenceTag}>
            {motorVehicleDensityRecipe.maxspeed_high_threshold}km/h以上:{" "}
            {formatSignedTerm(motorVehicleDensityRecipe.maxspeed_high_adjustment)}
          </li>
          <li className={styles.referenceTag}>
            車線数{motorVehicleDensityRecipe.lanes_high_threshold}以上:{" "}
            {formatSignedTerm(motorVehicleDensityRecipe.lanes_high_adjustment)}
          </li>
          <li className={styles.referenceTag}>
            指定路線: {formatSignedTerm(motorVehicleDensityRecipe.designation_adjustment)}
          </li>
        </ul>
      </div>
    </details>
  );
}

// CAR_STRESS_COLORSの最小/最大段階の色を補正値ステッパーの負値/正値表示に使う
// （改善計画: 車との近さ材料の共有元化のレビュー指摘。4パネル中3パネルが
// `CAR_STRESS_COLORS[1]`/`[5]`を、RoadSuitabilityRecipePanelだけが値域の違い
// （道路適正の基準値は1〜4で5段階目を使わない）から`[1]`/`[4]`を、それぞれのファイルへ
// 個別にハードコードしていた。呼び出し側ごとに使う範囲が異なるため単一の共有定数には
// できないが、「CAR_STRESS_COLORSから最小・最大段階の色を引く」という手順自体は
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
// CarStressRecipePanelの複数ファイルへ実質同一の内容がコピペされていたのをここへ集約）。
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
  const value = recipe[field.key] as number;
  return (
    <div className={styles.field}>
      <FieldLabel label={field.label} description={field.description} />
      <AdjustmentStepper
        label={field.label}
        value={value}
        onChange={(next) => onChange({ ...recipe, [field.key]: next } as TRecipe)}
        negativeColor={negativeColor}
        positiveColor={positiveColor}
      />
    </div>
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
// MotorVehicleDensityRecipePanel/CarStressRecipePanelの2ファイルへ実質同一の内容が
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
  const thresholdValue = recipe[field.thresholdKey] as number;
  const adjustmentValue = recipe[field.adjustmentKey] as number;
  return (
    <div className={styles.field}>
      <FieldLabel label={field.label} description={field.description} />
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
  );
}

export function FieldLabel({
  label,
  description,
  className,
}: {
  label: string;
  description: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <span className={className ? `${styles.fieldLabel} ${className}` : styles.fieldLabel}>
        {label}
        <Popover.Trigger asChild>
          <button
            type="button"
            className={styles.infoButton}
            aria-label={`${label}の説明を${open ? "隠す" : "表示"}`}
          >
            <InfoIcon />
          </button>
        </Popover.Trigger>
      </span>
      {/* Portalでdocument.body直下へ描画する（呼び出し側がoverflow-y:autoの
          サイドバー・BottomSheet内にあっても、その祖先要素のoverflowでクリップされない
          ようにするため）。 */}
      <Popover.Portal>
        <Popover.Content className={styles.infoTooltip} side="bottom" align="start" sideOffset={6}>
          {description}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
