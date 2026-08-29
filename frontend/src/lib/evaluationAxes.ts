// 評価軸のカタログ（単一ソース）。mapLayers.tsと同じ「カタログ＋汎用列挙」の型
// （改善計画T25、docs/research-interface-review-2026-08-15.md §10-8）。
//
// 静的属性P1（停止密度）でRoutePreferenceに4つ目の軸が増えたのを機に、軸のid・重みキー・
// 表示名が RouteList のhint文言・WeightPanel の入力欄リストへ手作業で分散していた状態
// （軸を増やすたびにズレる「第3の手動同期ペア」、レビュー指摘）を解消する。
//
// ラベルは Record<キー, string> として書くことで、backend/app/scoring.yaml のキー集合
// （OpenAPI型生成でフロントへ届く ScoringWeights）とフィールドが1対1で揃っていることを
// TypeScriptのコンパイルで強制する（キーの過不足はコンパイルエラーになる）。
// route_preference側は改善計画T221 Stage Bでaxis_idキーの辞書（RoutePreferenceWeightsは
// index signature型）へ一般化されたためコンパイル時のキー照合はできず、代わりに
// evaluationAxes.test.tsがaxis-catalog.jsonのpreference_defaultsとキー集合を突き合わせる。
import type { ScoringWeights } from "@/types/route";
import { SECONDARY_AXES } from "@/components/Map/secondaryAxes";

export interface ScoringAxisDef {
  /** RouteScoreComponent.axis（backend/app/services/route_scorer.py）と一致する値。
   * weightKeyから"_weight"接尾辞を除いたもの（バックエンド側の命名規約、
   * test_route_scorer.pyで固定）。 */
  id: string;
  weightKey: keyof ScoringWeights;
  /** RouteListのhint文・WeightPanelの入力欄ラベルに共通で使う表示名 */
  label: string;
  /** この軸が何を表すかの短い説明。WeightPanel.tsxがFieldLabelのdescriptionとして
   * ラベル横の情報アイコン開閉表示に使う（コメント修正: デッドコード監査2026-08-25、
   * 「将来のツールチップ等向け、現状は未使用」という記述は事実誤認だった）。 */
  description: string;
}

// 改善計画T401: 従来のelevation_weight/wind_weight/road_weightはoverall_difficulty
// （軸スタジオのRoutePreference.weightsで既に重み付け合成済みの値）に既に織り込まれて
// いたため二重管理だった。distance（目標距離への近さ）とdifficulty（overall_difficulty）の
// 2指標へ単純化した。
const SCORING_AXIS_META: Record<keyof ScoringWeights, Omit<ScoringAxisDef, "id" | "weightKey">> = {
  distance_weight: { label: "距離の合わせ込み", description: "指定距離との差の小ささ" },
  difficulty_weight: { label: "総合難易度", description: "軸スタジオの重みで合成した総合難易度が小さいほど高評価" },
};

export const SCORING_AXES: readonly ScoringAxisDef[] = (
  Object.keys(SCORING_AXIS_META) as (keyof ScoringWeights)[]
).map((weightKey) => ({
  id: weightKey.replace(/_weight$/, ""),
  weightKey,
  ...SCORING_AXIS_META[weightKey],
}));

export interface PreferenceAxisDef {
  /** route_preference（axis_idキーの重み辞書）のキー。backend
   * domain/axis_definitions.py: AXIS_DEFINITIONSのaxis_idと一致する
   * （改善計画T221 Stage B: 旧weightKey[elevation_weight等]→axis_idの手書き対応表
   * PREFERENCE_WEIGHT_KEY_BY_AXIS_IDは、重み辞書自体がaxis_idキーになったため廃止）。 */
  axisId: string;
  /** 区間の色分け・WeightPanelの入力欄ラベルに共通で使う表示名 */
  label: string;
  description: string;
}

// axis_idごとの説明文（1〜2文の要約）。ラベル自体は下記PREFERENCE_AXESが
// SECONDARY_AXES（地図と共有する軸カタログ）から導出するため、ここには持たない。
const PREFERENCE_AXIS_DESCRIPTIONS: Record<string, string> = {
  gradient: "登り坂の急さが小さいほど易しい",
  surface_q: "舗装路であるほど易しい",
  wind: "向かい風が弱いほど易しい",
  stop_density: "信号・横断歩道・一時停止・踏切・交差点(次数3以上の分岐点、低い重み)が少ないほど易しい",
  car_stress:
    "推定される車の圧迫感(1-5)が低いほど易しい。自動車との近さ・速さ・車線数・自転車インフラの指標で、信号や交差点の頻度は含まない(別軸)",
  accident: "事故密度(件/(km・年)、警察庁統計)が低いほど易しい",
  night: "街灯なし・トンネルが少ないほど易しい。既定重み0(夜間ライドを重視する場合に個別に上げる想定)",
  bicycle_infra_quality: "専用の自転車インフラ（分離自転車道・自転車レーン等）が整備されているほど易しい",
};

// 区間難易度の重み（2次要素）8軸。改善計画: 「研究タブの2次要素の調整の仕方がわからない、
// 地図表示・地図の見え方パネルと考え方を併せて再設計して」という実機フィードバックへの
// 対応。SECONDARY_AXES（secondaryAxes.ts、地図チップ・地図の見え方パネルの推定グループが
// 共有する単一ソース）をそのままなぞって並び順・ラベルを導出することで、「研究タブの
// この重みは地図のどの軸に対応するか」が名前と並びだけで分かるようにする（片側import、
// 新しい軸が増えてもこのファイルの変更は不要）。windは対応する軸がSECONDARY_AXESに
// 無いため（表示カタログ未登録、動的データ由来でレイヤーを持たない）末尾へ別途追加する。
// 改善計画T367: bicycle_infra_qualityは改善計画T347時点ではshow_map_icon=falseだったため
// windと同じ「地図レイヤー非対応」扱いで末尾へ別途追加していたが、T367で地図表示に対応し
// show_map_icon=trueへ変更したためSECONDARY_AXESへ自然に含まれるようになった（手書きの
// 個別追加は不要、二重登録を避けるため撤去）。
export const PREFERENCE_AXES: readonly PreferenceAxisDef[] = [
  ...SECONDARY_AXES.map(
    (axis): PreferenceAxisDef => ({
      axisId: axis.axisId,
      label: axis.label,
      description: PREFERENCE_AXIS_DESCRIPTIONS[axis.axisId] ?? "",
    })
  ),
  { axisId: "wind", label: "風", description: PREFERENCE_AXIS_DESCRIPTIONS.wind },
];

// 軸の分類（観測/推定/動的、改善計画T267で確定・目論見書3章）は、一般向けルート設定画面
// （RouteSettingsPanel）が軸をこの3カテゴリでグルーピング表示するために使っていたが、
// 改善計画T306でその表示を撤去したのに伴いこのフロント側の静的対応表（AxisCategory型・
// AXIS_CATEGORIES・axisCategory()）も削除した。分類データ自体（backend側の`category`
// フィールド、GET /api/axis-catalogのAxisCatalogEntry.category）は他用途・将来の
// プロファイル機能のため引き続き存在する。復元する場合はgit履歴（本コミット直前）参照。
