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
import { SECONDARY_AXES } from "@/components/Map/secondaryAxes";

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
  /** axis-catalog.jsonのaxis_id（backendレジストリ、registry_defaults.py参照）。
   * 改善計画T168: 研究タブの重み行直下に合成材料一覧（axisMaterials逆導出、
   * primaryAttributes.ts）を出すためのキー。windはレジストリ未登録
   * （RoutePreferenceの独立項目、axisLayers.tsのAXIS_LABELSコメント参照）のため
   * 対応するaxis_idを持たない（未指定）。 */
  axisId?: string;
}

// weightKeyごとの説明文（1〜2文の要約）。ラベル自体は下記PREFERENCE_AXESが
// SECONDARY_AXES（地図と共有する軸カタログ）から導出するため、ここには持たない。
const PREFERENCE_AXIS_DESCRIPTIONS: Record<keyof RoutePreferenceWeights, string> = {
  elevation_weight: "登り坂の急さが小さいほど易しい",
  road_weight: "舗装路であるほど易しい",
  wind_weight: "向かい風が弱いほど易しい",
  stop_weight: "信号・横断歩道・一時停止・踏切・交差点(次数3以上の分岐点、低い重み)が少ないほど易しい",
  car_stress_weight:
    "推定される車の圧迫感(1-5)が低いほど易しい。自動車との近さ・速さ・車線数・自転車インフラの指標で、信号や交差点の頻度は含まない(別軸)",
  accident_weight: "事故密度(件/(km・年)、警察庁統計)が低いほど易しい",
  night_weight: "街灯なし・トンネルが少ないほど易しい。既定重み0(夜間ライドを重視する場合に個別に上げる想定)",
};

// axis-catalog.jsonのaxis_id→対応する区間難易度の重みキー（6軸、windを除く）。
const PREFERENCE_WEIGHT_KEY_BY_AXIS_ID: Partial<Record<string, keyof RoutePreferenceWeights>> = {
  gradient: "elevation_weight",
  surface_q: "road_weight",
  stop_density: "stop_weight",
  car_stress: "car_stress_weight",
  night: "night_weight",
  accident: "accident_weight",
};

// 区間難易度の重み（2次要素）7軸。改善計画: 「研究タブの2次要素の調整の仕方がわからない、
// 地図表示・地図の見え方パネルと考え方を併せて再設計して」という実機フィードバックへの
// 対応。以前はラベル・並び順をこのファイル独自に持っており（例: stop_weightのラベルは
// 地図の「停止密度」とは別に「信号・踏切等」という言い換え、並び順もelevation→road→wind→
// stop→car_stress→accident→nightという独自順）、地図の見え方パネル（勾配・舗装質・
// 停止密度・車の圧迫感・夜間・事故密度）と見比べても対応が取れなかった。
// SECONDARY_AXES（secondaryAxes.ts、地図チップ・地図の見え方パネルの推定グループが
// 共有する単一ソース）をそのままなぞって並び順・ラベルを導出することで、「研究タブの
// この重みは地図のどの軸に対応するか」が名前と並びだけで分かるようにする（片側import、
// 新しい軸が増えてもこのファイルの変更は不要）。windは対応する軸がSECONDARY_AXESに
// 無いため（レジストリ未登録、距離指標寄り）末尾へ別途追加する。
export const PREFERENCE_AXES: readonly PreferenceAxisDef[] = [
  ...SECONDARY_AXES.flatMap((axis): PreferenceAxisDef[] => {
    const weightKey = PREFERENCE_WEIGHT_KEY_BY_AXIS_ID[axis.axisId];
    if (!weightKey) return [];
    return [
      {
        weightKey,
        label: axis.label,
        description: PREFERENCE_AXIS_DESCRIPTIONS[weightKey],
        axisId: axis.axisId,
      },
    ];
  }),
  { weightKey: "wind_weight", label: "風", description: PREFERENCE_AXIS_DESCRIPTIONS.wind_weight },
];
