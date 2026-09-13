"use client";

import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { tileBoundsLonLat } from "@/components/Map/dynamicWayValues";
import { tileBaseUrl } from "@/lib/tileBaseUrl";
import { getRoadGraphTiles } from "@/services/dbStatusApi";
import type { RoadGraphTilesResponse } from "@/types/route";
import styles from "./SplitCoverageMap.module.css";

/** ベースマップのスタイル。`MapView`と同じ経路（同一オリジンのrewrite、または
 * `NEXT_PUBLIC_TILE_BASE_URL`）で取る——スタイルJSON内のタイルURLはbackendが組み立てるため、
 * 両者が同じオリジンを指す前提が要る。 */
function mapStyleUrl(): string {
  return `${tileBaseUrl()}/api/basemap/styles/liberty`;
}

const SOURCE_ID = "split-coverage";
const FILL_LAYER_ID = "split-coverage-fill";
const LINE_LAYER_ID = "split-coverage-line";

export function tilesToGeojson(tiles: RoadGraphTilesResponse["tiles"]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: tiles.map((tile) => {
      const bounds = tileBoundsLonLat(tile.zoom, tile.x, tile.y);
      return {
        type: "Feature" as const,
        properties: { fetched_at: tile.fetched_at },
        geometry: {
          type: "Polygon" as const,
          coordinates: [
            [
              [bounds.west, bounds.north],
              [bounds.east, bounds.north],
              [bounds.east, bounds.south],
              [bounds.west, bounds.south],
              [bounds.west, bounds.north],
            ],
          ],
        },
      };
    }),
  };
}

/** 全タイルを覆う範囲。地図をこの範囲へ合わせる（splitがどこまで進んでいるかは
 * 「どの範囲か」でしか読めないため、初期表示で全体が入っている必要がある）。 */
export function boundsOf(tiles: RoadGraphTilesResponse["tiles"]): [[number, number], [number, number]] | null {
  if (tiles.length === 0) return null;
  let west = 180;
  let south = 90;
  let east = -180;
  let north = -90;
  for (const tile of tiles) {
    const b = tileBoundsLonLat(tile.zoom, tile.x, tile.y);
    west = Math.min(west, b.west);
    south = Math.min(south, b.south);
    east = Math.max(east, b.east);
    north = Math.max(north, b.north);
  }
  return [
    [west, south],
    [east, north],
  ];
}

// split済み範囲（road_graph_tiles）を地図で示す軽量な地図。ベースマップとタイル境界の面だけを
// 持ち、MapViewの機構（レイヤー群・レンズ・ルート線）は一切使わない——管理画面で見たいのは
// 「どこまで済んでいるか」だけで、ここに全部を持ち込むと重いだけになる。
// 塗られていない範囲は、初回のルート生成でsplitが走る＝冷パスになる。
export default function SplitCoverageMap() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [tiles, setTiles] = useState<RoadGraphTilesResponse["tiles"] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getRoadGraphTiles()
      .then((result) => {
        if (!cancelled) setTiles(result.tiles);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!containerRef.current || tiles === null || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: mapStyleUrl(),
      center: [139.7, 35.7],
      zoom: 7,
      attributionControl: false,
    });
    mapRef.current = map;
    map.on("load", () => {
      map.addSource(SOURCE_ID, { type: "geojson", data: tilesToGeojson(tiles) });
      map.addLayer({
        id: FILL_LAYER_ID,
        type: "fill",
        source: SOURCE_ID,
        paint: { "fill-color": "#22c55e", "fill-opacity": 0.25 },
      });
      map.addLayer({
        id: LINE_LAYER_ID,
        type: "line",
        source: SOURCE_ID,
        paint: { "line-color": "#22c55e", "line-width": 1 },
      });
      const bounds = boundsOf(tiles);
      if (bounds) map.fitBounds(bounds, { padding: 24, animate: false });
    });
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [tiles]);

  if (error) return <p className={styles.error}>split済み範囲の取得に失敗: {error}</p>;
  if (tiles === null) return <p className={styles.hint}>読み込み中…</p>;
  if (tiles.length === 0) return <p className={styles.hint}>split済みの範囲がまだ無い（全域が冷パスになる）</p>;

  return (
    <>
      <div ref={containerRef} className={styles.map} />
      <p className={styles.hint}>
        塗られた範囲がsplit済み（{tiles.length.toLocaleString("ja-JP")}タイル）。
        塗られていない範囲は、初回のルート生成でsplitが走るため時間がかかる。
      </p>
    </>
  );
}
