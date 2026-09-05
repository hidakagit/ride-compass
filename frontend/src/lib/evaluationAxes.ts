// 評価軸のカタログ（単一ソース）。mapLayers.tsと同じ「カタログ＋汎用列挙」の型。
// 軸のid・重みキー・表示名をここへ一本化し、他のUI（RouteSettingsPanel等）へ
// 手作業で分散させない。
//
// RoutePreferenceWeightsはindex signature型（axis_idキーの辞書）のためコンパイル時の
// キー照合はできず、代わりにevaluationAxes.test.tsがaxis-catalog.jsonの
// preference_defaultsとキー集合を突き合わせる。
import type { RoutePreferenceWeights } from "@/types/route";
import type { MapValueKind } from "@/components/Map/valueScale";
import { SECONDARY_AXES } from "@/components/Map/secondaryAxes";
import axisCatalog from "@/types/generated/axis-catalog.json";

// 区間難易度の重み（route_preference）の既定値。「既定値に戻す」ボタンの起点、および
// 上書き有効化の直後に送る初期値として使う。axis-catalog.jsonのpreference_defaults
// （backend domain/axis_definitions.py: AXIS_DEFINITIONSのdefault_weightを生成物として
// 書き出したもの）から読むことで、軸の増減・既定値変更に自動追従する。
export const DEFAULT_ROUTE_PREFERENCE: RoutePreferenceWeights = axisCatalog.preference_defaults;

export interface PreferenceAxisDef {
  /** route_preference（axis_idキーの重み辞書）のキー。backend
   * domain/axis_definitions.py: AXIS_DEFINITIONSのaxis_idと一致する。 */
  axisId: string;
  /** 区間の色分け・RouteSettingsPanelの入力欄ラベルに共通で使う表示名 */
  label: string;
  description: string;
  /** この軸が専用のway_id→値配信レイヤー（Redis経由、ルート未確定時から地図上で
   * 視界内の全道路を線色分け表示できる）を持つかの宣言（domain/axis_definitions.py:
   * AxisDefinition.dedicated_way_value_layer参照）。`page.tsx`が、axis_idの
   * ハードコード比較ではなくこのフィールドで`dedicatedWayValueDisplays`
   * （軸id→表示宣言の汎用Map）・レンズ選択肢の`routeOnly`判定を行う。 */
  dedicatedWayValueLayer: boolean;
  /** 軸スタジオのdisplay_thresholds_override（未設定時はundefined）。
   * dedicatedWayValueLayer軸（現状windのみ）の評価軸グループ色分けしきい値に使う
   * （dedicatedWayValueLayer.ts: dedicatedWayValueColorExpression）。
   * SECONDARY_AXES由来の軸はkind="ramp"のためこのフィールドを使わない（常にundefined）。 */
  displayThresholdsOverride?: readonly number[] | null;
  /** displayThresholdsOverrideと対になる、段階ごとの体感ラベルの軽量な上書き。
   * SECONDARY_AXES由来の軸はkind="ramp"のためこのフィールドを使わない
   * （常にundefined、dedicatedWayValueLegendの消費者のみが対象）。 */
  displayBandLabelsOverride?: readonly string[] | null;
  /** 地図がこの軸について塗る値の種類・単位（GET /api/axis-catalogのmap_value_kind/
   * map_value_unit）。専用way値レイヤーの色式・凡例（dedicatedWayValueLayer.ts）が使う。 */
  mapValueKind?: MapValueKind;
  mapValueUnit?: string;
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

// 区間難易度の重み（2次要素）8軸。SECONDARY_AXES（secondaryAxes.ts、地図チップ・
// 地図の見え方パネルの推定グループが共有する単一ソース）をそのままなぞって並び順・
// ラベルを導出することで、「この重みは地図のどの軸に対応するか」が名前と並びだけで
// 分かるようにする（片側import、新しい軸が増えてもこのファイルの変更は不要）。windは
// 対応する軸がSECONDARY_AXESに無いため（表示カタログ未登録、動的データ由来でレイヤーを
// 持たない）末尾へ別途追加する。
export const PREFERENCE_AXES: readonly PreferenceAxisDef[] = [
  ...SECONDARY_AXES.map(
    (axis): PreferenceAxisDef => ({
      axisId: axis.axisId,
      label: axis.label,
      description: PREFERENCE_AXIS_DESCRIPTIONS[axis.axisId] ?? "",
      // SECONDARY_AXESはkind='ramp'軸に限らない——gradientはkind="none"（材料がタイル
      // 非依存）でありながらdedicated_way_value_layer=trueという組み合わせが実在するため、
      // SECONDARY_AXES側のdedicatedWayValueLayerフィールドをそのまま引き継ぐ。
      dedicatedWayValueLayer: axis.dedicatedWayValueLayer ?? false,
      displayThresholdsOverride: axis.displayThresholdsOverride,
      displayBandLabelsOverride: axis.displayBandLabelsOverride,
      mapValueKind: axis.mapValueKind,
      mapValueUnit: axis.mapValueUnit,
    })
  ),
  {
    axisId: "wind",
    label: "風",
    description: PREFERENCE_AXIS_DESCRIPTIONS.wind,
    dedicatedWayValueLayer: true,
    mapValueKind: "difficulty",
    mapValueUnit: "",
  },
];

// 軸の分類（観測/推定/動的）は一般向けルート設定画面（RouteSettingsPanel）の表示では
// 使わず、公開済みの軸をフラットな1本のリストとして扱う。分類データ自体（backend側の
// `category`フィールド、GET /api/axis-catalogのAxisCatalogEntry.category）は他用途の
// ため引き続き存在する。
