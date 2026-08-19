// 評価軸のカタログ（単一ソース）。mapLayers.tsと同じ「カタログ＋汎用列挙」の型
// （改善計画T25、docs/research-interface-review-2026-08-15.md §10-8）。
//
// 静的属性P1（停止密度）でRoutePreferenceに4つ目の軸が増えたのを機に、軸のid・重みキー・
// 表示名が RouteList のhint文言・WeightPanel の入力欄リストへ手作業で分散していた状態
// （軸を増やすたびにズレる「第3の手動同期ペア」、レビュー指摘）を解消する。
//
// ラベルは Record<キー, string> として書くことで、backend/app/scoring.yaml・
// route_preference.yaml のキー集合（OpenAPI型生成でフロントへ届く ScoringWeights /
// RoutePreferenceWeights）とフィールドが1対1で揃っていることをTypeScriptのコンパイルで
// 強制する（キーの過不足はコンパイルエラーになる。T4の型生成インフラをそのまま
// ドリフト検知に使うため、追加の生成物・テストは持たない）。
import type { RoutePreferenceWeights, ScoringWeights } from "@/types/route";

export interface ScoringAxisDef {
  /** RouteScoreComponent.axis（backend/app/services/route_scorer.py）と一致する値。
   * weightKeyから"_weight"接尾辞を除いたもの（バックエンド側の命名規約、
   * test_route_scorer.pyで固定）。 */
  id: string;
  weightKey: keyof ScoringWeights;
  /** RouteListのhint文・WeightPanelの入力欄ラベルに共通で使う表示名 */
  label: string;
  /** この軸が何を表すかの短い説明（将来のツールチップ等向け、現状は未使用） */
  description: string;
}

const SCORING_AXIS_META: Record<keyof ScoringWeights, Omit<ScoringAxisDef, "id" | "weightKey">> = {
  distance_weight: { label: "距離の合わせ込み", description: "指定距離との差の小ささ" },
  elevation_weight: { label: "獲得標高", description: "獲得標高が小さいほど高評価" },
  wind_weight: { label: "向かい風", description: "向かい風の影響が小さいほど高評価" },
  road_weight: { label: "舗装率", description: "舗装路の割合が高いほど高評価" },
};

export const SCORING_AXES: readonly ScoringAxisDef[] = (
  Object.keys(SCORING_AXIS_META) as (keyof ScoringWeights)[]
).map((weightKey) => ({
  id: weightKey.replace(/_weight$/, ""),
  weightKey,
  ...SCORING_AXIS_META[weightKey],
}));

export interface PreferenceAxisDef {
  weightKey: keyof RoutePreferenceWeights;
  /** 区間の色分け・WeightPanelの入力欄ラベルに共通で使う表示名 */
  label: string;
  description: string;
}

const PREFERENCE_AXIS_META: Record<keyof RoutePreferenceWeights, Omit<PreferenceAxisDef, "weightKey">> = {
  // ラベルはルート色分けモード（勾配・舗装/未舗装・風の影響）が可視化する区間難易度の
  // 構成要素に対応するため、その語に揃える（elevation_weightの実体は区間勾配由来の難易度）。
  elevation_weight: { label: "勾配", description: "登り坂の急さが小さいほど易しい" },
  road_weight: { label: "舗装", description: "舗装路であるほど易しい" },
  wind_weight: { label: "風", description: "向かい風が弱いほど易しい" },
  // ラベルは重み調整UIとして「何を減らしたいか」が伝わる具体名を使う（地図の凡例
  // （axis-catalog.jsonのdisplay.label、`stop_density`軸は「停止密度」）とは文脈が異なる
  // 意図的な言い換え。前者は密度という量、後者は要因の実体を説明する。統合レビュー
  // 2026-08-19 overall F-4・改善計画T160(1)で表記ゆれか同期漏れか不明と指摘されたため
  // 明記した）。
  stop_weight: {
    label: "信号・踏切等",
    description: "信号・横断歩道・一時停止・踏切・交差点(次数3以上の分岐点、低い重み)が少ないほど易しい",
  },
  car_stress_weight: {
    label: "車の圧迫感",
    description: "推定される車の圧迫感(1-5)が低いほど易しい。自動車との近さ・速さ・車線数・自転車インフラの指標で、信号や交差点の頻度は含まない(別軸)",
  },
  accident_weight: { label: "事故", description: "事故密度(件/(km・年)、警察庁統計)が低いほど易しい" },
  night_weight: {
    label: "夜間",
    description: "街灯なし・トンネルが少ないほど易しい。既定重み0(夜間ライドを重視する場合に個別に上げる想定)",
  },
};

export const PREFERENCE_AXES: readonly PreferenceAxisDef[] = (
  Object.keys(PREFERENCE_AXIS_META) as (keyof RoutePreferenceWeights)[]
).map((weightKey) => ({ weightKey, ...PREFERENCE_AXIS_META[weightKey] }));
