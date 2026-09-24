// 気象庁の配信（bosai/jmatile/data/配下）から取る段の共通部品。配信元のパス構造・時刻一覧の
// 取得・時刻一覧の行をコマにする読み方・コマのタイルや地点のURL。どの配信要素を・どの系統の・
// どのファイルから・どう読むかは源泉の宣言（`mapDisplay.weatherElements`の`jmaElements`）が持ち、
// ここは宣言を受け取って組み立てるだけ。

import { fetchJson } from "@/lib/fetchJson";
import { tileBaseUrl } from "@/lib/tileBaseUrl";
import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";
import { mapDisplay } from "@/types/generated/mapDisplay";
import type { DynamicWeatherRenderPayload } from "@/features/map/layers/dynamicWeather";

// JMA bosaiタイル系（時刻一覧JSON・ラスタタイルPNG）の共通ベースURL。
// バックエンドのプロキシ＋キャッシュ（backend/app/infrastructure/jma_tile_client.py、
// `GET /api/jma-tile/{path}`）経由にすることで、JMAの非公式内部APIへの直接アクセスを
// 避けつつ配信する。
const JMA_TILE_BASE_URL = "/api/jma-tile/bosai";

/**
 * JMAプロキシ配下のパスを、タイル本体と同じ配信オリジンの絶対URLにする。
 *
 * 時刻一覧（`targetTimes*.json`）・地点のGeoJSONは、タイル本体と違ってアプリ自身の`fetch()`で
 * 読む。**タイルURLは時刻一覧が返るまで確定しない**ため、ここでフロントのホスティングを経由すると
 * 往復1つぶんが初回表示のクリティカルパスへ直列に乗る。タイルと同じ`tileBaseUrl()`（本番では
 * backendのオリジン）を使って避ける。
 *
 * `tileBaseUrl()`は`window`を参照するため、モジュール読み込み時の定数ではなく
 * 呼び出し時に評価する関数として提供する（SSRで空文字に固定されるのを避ける）。
 */
function jmaProxyUrl(path: string): string {
  return `${tileBaseUrl()}${JMA_TILE_BASE_URL}${path}`;
}

type DeclaredElement = (typeof mapDisplay.weatherElements)[number];

/** 時刻の段1つぶんの配信要素（要素id・パスの系統・時刻一覧のファイル・読み方・更新間隔）。 */
export type JmaDelivery = DeclaredElement["jmaElements"][number];

type JmaPathGroup = JmaDelivery["pathGroup"];

/** 配信元のタイルで描く描き方。 */
type JmaTileKind = "rasterTile" | "vectorTile";

/** 時刻一覧から読み出したコマ1つ。タイル・地点のURLを決める時刻と系列。 */
export interface JmaFrame {
  basetime: string;
  /** 数値予報の系列。系列を持たない系統（nowc）は常に"none"。 */
  member: string;
  validtime: string;
}

/** 配信元はベクタで描く要素をMapbox Vector Tile（.pbf）、それ以外を画像（.png）で配る。 */
function tileExtension(kind: DeclaredElement["kind"]): "png" | "pbf" {
  return kind === "vectorTile" ? "pbf" : "png";
}

/** 配信元のパスが持つ可変部分。 */
interface JmaTarget {
  /** 配信系統。`targetTimes.json`の在り処もこれで決まる。 */
  group: JmaPathGroup;
  /** 要素id（`land`・`rain_mesh`・`hrpns`・`thns`等）。 */
  element: string;
  basetime: string;
  member: string;
  validtime: string;
}

/**
 * 配信元の要素配下URL。`suffix`はタイル座標（`{z}/{x}/{y}.png`）とGeoJSON
 * （`data.geojson?id=...`）で異なるが、そこまでのパス構造は共通のためここで組み立てる。
 *
 * `.../data/<group>/<basetime>/<member>/<validtime>/surf/<element>/`という**配信元のパス構造を
 * 表す唯一の場所**——構造を各所で組み立てると、要素を1つ足すたびに同じ並びを書き写すことになる。
 */
function jmaElementUrl(target: JmaTarget, suffix: string): string {
  return jmaProxyUrl(
    `/jmatile/data/${target.group}/${target.basetime}/${target.member}/${target.validtime}` +
      `/surf/${target.element}/${suffix}`,
  );
}

function jmaTarget(delivery: JmaDelivery, frame: JmaFrame): JmaTarget {
  return {
    group: delivery.pathGroup,
    element: delivery.id,
    basetime: frame.basetime,
    member: frame.member,
    validtime: frame.validtime,
  };
}

/** 配信元のタイルで描く段の、そのコマの描画ペイロード。 */
export function jmaTilePayload(kind: JmaTileKind, delivery: JmaDelivery, frame: JmaFrame): DynamicWeatherRenderPayload {
  return {
    kind,
    tileUrlTemplate: jmaElementUrl(jmaTarget(delivery, frame), `{z}/{x}/{y}.${tileExtension(kind)}`),
  };
}

