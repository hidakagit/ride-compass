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

// フロント専用（位置情報の出所）。APIには現れない。
export type LocationSource = "geolocation" | "manual" | "default";

export type RouteSegment = Omit<Required<Schemas["RouteSegment"]>, "geometry"> & {
  geometry: GeoJSON.LineString;
};

export type RoutePreviewRequest = Schemas["RoutePreviewRequest"];

export type RouteSegmentDetail = Required<Schemas["RouteSegmentDetail"]>;

export type RouteCandidate = Omit<Required<Schemas["RouteCandidate"]>, "geometry" | "segments"> & {
  geometry: GeoJSON.LineString;
  segments: RouteSegmentDetail[] | null;
};

export type RouteGenerateRequest = Schemas["RouteGenerateRequest"];

export type RouteGenerateResponse = Omit<Required<Schemas["RouteGenerateResponse"]>, "routes"> & {
  routes: RouteCandidate[];
};
