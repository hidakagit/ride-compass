"use client";

import type { ReactNode } from "react";
import { FieldLabel, RecipePanelSection, withAutoEnable } from "@/components/Map/recipeControls";
import { PREFERENCE_AXES, SCORING_AXES } from "@/lib/evaluationAxes";
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

// 区間難易度の重みの既定値は手書きミラーをやめ、axis-catalog.jsonのpreference_defaults
// （backend domain/axis_definitions.py: AXIS_DEFINITIONSのdefault_weightを生成物として
// 書き出したもの、改善計画T221 Stage B）から読む。軸の増減・既定値変更に自動追従する。
export const DEFAULT_ROUTE_PREFERENCE: RoutePreferenceWeights = axisCatalog.preference_defaults;

interface WeightPanelProps {
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  scoringWeights: ScoringWeights;
  onScoringWeightsChange: (weights: ScoringWeights) => void;
  routePreference: RoutePreferenceWeights;
  onRoutePreferenceChange: (preference: RoutePreferenceWeights) => void;
  /** 区間難易度の重み（2次要素）を軸ごとに整理する研究タブの改修（改善計画T145関連）用の
   * 差し込み枠。軸によっては重みだけでなく一次情報→二次情報の変換式そのもの
   * （車の圧迫感のCarStressRecipePanel等）を持ち、以前は「レシピ」という別カテゴリへ
   * 分離していたが、同じ軸の重みのすぐ下に置く方が「この軸を調整する」ときに探す場所が
   * 1箇所で済む。WeightPanel自身は車ストレス等の個別知識を持たず、page.tsx側が
   * weightKeyごとに何を差し込むか（無ければnull）を決める汎用の枠として提供する。 */
  renderPreferenceFieldExtra?: (axisId: string) => ReactNode;
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

// キーはaxis_id（改善計画T221 Stage B、RoutePreferenceWeightsはaxis_idキーの辞書）。
const PREFERENCE_FIELDS: WeightField<RoutePreferenceWeights>[] = PREFERENCE_AXES.map((axis) => ({
  key: axis.axisId,
  label: axis.label,
  description: axis.description,
}));

// ラベル横の情報アイコン（FieldLabel、Map/recipeControls.tsx）でdescriptionを開閉表示する。
// evaluationAxesのdescriptionフィールドはこれまでコード上に存在するだけでUIに出ていなかった
// （「車ストレス」等のラベルだけでは実際の判定材料が伝わらないという指摘への対応）。
// レシピパネル（CarStressRecipePanel等）と同じ「タップで開くinfoTooltip」パターンを再利用する。
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
  renderPreferenceFieldExtra,
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
        {/* 次数タグ（改善計画: 研究パネルも次数でグループ化してほしいという実機
            フィードバックへの対応。地図の見え方パネルの「観測データ/推定指標（合成）」
            グループ見出しと同じ「次数で束ねる」考え方を研究タブにも適用するが、研究タブは
            開発者・研究者向けの画面のため地図側のような言い換え（観測/推定）はせず、
            docs/improvement-plan.md「評価システムの層構造再設計」の呼称（0次/1次/2次/3次）を
            そのまま使う。おすすめ度の重みは候補ルート間の重み付き合成
            （route_scorer.py: RouteScorer.score、3次相当）、区間難易度の重みは
            route_preference.yamlの各軸[2次要素]と1:1対応する重み（下記コメント参照）で
            2次相当。表示順「3次→2次」は元々この並びだったため変更していない。 */}
        <details className={styles.group}>
          <summary className={styles.groupHeader}>
            <span aria-hidden="true" className={styles.groupChevron} />
            <span className={styles.tierBadge}>3次</span>
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
            <span className={styles.tierBadge}>2次</span>
            区間難易度の重み[絶対評価]
          </summary>
          <div className={styles.groupBody}>
            {PREFERENCE_FIELDS.map((field) => (
              <div key={String(field.key)} className={styles.fieldGroup}>
                <WeightInput field={field} values={routePreference} onChange={handlePreferenceChange} />
                {/* keyof（index signature型）はstring | numberに広がるためStringで確定させる */}
                {renderPreferenceFieldExtra?.(String(field.key))}
              </div>
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
