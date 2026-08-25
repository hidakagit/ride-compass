"use client";

import { FieldLabel, RecipePanelSection, withAutoEnable } from "@/components/Map/recipeControls";
import { SCORING_AXES } from "@/lib/evaluationAxes";
import type { RoutePreferenceWeights, ScoringWeights } from "@/types/route";
import axisCatalog from "@/types/generated/axis-catalog.json";
import styles from "./WeightPanel.module.css";

// backend/app/scoring.yaml の既定値のフロント側ミラー。
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

// 区間難易度の重み（route_preference）の既定値。WeightPanel自身はこの値を編集する
// UIをもう持たない（改善計画T304、下記コメント参照）が、page.tsx/admin/page.tsxが
// route_preference stateの初期値として引き続き参照するため定数export自体は残す。
// axis-catalog.jsonのpreference_defaults（backend domain/axis_definitions.py:
// AXIS_DEFINITIONSのdefault_weightを生成物として書き出したもの、改善計画T221 Stage B）
// から読むことで、軸の増減・既定値変更に自動追従する。
export const DEFAULT_ROUTE_PREFERENCE: RoutePreferenceWeights = axisCatalog.preference_defaults;

interface WeightPanelProps {
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  scoringWeights: ScoringWeights;
  onScoringWeightsChange: (weights: ScoringWeights) => void;
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

// ラベル横の情報アイコン（FieldLabel、Map/recipeControls.tsx）でdescriptionを開閉表示する。
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
    <div className={styles.field}>
      <FieldLabel label={field.label} description={field.description} />
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
  );
}

// おすすめ度の重み（候補ルート同士を比べる3次評価、route_scorer.py: RouteScorer.score）の
// リクエスト上書きUI（研究インターフェース改善 §10-1/4）。デバッグモード配下に置き、一般
// ユーザーの操作導線には出さない（§14の分離方針）。
//
// 改善計画T304: 以前は区間難易度の重み（route_preference、2次要素・軸ごとの重み）も
// このパネルの別グループとして編集できたが、その状態は一般向けルート設定画面
// （RouteSettingsPanel、`/`）と同一のlocalStorageキーを共有しており、RouteSettingsPanelの
// チェックボックス+スライダー（観測/推定/動的で分類・プリセット付き）という同じ値への
// より分かりやすい編集UIが既に存在していた。さらに軸の「既定重み」自体は軸スタジオの
// AxisComposerでも編集できるため、ここに3つ目の生の数値入力欄を残す意味が薄いという
// ユーザー指摘を受けて撤去した（区間難易度の重みを研究用途で一時的に変えたい場合は
// RouteSettingsPanelを使う）。「既定値に戻す」もscoringWeightsのみを対象にする。
export default function WeightPanel({
  overrideEnabled,
  onOverrideEnabledChange,
  scoringWeights,
  onScoringWeightsChange,
}: WeightPanelProps) {
  const handleScoringChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onScoringWeightsChange);

  return (
    <RecipePanelSection
      title="おすすめ度の重み[候補一覧内の相対評価、次回のルート生成に反映]"
      overrideAriaLabel="おすすめ度の重みを上書き"
      overrideEnabled={overrideEnabled}
      onOverrideEnabledChange={onOverrideEnabledChange}
    >
      <div className={styles.groups}>
        {SCORING_FIELDS.map((field) => (
          <WeightInput key={String(field.key)} field={field} values={scoringWeights} onChange={handleScoringChange} />
        ))}
        <button type="button" className={styles.resetButton} onClick={() => onScoringWeightsChange(DEFAULT_SCORING_WEIGHTS)}>
          既定値に戻す
        </button>
      </div>
    </RecipePanelSection>
  );
}
