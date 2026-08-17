"use client";

import { useState } from "react";
import { InfoIcon } from "@/components/Map/icons";
import { TRAFFIC_STRESS_COLORS } from "@/components/Map/staticAttributeLayers";
import { DEFAULT_TRAFFIC_STRESS_RECIPE, type TrafficStressRecipe } from "@/components/Map/trafficStressExpression";
import styles from "./TrafficStressRecipePanel.module.css";

interface TrafficStressRecipePanelProps {
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  recipe: TrafficStressRecipe;
  onRecipeChange: (recipe: TrafficStressRecipe) => void;
}

type ScalarKey = Exclude<keyof TrafficStressRecipe, "base_by_highway">;

interface ScalarField {
  key: ScalarKey;
  /** 表示ラベル（改善計画: 研究タブの用語日本語化。技術的な条件そのものはdescription
   * （情報アイコンのツールチップ）側へ回し、ここは日本語として読める短い語句にする）。 */
  label: string;
  /** ラベル横の情報アイコンのツールチップに出す、判定条件の具体的な説明
   * （対応するOSMタグ・値を含む）。 */
  description: string;
}

/** 閾値+補正値が対になっているフィールド（低速/高速・多車線/少車線）用。改善計画:
 * レシピ入力フォームの改善で「変動条件（閾値）は補正値の横に個別設定できるように」という
 * 要望を受け、以前は4つの独立したScalarFieldだったmaxspeed/lanes系を対で1行にまとめた。 */
interface ThresholdAdjustmentField {
  thresholdKey: ScalarKey;
  adjustmentKey: ScalarKey;
  label: string;
  description: string;
  /** 閾値入力欄の直後に出す単位付き条件文言（例: "km/h以下"）。 */
  thresholdSuffix: string;
}

// 基準値ピッカーの段階（改善計画: レシピ入力フォームの改善、「1-4をプログレスバーで選択、
// 4は将来的に5や6に変えられるように」という要望への対応）。地図の色分け
// （staticAttributeLayers.ts: TRAFFIC_STRESS_COLORS）と単一ソースにし、段階数を増やす
// 場合もそちらへキーを追加するだけで両方に反映される（このファイルの変更は不要）。
const TRAFFIC_STRESS_LEVELS = Object.keys(TRAFFIC_STRESS_COLORS)
  .map(Number)
  .sort((a, b) => a - b);

// WeightPanel.tsxのWeightField/WeightInputと同じ発想の一覧駆動だが、
// TrafficStressRecipeOverrideはevaluationAxes.tsのWeights系ユニオン型に含まれないため
// （軸間の重みではなく軸の中身のレシピのため）、フィールド一覧はこのファイル内に持つ。
// backend/app/domain/traffic.py: traffic_stress_breakdownの適用順序に合わせて4グループに束ねる。
const CYCLEWAY_FIELDS: ScalarField[] = [
  {
    key: "cycleway_track_adjustment",
    label: "専用レーンの補正",
    description: "cycleway=track（車道と分離された自転車専用レーン）に該当する道路への補正値",
  },
  {
    key: "cycleway_lane_adjustment",
    label: "自転車レーンの補正",
    description: "cycleway=lane（車道内に区画された自転車レーン）に該当する道路への補正値",
  },
  {
    key: "cycleway_shared_adjustment",
    label: "共有レーンの補正",
    description: "cycleway=shared_lane / share_busway（自動車・バスと車線を共有する通行帯）に該当する道路への補正値",
  },
];

const MAXSPEED_PAIRS: ThresholdAdjustmentField[] = [
  {
    thresholdKey: "maxspeed_low_threshold",
    adjustmentKey: "maxspeed_low_adjustment",
    label: "低速道路",
    thresholdSuffix: "km/h以下",
    description: "制限速度がこの値[km/h]以下の道路を「低速道路」とみなし、補正値を交通ストレスへ加える",
  },
  {
    thresholdKey: "maxspeed_high_threshold",
    adjustmentKey: "maxspeed_high_adjustment",
    label: "高速道路",
    thresholdSuffix: "km/h以上",
    description: "制限速度がこの値[km/h]以上の道路を「高速道路」とみなし、補正値を交通ストレスへ加える",
  },
];

const LANES_PAIRS: ThresholdAdjustmentField[] = [
  {
    thresholdKey: "lanes_high_threshold",
    adjustmentKey: "lanes_high_adjustment",
    label: "多車線道路",
    thresholdSuffix: "車線以上",
    description: "車線数がこの値以上の道路を「多車線道路」とみなし、補正値を交通ストレスへ加える",
  },
  {
    thresholdKey: "lanes_low_threshold",
    adjustmentKey: "lanes_low_adjustment",
    label: "少車線道路",
    thresholdSuffix: "車線以下",
    description: "車線数がこの値以下の道路を「少車線道路」とみなし、補正値を交通ストレスへ加える",
  },
];

