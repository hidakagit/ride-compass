import type { Coordinates } from "@/types/route";

const EARTH_RADIUS_KM = 6371;

/** 2点間の大円距離（km）。 */
export function haversineKm(a: Coordinates, b: Coordinates): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(b.latitude - a.latitude);
  const dLon = toRad(b.longitude - a.longitude);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.latitude)) * Math.cos(toRad(b.latitude)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(h));
}

/** 座標列（GeoJSONの[lon, lat]）の総延長（km）。 */
export function polylineLengthKm(coordinates: readonly GeoJSON.Position[]): number {
  let total = 0;
  for (let i = 1; i < coordinates.length; i += 1) {
    total += haversineKm(
      { latitude: coordinates[i - 1][1], longitude: coordinates[i - 1][0] },
      { latitude: coordinates[i][1], longitude: coordinates[i][0] },
    );
  }
  return total;
}

/** 座標列の各点までの累積距離（km）。`[0, ...]`で座標と同じ長さ。 */
export function cumulativeDistancesKm(coordinates: readonly GeoJSON.Position[]): number[] {
  const cumulative = [0];
  for (let i = 1; i < coordinates.length; i += 1) {
    cumulative.push(
      cumulative[i - 1] +
        haversineKm(
          { latitude: coordinates[i - 1][1], longitude: coordinates[i - 1][0] },
          { latitude: coordinates[i][1], longitude: coordinates[i][0] },
        ),
    );
  }
  return cumulative;
}
