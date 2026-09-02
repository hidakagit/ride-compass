// 評価軸のカタログ（単一ソース）。mapLayers.tsと同じ「カタログ＋汎用列挙」の型
// （改善計画T25、docs/research-interface-review-2026-08-15.md §10-8）。
//
// 静的属性P1（停止密度）でRoutePreferenceに4つ目の軸が増えたのを機に、軸のid・重みキー・
// 表示名が RouteList のhint文言・RouteSettingsPanel の入力欄リストへ手作業で分散していた
// 状態（軸を増やすたびにズレる「第3の手動同期ペア」、レビュー指摘）を解消する。
//
// route_preference側は改善計画T221 Stage Bでaxis_idキーの辞書（RoutePreferenceWeightsは
// index signature型）へ一般化されたためコンパイル時のキー照合はできず、代わりに
// evaluationAxes.test.tsがaxis-catalog.jsonのpreference_defaultsとキー集合を突き合わせる。
import type { RoutePreferenceWeights } from "@/types/route";
import { SECONDARY_AXES } from "@/components/Map/secondaryAxes";
import axisCatalog from "@/types/generated/axis-catalog.json";

// 区間難易度の重み（route_preference）の既定値。「既定値に戻す」ボタンの起点、および
// 上書き有効化の直後に送る初期値として使う（改善計画T548: 従来はWeightPanel.tsxが
// この定数をexportしていたが、total_score撤去に伴いWeightPanel自体を削除したため
// こちらへ移設した）。axis-catalog.jsonのpreference_defaults（backend domain/
// axis_definitions.py: AXIS_DEFINITIONSのdefault_weightを生成物として書き出したもの、
// 改善計画T221 Stage B）から読むことで、軸の増減・既定値変更に自動追従する。
export const DEFAULT_ROUTE_PREFERENCE: RoutePreferenceWeights = axisCatalog.preference_defaults;

export interface PreferenceAxisDef {
  /** route_preference（axis_idキーの重み辞書）のキー。backend
   * domain/axis_definitions.py: AXIS_DEFINITIONSのaxis_idと一致する
   * （改善計画T221 Stage B: 旧weightKey[elevation_weight等]→axis_idの手書き対応表
   * PREFERENCE_WEIGHT_KEY_BY_AXIS_IDは、重み辞書自体がaxis_idキーになったため廃止）。 */
  axisId: string;
  /** 区間の色分け・RouteSettingsPanelの入力欄ラベルに共通で使う表示名 */
  label: string;
  description: string;
  /** 改善計画T440: この軸が専用のway_id→値配信レイヤー（Redis経由、ルート未確定時から
   * 地図上で視界内の全道路を線色分け表示できる）を持つかの宣言（domain/
   * axis_definitions.py: AxisDefinition.dedicated_way_value_layer参照）。
   * RouteSettingsPanel.tsx（mapColorLayerIdFor）が、axis_idのハードコード比較
   * （wind/gradientのみ）ではなくこのフィールドで判定する。 */
  dedicatedWayValueLayer: boolean;
  /** 改善計画T466: 軸スタジオのdisplay_thresholds_override（未設定時はundefined）。
   * dedicatedWayValueLayer軸（現状windのみ）の評価軸グループ色分けしきい値に使う
   * （windAxisLayer.ts: windAxisColorExpression、gradientのgradientBoundaries[T443]と同型）。
   * SECONDARY_AXES由来の軸はkind="ramp"のためこのフィールドを使わない（常にundefined）。 */
  displayThresholdsOverride?: readonly number[] | null;
  /** 改善計画T513: displayThresholdsOverrideと対になる、段階ごとの体感ラベルの軽量な
   * 上書き。SECONDARY_AXES由来の軸はkind="ramp"のためこのフィールドを使わない
   * （常にundefined、windAxisLegend/gradientAxisLegendの消費者のみが対象）。 */
  displayBandLabelsOverride?: readonly string[] | null;
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
      // 改善計画T473訂正: 以前は「SECONDARY_AXESはkind='ramp'軸のみを含み、専用way_id配信層
      // （dedicated_way_value_layer）とは構造上排他的」という理由で常にfalse固定していたが、
      // 誤りだった。gradientはkind="none"（材料がタイル非依存）でありながら
      // dedicated_way_value_layer=trueという組み合わせが実在する（軸自身のデータをそのまま
      // 反映する、SECONDARY_AXES側のdedicatedWayValueLayerフィールド参照）。
      dedicatedWayValueLayer: axis.dedicatedWayValueLayer ?? false,
      displayThresholdsOverride: axis.displayThresholdsOverride,
      displayBandLabelsOverride: axis.displayBandLabelsOverride,
    })
  ),
  { axisId: "wind", label: "風", description: PREFERENCE_AXIS_DESCRIPTIONS.wind, dedicatedWayValueLayer: true },
];

// 軸の分類（観測/推定/動的、改善計画T267で確定・目論見書3章）は、一般向けルート設定画面
// （RouteSettingsPanel）が軸をこの3カテゴリでグルーピング表示するために使っていたが、
// 改善計画T306でその表示を撤去したのに伴いこのフロント側の静的対応表（AxisCategory型・
// AXIS_CATEGORIES・axisCategory()）も削除した。分類データ自体（backend側の`category`
// フィールド、GET /api/axis-catalogのAxisCatalogEntry.category）は他用途・将来の
// プロファイル機能のため引き続き存在する。復元する場合はgit履歴（本コミット直前）参照。
