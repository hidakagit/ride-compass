"use client";

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
}

// 軸のラベル・入力欄リストは評価軸カタログ（lib/evaluationAxes.ts）から生成する
// （改善計画T25。軸を増やすたびにここへ手作業で追記するとRouteListのhint文言と
// ズレていく「手動同期ペア」だったため、カタログを単一ソースにした）。
// ラベルは候補一覧（RouteList）のおすすめ度説明文と同じ語を使う「画面に出る数値と、
// それを動かす重みは同じ語で呼ぶ」統一ルール（T30）を踏襲する。
const SCORING_FIELDS: WeightField<ScoringWeights>[] = SCORING_AXES.map((axis) => ({
  key: axis.weightKey,
  label: axis.label,
}));

const PREFERENCE_FIELDS: WeightField<RoutePreferenceWeights>[] = PREFERENCE_AXES.map((axis) => ({
  key: axis.weightKey,
  label: axis.label,
}));

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
          {/* 各グループは折りたたみ（details、改善計画: 研究の中身も折りたたみ式に統一。
              MapLayersPanel.tsxのレイヤーごとの折りたたみ（T38、デフォルト全閉）と同じ構成。
              開閉状態はこのトグル自体のON/OFFとは独立させている（MapLayersPanelの各レイヤーが
              表示ON/OFFと無関係に開閉できるのと同じ設計判断——上書きが有効な間、個々の
              グループを開くか閉じるかは純粋に「今どれを見たいか」というUI都合であり、
              有効/無効の状態と連動させる理由が無いため）。 */}
          <details className={styles.group}>
            <summary className={styles.groupHeader}>
              <span aria-hidden="true" className={styles.groupChevron} />
              おすすめ度の重み[候補一覧内の相対評価]
            </summary>
            <div className={styles.groupBody}>
              {SCORING_FIELDS.map((field) => (
                <WeightInput
                  key={String(field.key)}
                  field={field}
                  values={scoringWeights}
                  onChange={onScoringWeightsChange}
                />
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
                <WeightInput
                  key={String(field.key)}
                  field={field}
                  values={routePreference}
                  onChange={onRoutePreferenceChange}
                />
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
      )}
    </div>
  );
}