/** ソース初期化時の仮URLに使う、実在しない時刻。 */
const PLACEHOLDER_TIME = "00000000000000";

/**
 * ソースを作るときの仮のURL（`features/map/scene/groups/weather.ts`）。
 *
 * 実データが来る前にsourceを作るための仮の値で、中身が届くと本物のURLへ差し替わる。
 * 時刻部分は実在しない値のため、万一このまま要求されても配信元で404になる。
 */
export function jmaPlaceholderTileUrl(element: Pick<DeclaredElement, "jmaElements" | "kind">): string {
  const [first] = element.jmaElements;
  if (first === undefined) throw new Error("配信元から取らない要素のタイルのURLを求めた");
  return jmaElementUrl(
    jmaTarget(first, { basetime: PLACEHOLDER_TIME, member: "none", validtime: PLACEHOLDER_TIME }),
    `{z}/{x}/{y}.${tileExtension(element.kind)}`,
  );
}

/** 配信元が地点をGeoJSONで配る段の記号の大きさを決めるプロパティ。配信元は地点ごとの強弱を
 * 持たないため、gridMarkのicon-size式が必須で参照するこのプロパティへ固定値を入れる。描き方の宣言
 * （`features/map/scene/groups/weather.ts`）もこの定数を参照する。 */
export const JMA_POINT_VALUE_PROPERTY = "value";

/** そのコマの地点（落雷の位置等）。 */
export async function fetchJmaPointGeojson(
  delivery: JmaDelivery,
  frame: JmaFrame,
  label: string,
): Promise<GeoJSON.FeatureCollection> {
  const geojson = await fetchJson<GeoJSON.FeatureCollection>(
    jmaElementUrl(jmaTarget(delivery, frame), `data.geojson?id=${delivery.id}`),
    { timeoutMs: DEFAULT_API_TIMEOUT_MS, category: "api:jma-points", errorLabel: label },
  );
  return {
    ...geojson,
    features: geojson.features.map((feature) => ({
      ...feature,
      properties: { ...feature.properties, [JMA_POINT_VALUE_PROPERTY]: 1 },
    })),
  };
}

/** 時刻一覧の1行。 */
interface RawTargetTime {
  basetime: string;
  validtime: string;
  /** 系列（risk・rasrf）。nowcの行は持たない。 */
  member?: string;
  /** この行のタイルがある要素id。1つのファイルに複数の要素が載り、要素ごとに更新間隔が
   * 違う——雷・竜巻（N3）は5分おきの行の一部が落雷（"liden"）だけを持ち、その回は
   * 雷ナウキャストのタイルが無い（取りに行くと404）。 */
  elements: string[];
}

// 未解決のフェッチだけを時刻一覧のパスごとに共有する（useAxisCatalog.tsのinFlightCatalogFetchと
// 同じ重複排除。解決したら即座に捨てる）。
const inFlightTargetTimes = new Map<string, Promise<unknown[]>>();

/** 時刻一覧のファイル1つを取得する。同じパスを同時に取りに行く呼び出し元（降水短時間予報と
 * 線状降水帯予測マップ、キキクルの各要素等）は、未解決のフェッチを共有して往復を1回に畳む。
 * 解決後はキャッシュしない——時刻一覧は数分で更新され、古い値を返すと表示が止まる。
 * エラー文言に載る`label`は先に呼んだ側のものになる（同じURLの同じ失敗を指すため実害はない）。
 * **共有の登録は同期的に済ませる**——同じ瞬間に並べて呼んだ側が、先の登録を見られるように。 */
function fetchTargetTimesFile(path: string, label: string): Promise<unknown[]> {
  const existing = inFlightTargetTimes.get(path);
  if (existing) return existing;

  const request = (async () => {
    const data = await fetchJson<unknown>(jmaProxyUrl(path), {
      timeoutMs: DEFAULT_API_TIMEOUT_MS,
      category: "api:jma-nowcast-times",
      errorLabel: `${label}の時刻一覧`,
    });
    if (!Array.isArray(data)) throw new Error(`${label}の時刻一覧の形式が想定と異なります`);
    return data as unknown[];
  })();
  inFlightTargetTimes.set(path, request);
  void request.then(
    () => inFlightTargetTimes.delete(path),
    () => inFlightTargetTimes.delete(path),
  );
  return request;
}

/** 配信要素の時刻一覧（`targetTimes*.json`）の行。在り処（系統とファイル名）は源泉の宣言が持ち、
 * ここは`.../data/<系統>/<ファイル>`というパス構造だけを知る。`label`はエラーメッセージに使う
 * 対象名（「の時刻一覧」は本関数が付ける）。
 *
 * 時刻一覧が複数のファイルに分かれる要素（降水ナウキャストの実況と予測）は、全ファイルの行を
 * 宣言の順につなげて返す。一部のファイルだけ取れなくても残りで部分的な時系列を返し、
 * 全部取れなかったときだけ最初の失敗を投げる。 */
