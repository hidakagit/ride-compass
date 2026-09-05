// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { RouteSegmentDetail } from "@/types/route";
import {
  nearestPointOnLineString,
  restoreRouteSegmentProperties,
  segmentsToFeatureCollection,
  type RouteSegmentProperties,
} from "./MapView";

function makeSegment(overrides: Partial<RouteSegmentDetail>): RouteSegmentDetail {
  return {
    geometry: null,
    start_latitude: 35.7,
    start_longitude: 139.7,
    end_latitude: 35.71,
    end_longitude: 139.71,
    cumulative_distance_km: 0,
    distance_km: 1.0,
    estimated_arrival_time: null,
    axis_difficulties: { gradient: 10, wind: 20, surface_q: 0, stop_density: 0 },
    material_values: { gradient_percent: 1.2, wind_drag_ratio: 0.5 },
    axis_contributions: { gradient: 5, wind: 10, surface_q: 0, stop_density: 0 },
    difficulty: 12,
    ...overrides,
  };
}

describe("nearestPointOnLineString", () => {
  // ユーザー指摘（2026-09-03、「ピンの位置は実際に情報表示しているルート上に補正してほしい」）:
  // 当たり判定（DETAIL_HIT_LAYER_ID、幅24px）は見た目の線より広いため、クリック地点を
  // そのままマーカー位置に使うとルート線から見た目にズレる。区間クリックのマーカー位置を
  // 区間geometry上へスナップするために使う純関数の単体テスト。
  it("線分の真上の点はそのまま返す", () => {
    const line: [number, number][] = [
      [0, 0],
      [10, 0],
    ];
    expect(nearestPointOnLineString(line, [5, 0])).toEqual([5, 0]);
  });

  it("線分から外れた点は垂線の足（線分上の最近点）へ補正する", () => {
    const line: [number, number][] = [
      [0, 0],
      [10, 0],
    ];
    expect(nearestPointOnLineString(line, [5, 3])).toEqual([5, 0]);
  });

  it("垂線の足が線分の外に出る場合は端点へクランプする", () => {
    const line: [number, number][] = [
      [0, 0],
      [10, 0],
    ];
    expect(nearestPointOnLineString(line, [-5, 2])).toEqual([0, 0]);
    expect(nearestPointOnLineString(line, [15, 2])).toEqual([10, 0]);
  });

  it("複数線分のうち最も近い線分上の点を選ぶ", () => {
    const line: [number, number][] = [
      [0, 0],
      [10, 0],
      [10, 10],
    ];
    // (10, 5)に最も近いのは2本目の線分[(10,0),(10,10)]上の(10,5)
    expect(nearestPointOnLineString(line, [10.5, 5])).toEqual([10, 5]);
  });

  it("座標が1点だけならその点を返す", () => {
    expect(nearestPointOnLineString([[3, 4]], [0, 0])).toEqual([3, 4]);
  });

  it("座標が空なら渡された点をそのまま返す", () => {
    expect(nearestPointOnLineString([], [7, 8])).toEqual([7, 8]);
  });
});

describe("segmentsToFeatureCollection", () => {
  it("区間の道なり形状（geometry）があればそれをfeatureの形状に使う", () => {
    const geometry: GeoJSON.LineString = {
      type: "LineString",
      coordinates: [
        [139.7, 35.7],
        [139.703, 35.702], // 中間点＝カーブを表す形状点
        [139.71, 35.71],
      ],
    };
    const collection = segmentsToFeatureCollection([makeSegment({ geometry })]);

    expect(collection.features[0].geometry).toEqual(geometry);
  });

  it("geometryが無い区間は従来どおり始点・終点を結ぶ直線で代替する", () => {
    const collection = segmentsToFeatureCollection([makeSegment({ geometry: null })]);

    expect(collection.features[0].geometry).toEqual({
      type: "LineString",
      coordinates: [
        [139.7, 35.7],
        [139.71, 35.71],
      ],
    });
  });

  it("propertiesには形状を重複して持たせない（ポップアップ用の値だけを残す）", () => {
    const geometry: GeoJSON.LineString = {
      type: "LineString",
      coordinates: [
        [139.7, 35.7],
        [139.71, 35.71],
      ],
    };
    const collection = segmentsToFeatureCollection([makeSegment({ geometry })]);

    const properties = collection.features[0].properties;
    expect(properties).not.toHaveProperty("geometry");
    // 色分け式・ポップアップが参照する値は残っている
    expect(properties.axis_difficulties).toEqual({ gradient: 10, wind: 20, surface_q: 0, stop_density: 0 });
    expect(properties.material_values).toEqual({ gradient_percent: 1.2, wind_drag_ratio: 0.5 });
    expect(properties.difficulty).toBe(12);
  });
});

describe("restoreRouteSegmentProperties", () => {
  function withoutGeometry(segment: RouteSegmentDetail): RouteSegmentProperties {
    const properties: Partial<RouteSegmentDetail> = { ...segment };
    delete properties.geometry;
    return properties as RouteSegmentProperties;
  }

  // クリック時にqueryRenderedFeatures経由で読み戻すfeature.propertiesでは、MapLibreが
  // オブジェクト型フィールドをJSON文字列へシリアライズする（vector tile相当の内部表現へ
  // 変換する際、プリミティブ型しか保持できないvector tile仕様の制約のため）。
  // segmentsToFeatureCollectionが渡す時点の素のオブジェクトではなく、この文字列化された
  // 形を入力にする。
  function makeSerializedProperties(overrides: Partial<RouteSegmentProperties> = {}): RouteSegmentProperties {
    const base = makeSegment({});
    return {
      ...withoutGeometry(base),
      axis_difficulties: JSON.stringify(base.axis_difficulties) as unknown as Record<string, number>,
      axis_contributions: JSON.stringify(base.axis_contributions) as unknown as Record<string, number>,
      material_values: JSON.stringify(base.material_values) as unknown as Record<string, number>,
      ...overrides,
    };
  }

  it("文字列化されたaxis_difficulties・axis_contributions・material_valuesをすべてオブジェクトへ復元する", () => {
    const restored = restoreRouteSegmentProperties(makeSerializedProperties());

    expect(restored.axis_difficulties).toEqual({ gradient: 10, wind: 20, surface_q: 0, stop_density: 0 });
    expect(restored.axis_contributions).toEqual({ gradient: 5, wind: 10, surface_q: 0, stop_density: 0 });
    expect(restored.material_values).toEqual({ gradient_percent: 1.2, wind_drag_ratio: 0.5 });
  });

  // 実際に発生していたクラッシュの再現: material_valuesのパースが漏れていると、文字列の
  // ままObject.entries()に渡され1文字ずつのエントリになる（利用側のformatMaterialValueが
  // .toFixed()を呼びTypeErrorになる、frontend/src/app/page.tsx参照）。
  it("パース漏れが無ければmaterial_valuesはObject.entries()で正しい[materialId, value]の組を返す", () => {
    const restored = restoreRouteSegmentProperties(makeSerializedProperties());

    const entries = Object.entries(restored.material_values ?? {});
    expect(entries).toEqual([
      ["gradient_percent", 1.2],
      ["wind_drag_ratio", 0.5],
    ]);
  });

  it("既にオブジェクトのまま（文字列化されていない）フィールドはそのまま返す", () => {
    const properties = withoutGeometry(makeSegment({}));

    expect(restoreRouteSegmentProperties(properties)).toEqual(properties);
  });
});
