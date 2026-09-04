// APIの型はbackendのOpenAPIスキーマから生成した generated/api.d.ts を正とし、
// このファイルはその再エクスポート＋フロント専用の補正だけを持つ（手書きの二重管理を
// しない。docs/improvement-plan.md T4）。backendのレスポンスモデルを変更したら
// backend/scripts/export_openapi.py → npm run generate:api で生成物を更新すること
// （CIのapi-contractジョブがドリフトを検知する）。
//
// Required<>で包む理由: pydanticはデフォルトNoneのフィールドもJSONに常に含めて
// 返すが、OpenAPI上は「必須でない」扱いになりopenapi-typescriptの生成型では
// optional（`?`）になる。実際のレスポンス形に合わせて必須へ戻す。
//
// geometryだけ手動で補正する理由: backend側はGeoJSONを`dict`（自由なオブジェクト）と
// して扱うためスキーマに構造が現れない。フロントは座標へアクセスするため
// GeoJSON.LineString（@types/geojson）で具体化する。
import type { components } from "./generated/api";

type Schemas = components["schemas"];

export type Coordinates = Schemas["Coordinates"];

// フロント専用（位置情報の出所）。APIには現れない。緯度経度の手書きテキスト入力は撤去済み
// （改善計画T35）だが、改善計画T366で地図タップによる出発地点の手動指定を再導入したため
// "manual"を持つ（T35が撤去したのはテキスト欄という入力方式であり、手動指定という概念自体
// ではない）。
export type LocationSource = "geolocation" | "default" | "manual";

export type RouteSegment = Omit<Required<Schemas["RouteSegment"]>, "geometry"> & {
  geometry: GeoJSON.LineString;
};

export type RoutePreviewRequest = Schemas["RoutePreviewRequest"];

// geometry: 区間の道なり形状（ルートgeometryの部分列）。バックエンドはdict|Noneのため
// スキーマに構造が現れず、RouteCandidate.geometryと同じ理由で手動補正する（null許容）。
export type RouteSegmentDetail = Omit<Required<Schemas["RouteSegmentDetail"]>, "geometry"> & {
  geometry: GeoJSON.LineString | null;
};

export type RouteCandidate = Omit<Required<Schemas["RouteCandidate"]>, "geometry" | "segments"> & {
  geometry: GeoJSON.LineString;
  segments: RouteSegmentDetail[] | null;
};

// フロント専用（改善計画T550）。APIには現れない。地図上でクリックされた区間
// （RouteSegmentDetail、geometryはfeature.propertiesから除外済みのためnull）と、実際に
// クリックされた地点（マーカー表示位置。MapView.tsx: handleRouteSegmentClickがe.lngLatから
// 組み立てる）を束ねてpage.tsxのstateへ持たせる。「ルート結果」タブ（RouteAxisProfile）は
// これがnullでない間、ルート全体の内訳の代わりにこの区間の内訳を表示する。
export interface SelectedRouteSegment {
  segment: RouteSegmentDetail;
  latitude: number;
  longitude: number;
}

export type RouteGenerateRequest = Schemas["RouteGenerateRequest"];

export type RouteGenerateResponse = Omit<Required<Schemas["RouteGenerateResponse"]>, "routes"> & {
  routes: RouteCandidate[];
};

// 改善計画T265: バックグラウンドジョブ化に伴う型。POST /api/routes/generateは即座に
// job_idを返し、GET /api/routes/generate/{job_id}をポーリングして結果を得る
// （frontend services/routeApi.ts参照）。
export type RouteGenerateJobCreatedResponse = Schemas["RouteGenerateJobCreatedResponse"];

export type RouteGenerateJobStatusResponse = Omit<Required<Schemas["RouteGenerateJobStatusResponse"]>, "result"> & {
  result: RouteGenerateResponse | null;
};

export type RoutePreferenceWeights = Schemas["RoutePreferenceWeights"];
// 0次ハードフィルタ(自転車通行禁止/高速道路/幹線道路)の個別ON/OFF上書き(改善計画T266)。
export type HardFilterOverride = Schemas["HardFilterOverride"];
// 改善計画T292: 車の圧迫感（car_stress）専用レシピ（CarStressRecipeOverride・
// RoadSuitabilityRecipeOverride・MotorVehicleDensityRecipeOverride）はbackend側で
// 専用Pythonレシピごと廃止（内部軸6つ+公開軸1つの階層構造へ再実装）したため、
// 対応する型定義も削除した。

// 実際に適用された条件のエコー（研究インターフェース改善 §10-6）。実験スロットの
// 保持・比較表・再現性メモの入力になる。
export type GenerationConditions = Schemas["GenerationConditions"];

// 軸カタログ（改善計画T269）。GET /api/axis-catalogのレスポンス。軸スタジオ（T270）が
// 管理API経由でDBへ追加した軸も、コード変更・再デプロイなしにここへ反映される。
export type AxisCatalogEntry = Schemas["AxisCatalogEntry"];
export type AxisCatalogResponse = Schemas["AxisCatalogResponse"];

// 軸スタジオ（改善計画T270）が使う評価軸定義のCRUD型。/api/admin/axis-definitions。
export type AxisDefinitionPayload = Schemas["AxisDefinitionPayload"];
export type AxisDefinitionResponse = Schemas["AxisDefinitionResponse"];
export type MaterialTerm = Schemas["MaterialTerm"];
export type BreakpointLinearShape = Schemas["BreakpointLinearShape"];
export type CategoricalShape = Schemas["CategoricalShape"];
export type AxisShape = BreakpointLinearShape | CategoricalShape;

// 材料カタログ（改善計画T277）。GET /api/material-catalogのレスポンス。軸スタジオの
// 材料選択候補を、材料自体の追加時にコード変更・再デプロイだけで反映する。
export type MaterialCatalogEntry = Schemas["MaterialCatalogEntry"];
export type MaterialCatalogResponse = Schemas["MaterialCatalogResponse"];

// 材料の実データ値一覧（改善計画T340）。GET /api/material-catalog/{material_id}/valuesの
// レスポンス。highway/surface/smoothnessのようなオープンエンドな多値材料向け。
// 改善計画T345フォローアップ: 各値に日本語ラベル(label)も付く
// （backend/app/domain/material_catalog.py: MaterialSpec.value_labelsが単一ソース）。
export type MaterialValueEntry = Schemas["MaterialValueEntry"];
export type MaterialValuesResponse = Schemas["MaterialValuesResponse"];

// 材料ごとの欠損割合。GET /api/admin/material-catalog/coverage（Basic認証必須、
// 管理画面「材料」タブが同一オリジンのroute handler経由で取得する）のレスポンス。
export type MaterialCoverageEntry = Schemas["MaterialCoverageEntry"];
export type MaterialCoverageResponse = Schemas["MaterialCoverageResponse"];

// 派生データ鮮度台帳。GET /api/admin/derived-data/freshness（Basic認証必須、
// 管理画面「鮮度」タブが同一オリジンのroute handler経由で取得する）のレスポンス。
export type SourceFreshnessEntry = Schemas["SourceFreshnessEntry"];
export type AlgorithmVersionFreshnessEntry = Schemas["AlgorithmVersionFreshnessEntry"];
export type GenerationFreshnessEntry = Schemas["GenerationFreshnessEntry"];
export type ElevationCompletenessEntry = Schemas["ElevationCompletenessEntry"];
export type DerivedDataFreshnessResponse = Schemas["DerivedDataFreshnessResponse"];