async function fetchJmaTargetTimes(delivery: JmaDelivery, label: string): Promise<RawTargetTime[]> {
  const results = await Promise.allSettled(
    delivery.targetTimeFiles.map((file) => fetchTargetTimesFile(`/jmatile/data/${delivery.pathGroup}/${file}`, label)),
  );
  const fulfilled = results.filter((result) => result.status === "fulfilled");
  if (fulfilled.length === 0) {
    const [firstFailure] = results;
    throw firstFailure?.status === "rejected" ? firstFailure.reason : new Error(`${label}の時刻一覧が宣言されていない`);
  }
  return fulfilled.flatMap((result) => result.value) as RawTargetTime[];
}

function toFrame(row: RawTargetTime): JmaFrame {
  return { basetime: row.basetime, member: row.member ?? "none", validtime: row.validtime };
}

function byValidtime(a: JmaFrame, b: JmaFrame): number {
  return a.validtime.localeCompare(b.validtime);
}

/** 実況＋予測。その要素の行を時刻順に並べ、最新の実況（validtime===basetime）より前を捨てる
 * ——過去を振り返る用途は無く、左端が「今」になる。実況が1つも無ければ何も捨てない（最も未来の
 * 1コマだけを残すと、実況が欠けた回に要素が実質空になる）。 */
function readNowcast(rows: readonly RawTargetTime[], elementId: string): JmaFrame[] {
  const frames = rows
    .filter((row) => row.elements.includes(elementId))
    .map(toFrame)
    .sort(byValidtime);
  let latestObserved = 0;
  frames.forEach((frame, index) => {
    if (frame.validtime === frame.basetime) latestObserved = index;
  });
  return frames.slice(latestObserved);
}

/** 数値予報のラン。系列（`member`）ごとに、有効時刻を複数持つ最新のラン（完全な予報）だけを使う
 * ——同じ系列の中にも、10分おきの中間ランが返す単発の有効時刻（basetime===validtime）が混ざり、
 * それを最新として拾うと1コマしか得られない。同じファイルに別の要素（線状降水帯予測）の行も混ざる
 * ため、数える前にその要素の行へ絞る。系列どうしは有効時刻の範囲が重ならない設計だが、重なれば
 * 新しいランを採る。 */
function readLatestFullRun(rows: readonly RawTargetTime[], elementId: string): JmaFrame[] {
  const entries = rows.filter((row) => row.elements.includes(elementId)).map(toFrame);
  const byTime = new Map<string, JmaFrame>();
  for (const member of new Set(entries.map((frame) => frame.member))) {
    const ofMember = entries.filter((frame) => frame.member === member);
    const validtimes = new Map<string, Set<string>>();
    for (const frame of ofMember) {
      if (!validtimes.has(frame.basetime)) validtimes.set(frame.basetime, new Set());
      validtimes.get(frame.basetime)!.add(frame.validtime);
    }
    const latest = [...validtimes.entries()]
      .filter(([, times]) => times.size > 1)
      .map(([basetime]) => basetime)
      .sort()
      .at(-1);
    for (const frame of ofMember) {
      if (frame.basetime !== latest) continue;
      const taken = byTime.get(frame.validtime);
      if (taken === undefined || taken.basetime < frame.basetime) byTime.set(frame.validtime, frame);
    }
  }
  return [...byTime.values()].sort(byValidtime);
}

/** 配信元が統合済みの「現在」の単一値。その要素の最新の行だけを1コマにする。 */
function readLatest(rows: readonly RawTargetTime[], elementId: string): JmaFrame[] {
  const entries = rows.filter((row) => row.elements.includes(elementId));
  const latest = [...entries].sort((a, b) => b.basetime.localeCompare(a.basetime))[0];
  return latest ? [toFrame(latest)] : [];
}

const READERS: Record<JmaDelivery["reader"], (rows: readonly RawTargetTime[], elementId: string) => JmaFrame[]> = {
  nowcast: readNowcast,
  latestFullRun: readLatestFullRun,
  latest: readLatest,
};

/** 段のコマ（時刻順）。時刻一覧の読み方は源泉の宣言が決める。 */
export async function fetchJmaFrames(delivery: JmaDelivery, label: string): Promise<JmaFrame[]> {
  return READERS[delivery.reader](await fetchJmaTargetTimes(delivery, label), delivery.id);
}

/** "YYYYMMDDHHmmss"（UTC）形式のvalidtime → Date。 */
export function parseValidtime(validtime: string): Date {
  const y = validtime.slice(0, 4);
  const mo = validtime.slice(4, 6);
  const d = validtime.slice(6, 8);
  const h = validtime.slice(8, 10);
  const mi = validtime.slice(10, 12);
  const s = validtime.slice(12, 14);
  return new Date(`${y}-${mo}-${d}T${h}:${mi}:${s}Z`);
}
