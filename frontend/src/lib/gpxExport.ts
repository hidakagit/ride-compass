import type { RouteCandidate } from "@/types/route";

// Suuntoアプリは1000点を超えるGPXの取り込みで問題が起きることがある
// （長い周回・目的地ルートのOSM道なり形状は数千点になりうる）。GarminはGarmin Connect側で
// 取り込み時に自動間引きするため直接の上限は無いが、経路の視覚的な形状はある程度の間引きで
// 実用上損なわれない密度（数十m間隔）を持つため、両方に安全な同じ閾値で揃える。
export const MAX_GPX_TRACK_POINTS = 1000;

// 間引きで元の折れ線からずれてよい距離（m）。読み込んだ側のナビが描く線として、この程度の
// ずれは道の形として見分けられない。上限点数に収まらない場合はこの値を倍にして再試行する。
const SIMPLIFY_TOLERANCE_M = 3;

const METERS_PER_DEGREE_LATITUDE = 111_320;

type PlanePoint = { x: number; y: number };

/** 緯度経度を、座標列の中央緯度を基準にした局所平面（m）へ落とす。緯度経度のまま距離を
 * 測ると経度方向が実際より長くなり（日本では約1.2倍）、東西の曲がりだけが残りやすくなる。 */
function toLocalPlane(coordinates: readonly GeoJSON.Position[]): PlanePoint[] {
  const lonScale = Math.cos((coordinates[Math.floor(coordinates.length / 2)][1] * Math.PI) / 180);
  return coordinates.map(([lon, lat]) => ({
    x: lon * METERS_PER_DEGREE_LATITUDE * lonScale,
    y: lat * METERS_PER_DEGREE_LATITUDE,
  }));
}

/** 点`p`と線分`a`-`b`の距離（m）。`a`と`b`が同じ点なら点どうしの距離。 */
function distanceToSegment(p: PlanePoint, a: PlanePoint, b: PlanePoint): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return Math.hypot(p.x - a.x, p.y - a.y);
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lengthSquared));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

/** Ramer–Douglas–Peucker。両端を結んだ線分から`toleranceM`より離れる点を残し、その点で
 * 区間を割って同じ判定を繰り返す。残った点だけを結べば元の折れ線との差は`toleranceM`以内に
 * 収まる。深い再帰を避けるため明示的なスタックで回す。 */
function markKeptPoints(points: readonly PlanePoint[], toleranceM: number): boolean[] {
  const kept = new Array<boolean>(points.length).fill(false);
  kept[0] = true;
  kept[points.length - 1] = true;
  const pending: Array<[number, number]> = [[0, points.length - 1]];
  while (pending.length > 0) {
    const [first, last] = pending.pop()!;
    let farthest = -1;
    let maxDistance = toleranceM;
    for (let i = first + 1; i < last; i += 1) {
      const distance = distanceToSegment(points[i], points[first], points[last]);
      if (distance > maxDistance) {
        maxDistance = distance;
        farthest = i;
      }
    }
    if (farthest < 0) continue;
    kept[farthest] = true;
    pending.push([first, farthest], [farthest, last]);
  }
  return kept;
}

/** 座標列を`maxPoints`以下へ間引く。残す点は折れ線の形から選ぶ（両端を結んだ線分からのずれが
 * 大きい点を残す）ため、残る点の間隔より短い区間に収まった曲がりも直線へ潰れない。
 * `maxPoints`以下ならそのまま返す。 */
export function simplifyCoordinates(
  coordinates: readonly GeoJSON.Position[],
  maxPoints: number = MAX_GPX_TRACK_POINTS
): GeoJSON.Position[] {
  if (coordinates.length <= maxPoints) return [...coordinates];
  const points = toLocalPlane(coordinates);
  // 両端は常に残るため、許容するずれを増やし続ければ2点まで減らせる（＝必ず収まる）。
  const limit = Math.max(2, maxPoints);
  let tolerance = SIMPLIFY_TOLERANCE_M;
  let kept = markKeptPoints(points, tolerance);
  while (kept.filter(Boolean).length > limit) {
    tolerance *= 2;
    kept = markKeptPoints(points, tolerance);
  }
  return coordinates.filter((_, index) => kept[index]);
}

function escapeXmlText(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** Garminは`<rte>`（ルート点）を「コース」としてのみ取り込め、`<trk>`（トラック点）は
 * 「コース」「アクティビティ」の両方に取り込める。Suuntoアプリは`<trk>`以外
 * （`<rte>`・単独の`<wpt>`）を取り込めない。両対応のため`<trk>`固定にする。標高・時刻は
 * RouteCandidateが点単位で持たないため含めない（候補全体の集約値のみ）。 */
export function buildGpxDocument(candidate: RouteCandidate): string {
  const coordinates = simplifyCoordinates(candidate.geometry.coordinates);
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