const DESIGNATION_FIELDS: ScalarField[] = [
  {
    key: "designation_adjustment",
    label: "指定路線への補正",
    description: "緊急輸送道路（N10）・重要物流道路（N12）のいずれかに該当する道路に加える補正値",
  },
];

interface HighwayLabel {
  label: string;
  description: string;
}

// highway別基準値の日本語ラベル+説明（改善計画: 研究タブの用語日本語化。以前はOSMの
// highway=タグ値をそのまま出していたが「要素名は日本語の論理をラベルに、具体的な属性
// 説明は情報アイコンで」という方針転換を受け変更）。キー集合自体はHIGHWAY_ORDER
// （DEFAULT_TRAFFIC_STRESS_RECIPE.base_by_highwayの定義順、domain/traffic.py:
// TRAFFIC_STRESS_BASE_BY_HIGHWAYと単一ソース）に従う。ラベルはroadFilterAxes.ts
// 「道路の種類」軸の分類語（幹線道路/主要道/生活道路等）と整合させつつ、この表では
// highway値ごとに基準値を個別編集するためより細かく分けている。説明（情報アイコンの
// ツールチップ）には元のOSMタグ値を明記し、タグ語彙を知っている利用者はそちらも
// 参照できるようにする。未知のhighway値（将来backendの既定レシピにキーが追加された場合）は
// フォールバックとしてタグ値そのものをラベルに使う（HIGHWAY_LABELS未収載でも表示は欠けない）。
const HIGHWAY_LABELS: Record<string, HighwayLabel> = {
  cycleway: { label: "自転車専用道", description: "highway=cycleway。自転車のための専用道路" },
  living_street: {
    label: "生活道路(歩車共存)",
    description: "highway=living_street。歩行者優先で自動車もゆっくり走る道路",
  },
  residential: { label: "住宅地の道路", description: "highway=residential。住宅地内の一般道路" },
  unclassified: {
    label: "その他の一般道",
    description: "highway=unclassified。上記のどれにも当てはまらない格付けの低い一般道路",
  },
  track: { label: "農道・林道", description: "highway=track。農地・山林内の道（未舗装が多い）" },
  tertiary: { label: "地区の主要道路", description: "highway=tertiary。市区町村道クラスの主要な道路" },
  tertiary_link: {
    label: "地区の主要道路(連絡路)",
    description: "highway=tertiary_link。上記の合流・分岐路（ランプ）",
  },
  secondary: { label: "都道府県道クラスの道路", description: "highway=secondary。主要地方道クラスの道路" },
  secondary_link: {
    label: "都道府県道クラスの道路(連絡路)",
    description: "highway=secondary_link。上記の合流・分岐路（ランプ）",
  },
  primary: { label: "国道クラスの幹線道路", description: "highway=primary。国道クラスの幹線道路" },
  primary_link: { label: "幹線道路(連絡路)", description: "highway=primary_link。上記の合流・分岐路（ランプ）" },
  trunk: { label: "高規格の幹線道路", description: "highway=trunk。自動車専用道路に準ずる高規格の幹線道路" },
  trunk_link: {
    label: "高規格の幹線道路(連絡路)",
    description: "highway=trunk_link。上記の合流・分岐路（ランプ）",
  },
};

const HIGHWAY_ORDER = Object.keys(DEFAULT_TRAFFIC_STRESS_RECIPE.base_by_highway);

// 基準値のレベルピッカー。TRAFFIC_STRESS_LEVELS（低→高）ぶんのボタンを並べ、選択値以下の
// 段階を地図と同じ色で塗って進捗バー風に見せる（改善計画: レシピ入力フォームの改善）。
function StressLevelPicker({
  value,
  onChange,
  groupLabel,
}: {
  value: number;
  onChange: (next: number) => void;
  groupLabel: string;
}) {
  return (
    <div className={styles.levelPicker} role="group" aria-label={groupLabel}>
      {TRAFFIC_STRESS_LEVELS.map((level) => (
        <button
          key={level}
          type="button"
          aria-pressed={value === level}
          aria-label={String(level)}
          data-filled={level <= value}
          className={styles.levelSegment}
          style={{ "--level-color": TRAFFIC_STRESS_COLORS[level] } as React.CSSProperties}
          onClick={() => onChange(level)}
        >
          {level}
        </button>
      ))}
    </div>
  );
}

