// JMA動的タイルの在否インデックス（backend `GET /api/jma-tile-index`）の解釈。
//
// JMA動的タイルは疎で、平常時はほぼ全てのタイルが空である。インデックスに載っていない
// タイルは取りに行かない（`jmaTileProtocol.ts`がMapLibreのタイル要求を横取りして
// 透明タイルを返す）ことで、平常時のリクエストをほぼゼロにする。
//
// **取りこぼしより空振りを選ぶ**: 判断がつかない場合（インデックス未取得・世代が違う・
// 網羅範囲外・URLを解釈できない）は必ず「取りに行く」へ倒す。誤って省くと危険情報が
// 地図から消えるため、省けるのは「空だと確認済み」の場合だけに限る。

/** backendの応答そのまま。`available: false`ならインデックス無し（従来どおり全取得）。 */
export interface JmaTileIndexResponse {
  available: boolean;
  coverage?: {
    min_longitude: number;
    min_latitude: number;
    max_longitude: number;
    max_latitude: number;
  };
  elements?: Record<
    string,
    {
      basetime: string | null;
      validtime: string | null;
      member: string;
      /** ズーム（文字列）→ 中身のあるタイル座標 [x, y] の一覧。 */
      zooms: Record<string, [number, number][]>;
    }
  >;
}

/** 判定用に前処理した形。座標の線形探索を避けるためSetへ展開しておく。 */
export interface JmaTileIndexLookup {
  coverage: NonNullable<JmaTileIndexResponse["coverage"]>;
  /** 要素id → { その要素のbasetime, "z/x/y"のSet } */
  elements: Map<string, { basetime: string; present: Set<string> }>;
}

/** タイルURLから読み取った、在否判定に必要な情報。 */
export interface JmaTileRef {
  element: string;
  basetime: string;
  z: number;
  x: number;
  y: number;
}

// .../data/{group}/{basetime}/{member}/{validtime}/surf/{element}/{z}/{x}/{y}.{png|pbf}
const TILE_URL_PATTERN =
  /\/data\/[a-z]+\/(\d{14})\/[^/]+\/\d{14}\/surf\/([a-z0-9_]+)\/(\d+)\/(\d+)\/(\d+)\.(?:png|pbf)/;

export function parseJmaTileUrl(url: string): JmaTileRef | null {
  const match = TILE_URL_PATTERN.exec(url);
  if (!match) return null;
  return {
    basetime: match[1],
    element: match[2],
    z: Number(match[3]),
    x: Number(match[4]),
    y: Number(match[5]),
  };
}

export function buildJmaTileIndexLookup(response: JmaTileIndexResponse | null): JmaTileIndexLookup | null {
  if (!response?.available || !response.coverage || !response.elements) return null;
  const elements = new Map<string, { basetime: string; present: Set<string> }>();
  for (const [elementId, entry] of Object.entries(response.elements)) {
    // basetimeが無い要素は世代を照合できない＝インデックスを信用できないので載せない
    // （その要素は従来どおり全タイルを取りに行く）。
    if (!entry.basetime) continue;
    const present = new Set<string>();
    for (const [zoom, coords] of Object.entries(entry.zooms ?? {})) {
      for (const [x, y] of coords) present.add(`${zoom}/${x}/${y}`);
    }
    elements.set(elementId, { basetime: entry.basetime, present });
  }
  return elements.size > 0 ? { coverage: response.coverage, elements } : null;
}

/** タイル(z,x,y)の地理範囲がcoverageと交差するか（Webメルカトル）。 */
function intersectsCoverage(ref: JmaTileRef, coverage: JmaTileIndexLookup["coverage"]): boolean {
  const n = 2 ** ref.z;
  const west = (ref.x / n) * 360 - 180;
  const east = ((ref.x + 1) / n) * 360 - 180;
  const latOf = (tileY: number) => {
    const t = Math.PI * (1 - (2 * tileY) / n);
    return (Math.atan(Math.sinh(t)) * 180) / Math.PI;
  };
  const north = latOf(ref.y);
  const south = latOf(ref.y + 1);
  return (
    west < coverage.max_longitude &&
    east > coverage.min_longitude &&
    south < coverage.max_latitude &&
    north > coverage.min_latitude
  );
}

/**
 * そのタイルが「空だと確認済み」か。trueのときだけ取得を省いてよい。
 *
 * 次のいずれかに当てはまる場合はfalse（＝取りに行く）:
 * インデックス未取得／URLを解釈できない／その要素がインデックスに無い／
 * インデックスの世代（basetime）が要求と違う／インデックスの網羅範囲外。
 */
export function isKnownEmptyTile(lookup: JmaTileIndexLookup | null, url: string): boolean {
  if (!lookup) return false;
  const ref = parseJmaTileUrl(url);
  if (!ref) return false;
  const entry = lookup.elements.get(ref.element);
  if (!entry) return false;
  if (entry.basetime !== ref.basetime) return false;
  if (!intersectsCoverage(ref, lookup.coverage)) return false;
  return !entry.present.has(`${ref.z}/${ref.x}/${ref.y}`);
}
