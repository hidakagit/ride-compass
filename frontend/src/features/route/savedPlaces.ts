import { vocabulary } from "@/types/generated/vocabulary";
import type { Coordinates, PlaceCandidate } from "@/types/route";

/** 名前を付けて保存した地点。探して置いた候補と同じ形で持ち、選ぶと候補を選んだのと同じく置く（名前は保存のときに付けたもの）。 */
export type SavedPlace = PlaceCandidate;

// 受け付ける種類と段はbackendの語彙（生成物）から読む——手で並べると、backendが足した段の地点を読み直しで捨てる。
const KINDS: ReadonlySet<unknown> = new Set(vocabulary.placeKinds.map(({ key }) => key));
const LEVELS: ReadonlySet<unknown> = new Set(vocabulary.placeMatchLevels.map(({ key }) => key));

// 1件を読む。今の画面が受け付けない件はnull（ほかの件は残す）。
function readSavedPlace(value: unknown): SavedPlace | null {
  if (typeof value !== "object" || value === null) return null;
  const { kind, level, name, area, latitude, longitude } = value as Record<string, unknown>;
  if (!KINDS.has(kind) || !LEVELS.has(level)) return null;
  if (typeof name !== "string" || name.trim() === "") return null;
  if (area !== null && typeof area !== "string") return null;
  if (typeof latitude !== "number" || !Number.isFinite(latitude)) return null;
  if (typeof longitude !== "number" || !Number.isFinite(longitude)) return null;
  return { kind, level, name, area, latitude, longitude } as SavedPlace;
}

/** 保存した地点の一覧を読む。壊れた保存値は空の一覧、読めない件はその件だけを捨てる。 */
export function readSavedPlaces(raw: string): SavedPlace[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  return parsed.map(readSavedPlace).filter((place): place is SavedPlace => place !== null);
}

/** 保存した地点のうち、位置`at`にあるもの。 */
export function savedPlaceAt(list: SavedPlace[], at: Coordinates): SavedPlace | null {
  return list.find((place) => place.latitude === at.latitude && place.longitude === at.longitude) ?? null;
}

/** 一覧へ1件を入れる。同じ名前・同じ位置の件は置き換え、入れた件を先頭に置く（最近保存したものほど上）。 */
export function withSavedPlace(list: SavedPlace[], place: SavedPlace): SavedPlace[] {
  return [place, ...list.filter((saved) => saved.name !== place.name && savedPlaceAt([saved], place) === null)];
}

/** 打った文字を名前に含む地点（空なら全部）。 */
export function savedPlacesMatching(list: SavedPlace[], text: string): SavedPlace[] {
  const needle = text.trim().toLowerCase();
  return needle === "" ? list : list.filter((place) => place.name.toLowerCase().includes(needle));
}