// 補正値のステッパー。当初は0中心の水平バー＋数値入力だったが、バーが実際の値の範囲
// （既定-2〜+1）に対して細すぎて「バーが出ていない」ように見え、かつ数値入力単体（ネイティブの
// 上下スピナー矢印が小さくタップしづらい）が「入力しにくい」という実機フィードバックを受け、
// -/+ボタン付きのステッパーへ作り直した（改善計画: レシピ入力フォームの改善）。数値入力欄
// 自体は残しているため直接タイプでの入力も引き続きできる。入力欄の背景色を負値（ストレス
// 軽減）は最も低い段階の色、正値（ストレス増加）は最も高い段階の色に塗り、TRAFFIC_STRESS_
// COLORSと連動させることで「0中心に変動する」という感覚を色だけで確実に伝える
// （バーの塗り幅のような視認性の問題が起きない）。
const ADJUSTMENT_NEGATIVE_COLOR = TRAFFIC_STRESS_COLORS[TRAFFIC_STRESS_LEVELS[0]];
const ADJUSTMENT_POSITIVE_COLOR = TRAFFIC_STRESS_COLORS[TRAFFIC_STRESS_LEVELS[TRAFFIC_STRESS_LEVELS.length - 1]];

function AdjustmentStepper({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (next: number) => void;
}) {
  const color = value < 0 ? ADJUSTMENT_NEGATIVE_COLOR : value > 0 ? ADJUSTMENT_POSITIVE_COLOR : undefined;
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

// フィールドラベル+情報アイコン。当初はtitle属性（weatherHeaderと同じ、ホバー/長押しで
// 出る補足）で説明を出していたが、スマホでtitle属性はタップでは開かない（ホバー状態を
// 持たない）ため実機で「押しても説明が出ない」と判明。タップでも確実に開くクリック式の
// 開閉ボタンへ作り直した（MapOverlayControlsのaria-expanded凡例トグルと同じ規約）。
// 説明本体（infoTooltip）はopen/onToggleを渡す呼び出し側が、DOM上input/tr等の後ろへ
// 別要素として配置する（このコンポーネント自身はラベル行だけを返す）。
function FieldLabel({
  label,
  open,
  onToggle,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <span className={styles.fieldLabel}>
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

// 閾値を持たない補正値フィールド（自転車インフラ・指定路線）。ラベルとステッパーを
// 1行にまとめる（改善計画: レシピ入力フォームの改善）。複数の操作要素（-/+ボタンと
// 数値入力）を子に持つため、単一の対象を暗黙に持つ<label>ではなく<div>で包む
// （個別のアクセシブル名はAdjustmentStepper側のaria-labelで持たせている）。
function ScalarInput({
  field,
  recipe,
  onChange,
}: {
  field: ScalarField;
  recipe: TrafficStressRecipe;
  onChange: (recipe: TrafficStressRecipe) => void;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  const value = recipe[field.key];
  return (
    <>
      <div className={styles.field}>
        <FieldLabel label={field.label} open={infoOpen} onToggle={() => setInfoOpen((v) => !v)} />
        <AdjustmentStepper label={field.label} value={value} onChange={(next) => onChange({ ...recipe, [field.key]: next })} />
      </div>
      {infoOpen && <p className={styles.infoTooltip}>{field.description}</p>}
    </>
  );
}

// 閾値+補正値の対フィールド（低速/高速道路・多車線/少車線道路）。補正値のステッパーと
// 変動条件（閾値）の入力を同じ行に横並びで置く（改善計画: レシピ入力フォームの改善、
// 「変動条件はその横に個別設定できるように」「全体的にもう少しコンパクトな形に」という
// 要望への対応。以前は補正値行と閾値行が縦2段だった）。幅が足りない場合はflex-wrapで
// 折り返す。
function ThresholdAdjustmentRow({
  field,
  recipe,
  onChange,
}: {
  field: ThresholdAdjustmentField;
  recipe: TrafficStressRecipe;
  onChange: (recipe: TrafficStressRecipe) => void;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  const thresholdValue = recipe[field.thresholdKey];
  const adjustmentValue = recipe[field.adjustmentKey];
  return (
    <>
      <div className={styles.field}>
        <FieldLabel label={field.label} open={infoOpen} onToggle={() => setInfoOpen((v) => !v)} />
        <span className={styles.pairControls}>
          <AdjustmentStepper
            label={field.label}
            value={adjustmentValue}
            onChange={(next) => onChange({ ...recipe, [field.adjustmentKey]: next })}
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
                onChange({ ...recipe, [field.thresholdKey]: next });
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

// highway別基準値テーブルの1行。説明の開閉状態を行ごとに独立して持つため（.mapのコールバック内
// では使えないuseStateを、行ごとの専用コンポーネントへ切り出すことで満たす）ScalarInputと
// 同じ構造の別コンポーネントにしている。説明行は<tbody>直下に有効なtr要素として追加する
// 必要があるため（tdの中にブロック要素を積む案は避けた）、Fragmentで本行の直後に返す。
function HighwayRow({
  highway,
  value,
  onChange,
}: {
  highway: string;
  value: number | undefined;
  onChange: (highway: string, next: number) => void;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  // HIGHWAY_LABELS未収載（将来backendの既定レシピにキーが追加された場合）はタグ値
  // そのものをラベルにフォールバックし、情報アイコンは出さない（フォールバック時点で
  // ラベル自体がタグ値なので説明の付け足しは不要）。
  const highwayLabel = HIGHWAY_LABELS[highway];
  const resolvedValue = value ?? TRAFFIC_STRESS_LEVELS[0];
  return (
    <>
      <tr>
        <td className={styles.tableLabel}>
          {highwayLabel ? (
            <FieldLabel label={highwayLabel.label} open={infoOpen} onToggle={() => setInfoOpen((v) => !v)} />
          ) : (
            highway
          )}
        </td>
        <td>
          <StressLevelPicker
            value={resolvedValue}
            onChange={(next) => onChange(highway, next)}
            groupLabel={`${highwayLabel?.label ?? highway}の基準値`}
          />
        </td>
      </tr>
      {infoOpen && highwayLabel && (
        <tr>
          <td colSpan={2} className={styles.infoTooltipCell}>
            {highwayLabel.description}
          </td>
        </tr>
      )}
    </>
  );
}

// 研究モードでの交通ストレスレシピ上書きUI（改善計画: 交通ストレスレシピ調整UIパネル、
// T107の次ラウンド。入力欄の見た目は改善計画: レシピ入力フォームの改善で刷新——基準値は
// 低→高のレベルピッカー、補正値は-/+ボタン付きの色付きステッパー、閾値は補正値の横に
// 個別入力）。WeightPanel
// （評価重みの上書き）とは独立したトグルにしている（ユーザー承認済み: レシピは有効化すると
// 地図の色分けへ即座に反映されるが、重みは次回のルート生成まで反映されないという挙動差が
// あるため）。上書き中は地図の色分け・凡例による絞り込み（MapView.tsx）・区間クリックの
// 内訳ポップアップ・次回のルート生成（page.tsx経由で/api/routes/generateへ）すべてが
// このレシピに従う。
export default function TrafficStressRecipePanel({
  overrideEnabled,
  onOverrideEnabledChange,
  recipe,
  onRecipeChange,
}: TrafficStressRecipePanelProps) {
  return (
    <div className={styles.panel}>
      <label className={styles.toggleLabel}>
        <input
          type="checkbox"
          checked={overrideEnabled}
          onChange={(e) => onOverrideEnabledChange(e.target.checked)}
        />
        交通ストレスのレシピを上書きする[地図の色分けに即時反映]
      </label>

      {overrideEnabled && (
        <div className={styles.groups}>
          <fieldset className={styles.group}>
            <legend>道路種別ごとの基準値[低→高]</legend>
            <table className={styles.table}>
              <tbody>
                {HIGHWAY_ORDER.map((highway) => (
                  <HighwayRow
                    key={highway}
                    highway={highway}
                    value={recipe.base_by_highway[highway]}
                    onChange={(hw, next) =>
                      onRecipeChange({
                        ...recipe,
                        base_by_highway: { ...recipe.base_by_highway, [hw]: next },
                      })
                    }
                  />
                ))}
              </tbody>
            </table>
          </fieldset>

          <fieldset className={styles.group}>
            <legend>自転車インフラ補正[cycleway]</legend>
            {CYCLEWAY_FIELDS.map((field) => (
              <ScalarInput key={field.key} field={field} recipe={recipe} onChange={onRecipeChange} />
            ))}
          </fieldset>

          <fieldset className={styles.group}>
            <legend>制限速度補正[maxspeed]</legend>
            {MAXSPEED_PAIRS.map((field) => (
              <ThresholdAdjustmentRow key={field.thresholdKey} field={field} recipe={recipe} onChange={onRecipeChange} />
            ))}
          </fieldset>

          <fieldset className={styles.group}>
            <legend>車線数補正[lanes]</legend>
            {LANES_PAIRS.map((field) => (
              <ThresholdAdjustmentRow key={field.thresholdKey} field={field} recipe={recipe} onChange={onRecipeChange} />
            ))}
          </fieldset>

          <fieldset className={styles.group}>
            <legend>指定路線補正</legend>
            {DESIGNATION_FIELDS.map((field) => (
              <ScalarInput key={field.key} field={field} recipe={recipe} onChange={onRecipeChange} />
            ))}
          </fieldset>

          <button
            type="button"
            className={styles.resetButton}
            onClick={() => onRecipeChange(DEFAULT_TRAFFIC_STRESS_RECIPE)}
          >
            既定値に戻す
          </button>
        </div>
      )}
    </div>
  );
}
