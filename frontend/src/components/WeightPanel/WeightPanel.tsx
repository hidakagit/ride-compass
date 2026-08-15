"use client";

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
  elevation_weight: 0.25,
  road_weight: 0.3,
  wind_weight: 0.45,
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
}

// ラベルは候補一覧（RouteList）のおすすめ度説明文と同じ語を使う。「画面に出る数値と、
// それを動かす重みは同じ語で呼ぶ」統一ルール（T30。以前は距離/風/路面と略していて、
// どの表示値に効く重みなのか照合しづらかった）。
const SCORING_FIELDS: WeightField<ScoringWeights>[] = [
  { key: "distance_weight", label: "距離の合わせ込み" },
  { key: "elevation_weight", label: "獲得標高" },
  { key: "wind_weight", label: "向かい風" },
  { key: "road_weight", label: "舗装率" },
];

// こちらはルート色分けモード（勾配・舗装/未舗装・風の影響）が可視化する区間難易度の
// 構成要素に対応するため、その語に揃える（elevation_weightの実体は区間勾配由来の難易度）。
const PREFERENCE_FIELDS: WeightField<RoutePreferenceWeights>[] = [
  { key: "elevation_weight", label: "勾配" },
  { key: "road_weight", label: "舗装" },
  { key: "wind_weight", label: "風" },
];

function WeightInput<T extends Record<string, number>>({
  field,
  values,
  onChange,
}: {
  field: WeightField<T>;
  values: T;
  onChange: (next: T) => void;
}) {
  return (
    <label className={styles.field}>
      {field.label}
      <input
        type="number"
        min="0"
        step="0.05"
        value={values[field.key]}
        onChange={(e) => {
          const next = Number(e.target.value);
          if (Number.isNaN(next) || next < 0) return;
          onChange({ ...values, [field.key]: next });
        }}
        className={styles.input}
      />
    </label>
  );
}

// 評価重みのリクエスト上書き（研究インターフェース改善 §10-1/4）のUI。デバッグモード配下に
// 置き、一般ユーザーの操作導線には出さない（§14の分離方針）。scoring 4値（total_score算出、
// 候補集合内の相対評価）とpreference 3値（Edge Cost・区間difficulty算出、絶対評価）は
// 対象・意味が異なる別設定のため見出しを分けて表示する。
export default function WeightPanel({
  overrideEnabled,
  onOverrideEnabledChange,
  scoringWeights,
  onScoringWeightsChange,
  routePreference,
  onRoutePreferenceChange,
}: WeightPanelProps) {
  return (
    <div className={styles.panel}>
      <label className={styles.toggleLabel}>
        <input
          type="checkbox"
          checked={overrideEnabled}
          onChange={(e) => onOverrideEnabledChange(e.target.checked)}
        />
        評価重みを上書きして生成する
      </label>

      {overrideEnabled && (
        <div className={styles.groups}>
          <fieldset className={styles.group}>
            <legend>おすすめ度の重み（候補一覧内の相対評価）</legend>
            {SCORING_FIELDS.map((field) => (
              <WeightInput key={String(field.key)} field={field} values={scoringWeights} onChange={onScoringWeightsChange} />
            ))}
          </fieldset>

          <fieldset className={styles.group}>
            <legend>区間難易度の重み（絶対評価）</legend>
            {PREFERENCE_FIELDS.map((field) => (
              <WeightInput
                key={String(field.key)}
                field={field}
                values={routePreference}
                onChange={onRoutePreferenceChange}
              />
            ))}
            {/* エンジン名（road_graph）を見出しへ出さず、制約は脚注に落とす（T30） */}
            <p className={styles.note}>※ルート形状への反映は一部エンジン（road_graph）のみ</p>
          </fieldset>

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
      )}
    </div>
  );
}
