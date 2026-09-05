import type { RouteCandidate } from "@/types/route";

// Suuntoアプリは1000点を超えるGPXの取り込みで問題が起きることがある
// （長い周回・目的地ルートのOSM道なり形状は数千点になりうる）。GarminはGarmin Connect側で
// 取り込み時に自動間引きするため直接の上限は無いが、経路の視覚的な形状はある程度の間引きで
// 実用上損なわれない密度（数十m間隔）を持つため、両方に安全な同じ閾値で揃える。
export const MAX_GPX_TRACK_POINTS = 1000;

/** 座標列を先頭・末尾を残したまま等間隔に間引く。maxPoints以下ならそのまま返す。 */
export function decimateCoordinates(
  coordinates: readonly GeoJSON.Position[],
  maxPoints: number = MAX_GPX_TRACK_POINTS
): GeoJSON.Position[] {
  if (coordinates.length <= maxPoints) return [...coordinates];
  const stride = Math.ceil(coordinates.length / maxPoints);
  const result: GeoJSON.Position[] = [];
  for (let i = 0; i < coordinates.length; i += stride) {
    result.push(coordinates[i]);
  }
  const last = coordinates[coordinates.length - 1];
  if (result[result.length - 1] !== last) result.push(last);
  return result;
}

function escapeXmlText(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** Garminは`<rte>`（ルート点）を「コース」としてのみ取り込め、`<trk>`（トラック点）は
 * 「コース」「アクティビティ」の両方に取り込める。Suuntoアプリは`<trk>`以外
 * （`<rte>`・単独の`<wpt>`）を取り込めない。両対応のため`<trk>`固定にする。標高・時刻は
 * RouteCandidateが点単位で持たないため含めない（候補全体の集約値のみ）。 */
export function buildGpxDocument(candidate: RouteCandidate): string {
  const coordinates = decimateCoordinates(candidate.geometry.coordinates);
  const name = escapeXmlText(`RideCompass ${candidate.direction_label} ${candidate.distance_km.toFixed(1)}km`);
  const trackPoints = coordinates
    .map(([lon, lat]) => `      <trkpt lat="${lat}" lon="${lon}"/>`)
    .join("\n");
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<gpx version="1.1" creator="RideCompass" xmlns="http://www.topografix.com/GPX/1/1">',
    "  <trk>",
    `    <name>${name}</name>`,
    "    <trkseg>",
    trackPoints,
    "    </trkseg>",
    "  </trk>",
    "</gpx>",
    "",
  ].join("\n");
}

/** ブラウザへGPXファイルのダウンロードを発火する（Blob + Object URL、リポジトリ初のクライアント
 * サイドファイルダウンロード）。 */
export function downloadGpx(candidate: RouteCandidate): void {
  const xml = buildGpxDocument(candidate);
  const blob = new Blob([xml], { type: "application/gpx+xml" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `ridecompass-${candidate.id}.gpx`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
