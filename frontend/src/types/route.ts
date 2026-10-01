// APIの型はbackendのOpenAPIスキーマから生成した generated/api.d.ts を正とし、
// このファイルはその再エクスポートとフロント専用の型だけを持つ（応答の形を補正しない）。
// backendのレスポンスモデルを変更したら
// backend/scripts/export_openapi.py → npm run generate:api で生成物を更新すること
// （CIのapi-contractジョブがドリフトを検知する）。
import type { components, paths } from "./generated/api";

type Schemas = components["schemas"];
/** 応答が1つのモデルではなく、状態で形の変わる共用体の口は、口の応答の型をそのまま引く。 */
type GetJson<P extends keyof paths> = paths[P] extends {
  get: { responses: { 200: { content: { "application/json": infer T } } } };
}
  ? T
  : never;

export type Coordinates = Schemas["Coordinates"];

// フロント専用（位置情報の出所）。APIには現れない。緯度経度の手書きテキスト入力は持たないが、
// 地図タップによる出発地点の手動指定を"manual"として持つ。
/** 地図をタップして置ける地点の役割。どれか1つだけが「置ける状態」になり、その間だけ
 * 地図のタップがピンの配置として扱われる（役割ごとに別々の武装フラグを持たない）。 */
export type PinRole = "origin" | "waypoint" | "destination";

export type LocationSource = "geolocation" | "default" | "manual";

export type RouteSegmentDetail = Schemas["RouteSegmentDetail"];

export type RouteCandidate = Schemas["RouteCandidate"];
export type OverallDifficulty = Schemas["OverallDifficulty"];

// フロント専用。APIには現れない。地図上でクリックされた区間
// （RouteSegmentDetail、geometryはfeature.propertiesから除外済みのためnull）と、実際に
// クリックされた地点（マーカー表示位置。MapView.tsx: handleRouteSegmentClickがe.lngLatから
// 組み立てる）を束ねて`features/route/useRouteResults.ts`のstateへ持たせる。「ルート結果」タブ（RouteAxisProfile）は
// これがnullでない間、ルート全体の内訳の代わりにこの区間の内訳を表示する。
export interface SelectedRouteSegment {
  segment: RouteSegmentDetail;
  latitude: number;
  longitude: number;
}

export type RouteGenerateRequest = Schemas["RouteGenerateRequest"];

// ルート生成のバックグラウンドジョブ化に伴う型。POST /api/routes/generateは即座に
// job_idを返し、GET /api/routes/generate/{job_id}をポーリングして結果を得る
// （frontend features/route/routeApi.ts参照）。
export type RouteGenerateJobStatusResponse = GetJson<"/api/routes/generate/{job_id}">;

export type RoutePreferenceWeights = Schemas["RoutePreferenceWeights"];
// 0次ハードフィルタ(自転車通行禁止/高速道路/幹線道路)の個別ON/OFF上書き。
export type HardFilterOverride = Schemas["HardFilterOverride"];

// 実際に適用された条件のエコー（研究インターフェース改善 §10-6）。実験スロットの
// 保持・比較表・再現性メモの入力になる。
export type GenerationConditions = Schemas["GenerationConditions"];

// 軸カタログの1軸。GET /api/axis-catalogのレスポンスの要素。軸スタジオが管理API経由でDBへ追加した
// 軸も、コード変更・再デプロイなしにここへ反映される。
export type AxisCatalogEntry = Schemas["AxisCatalogEntry"];

// 軸スタジオが使う評価軸定義のCRUD型。/api/admin/axis-definitions。
export type AxisDefinitionPayload = Schemas["AxisDefinitionPayload"];
export type AxisDefinitionResponse = Schemas["AxisDefinitionResponse"];
// 形は要求（保存）にも応答にも現れ、契約は要求側（既定値の項目を省略できる）と応答側（必ず載る）に分かれる。
// 画面は形を組み立てて送る側なので要求側を使う（応答側の形はそのまま当てはまる）。
type BreakpointLinearShape = Schemas["BreakpointLinearShape-Input"];
type CategoricalShape = Schemas["CategoricalShape-Input"];
export type AxisShape = BreakpointLinearShape | CategoricalShape;

// JMA動的タイルの在否インデックス。GET /api/jma-tile-indexのレスポンス。
// 平常時に空タイルを取りに行かないための「どのタイルに中身があるか」の一覧
// （features/map/layers/jmaTileIndex.tsが解釈する）。
export type JmaTileIndexResponse = GetJson<"/api/jma-tile-index">;

// 材料の実データ値の1件。GET /api/admin/material-catalog/{material_id}/valuesのレスポンスの要素。
// highway/surface/smoothnessのようなオープンエンドな多値材料向け。各値に日本語ラベル
// (label)も付く（backend/app/domain/material_catalog.py: MaterialSpec.value_labelsが
// 単一ソース）。
export type MaterialValueEntry = Schemas["MaterialValueEntry"];

// 材料ごとの欠損割合。GET /api/admin/material-catalog/coverage（Basic認証必須、
// 管理画面「材料」タブが同一オリジンのroute handler経由で取得する）のレスポンス。
export type MaterialCoverageResponse = Schemas["MaterialCoverageReport"];
export type MaterialCoverageEntry = MaterialCoverageResponse["materials"][number];

// 派生データ鮮度台帳。GET /api/admin/derived-data/freshness（Basic認証必須、
// 管理画面「データ保守」タブが同一オリジンのroute handler経由で取得する）のレスポンス。
export type DerivedDataFreshnessResponse = Schemas["DerivedDataFreshnessReport"];
export type DbStatusResponse = Schemas["DbStatusReport"];
