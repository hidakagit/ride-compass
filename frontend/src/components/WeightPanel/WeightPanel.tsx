"use client";

import { useState } from "react";
import { FieldLabel, RecipePanelSection, withAutoEnable } from "@/components/Map/recipeControls";
import { PREFERENCE_AXES, SCORING_AXES } from "@/lib/evaluationAxes";
import type { RoutePreferenceWeights, ScoringWeights } from "@/types/route";
import styles from "./WeightPanel.module.css";

// backend/app/scoring.yaml / backend/app/route_preference.yaml の既定値のフロント側ミラー。
// 「既定値に戻す」ボタンの起点、および上書き有効化の直後に送る初期値としてのみ使う
// （実際にリクエストへ乗るのはonOverrideEnabledChangeがtrueの間だけで、falseの間は
// scoring_weights/route_preferenceを省略しバックエンドのYAML既定値がそのまま使われるため、
// この定数が古くなっても通常時の挙動には影響しない）。
export const DEFAULT_SCORING_WEIGHTS: ScoringWeights = {
  distance_weight: 0.3,
  elevation_weight: 0.15,
  wind_weight: 0.3,
  road_weight: 0.25,
};

export const DEFAULT_ROUTE_PREFERENCE: RoutePreferenceWeights = {
  elevation_weight: 0.15,
  road_weight: 0.19,
  wind_weight: 0.26,
  stop_weight: 0.15,
  traffic_weight: 0.1,
  infra_weight: 0.1,
  intersection_weight: 0.05,
  accident_weight: 0.08,
  safety_weight: 0.1,
};

interface WeightPanelProps {
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  scoringWeights: ScoringWeights;
  onScoringWeightsChange: (weights: ScoringWeights) => void;
  routePreference: RoutePreferenceWeights;
  onRoutePreferenceChange: (preference: RoutePreferenceWeights) => void;
}

interface WeightField<T> {
  key: keyof T;
  label: string;
  description: string;
}

// 軸のラベル・入力欄リストは評価軸カタログ（lib/evaluationAxes.ts）から生成する
// （改善計画T25。軸を増やすたびにここへ手作業で追記するとRouteListのhint文言と
// ズレていく「手動同期ペア」だったため、カタログを単一ソースにした）。
// ラベルは候補一覧（RouteList）のおすすめ度説明文と同じ語を使う「画面に出る数値と、
// それを動かす重みは同じ語で呼ぶ」統一ルール（T30）を踏襲する。
const SCORING_FIELDS: WeightField<ScoringWeights>[] = SCORING_AXES.map((axis) => ({
  key: axis.weightKey,
  label: axis.label,
  description: axis.description,
}));

const PREFERENCE_FIELDS: WeightField<RoutePreferenceWeights>[] = PREFERENCE_AXES.map((axis) => ({
  key: axis.weightKey,
  label: axis.label,
  description: axis.description,
}));

// ラベル横の情報アイコン（FieldLabel、Map/recipeControls.tsx）でdescriptionを開閉表示する。
// evaluationAxesのdescriptionフィールドはこれまでコード上に存在するだけでUIに出ていなかった
// （「交通ストレス」等のラベルだけでは実際の判定材料が伝わらないという指摘への対応）。
// レシピパネル（SafetyRecipePanel等）と同じ「タップで開くinfoTooltip」パターンを再利用する。
function WeightInput<T extends Record<string, number>>({
  field,
  values,
  onChange,
}: {
  field: WeightField<T>;
  values: T;
  onChange: (next: T) => void;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  return (
    <>
      <div className={styles.field}>
        <FieldLabel label={field.label} open={infoOpen} onToggle={() => setInfoOpen((v) => !v)} />
        <input
          type="number"
          min="0"
          step="0.05"
          aria-label={field.label}
          value={values[field.key]}
          onChange={(e) => {
            const next = Number(e.target.value);
            if (Number.isNaN(next) || next < 0) return;
            onChange({ ...values, [field.key]: next });
          }}
          className={styles.input}
        />
      </div>
      {infoOpen && <p className={styles.infoTooltip}>{field.description}</p>}
    </>
  );
}

// 評価重みのリクエスト上書き（研究インターフェース改善 §10-1/4）のUI。デバッグモード配下に
// 置き、一般ユーザーの操作導線には出さない（§14の分離方針）。scoring 4値（total_score算出、
// 候補集合内の相対評価）とpreference 3値（Edge Cost・区間difficulty算出、絶対評価）は
// 対象・意味が異なる別設定のため見出しを分けて表示する。
//
// 最上位はRecipePanelSection（改善計画: 研究タブのレイアウト改善）。以前は「評価重みを
// 上書きして生成する」チェックボックス1つが開閉と有効/無効を兼ねていたが、MapLayersPanelの
// レイヤー折りたたみと同じ「開閉（details）とON/OFF（チップ）を分ける」構成へ揃えた。
// 内側の各グループの折りたたみ（details、デフォルト全閉）はこのRecipePanelSectionのON/OFFとも
// 独立させている（MapLayersPanelの各レイヤーが表示ON/OFFと無関係に開閉できるのと同じ設計判断
// ——有効な間、個々のグループを開くか閉じるかは純粋に「今どれを見たいか」というUI都合であり、
// 有効/無効の状態と連動させる理由が無いため）。上書き無効中も入力欄は既定値で操作でき、
// 値を変更すると上書きが自動でONになる（withAutoEnable、MapLayersPanelの
// 「絞り込みを操作すると自動でON」と同じパターン）。
export default function WeightPanel({
  overrideEnabled,
  onOverrideEnabledChange,
  scoringWeights,
  onScoringWeightsChange,
  routePreference,
  onRoutePreferenceChange,
}: WeightPanelProps) {
  const handleScoringChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onScoringWeightsChange);
  const handlePreferenceChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onRoutePreferenceChange);

  return (
    <RecipePanelSection
      title="評価重み[次回のルート生成に反映]"
      overrideAriaLabel="評価重みを上書き"
      overrideEnabled={overrideEnabled}
      onOverrideEnabledChange={onOverrideEnabledChange}
    >
      <div className={styles.groups}>
        <details className={styles.group}>
          <summary className={styles.groupHeader}>
            <span aria-hidden="true" className={styles.groupChevron} />
            おすすめ度の重み[候補一覧内の相対評価]
          </summary>
          <div className={styles.groupBody}>
            {SCORING_FIELDS.map((field) => (
              <WeightInput key={String(field.key)} field={field} values={scoringWeights} onChange={handleScoringChange} />
            ))}
          </div>
        </details>

        <details className={styles.group}>
          <summary className={styles.groupHeader}>
            <span aria-hidden="true" className={styles.groupChevron} />
            区間難易度の重み[絶対評価]
          </summary>
          <div className={styles.groupBody}>
            {PREFERENCE_FIELDS.map((field) => (
              <WeightInput key={String(field.key)} field={field} values={routePreference} onChange={handlePreferenceChange} />
            ))}
            {/* エンジン名（road_graph）を見出しへ出さず、制約は脚注に落とす（T30） */}
            <p className={styles.note}>※ルート形状への反映は一部エンジン[road_graph]のみ</p>
          </div>
        </details>

        <button
          type="button"
          className={styles.resetButton}
          onClick={() => {
            onScoringWeightsChange(DEFAULT_SCORING_WEIGHTS);
            onRoutePreferenceChange(DEFAULT_ROUTE_PREFERENCE);
          }}
        >
          既定値に戻す
        </button>
      </div>
    </RecipePanelSection>
  );
}
