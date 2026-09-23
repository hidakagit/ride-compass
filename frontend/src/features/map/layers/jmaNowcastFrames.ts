// 気象庁ナウキャスト系（bosai/jmatile/data/nowc/配下、降水・雷/竜巻）に共通する
// 時刻一覧の取得・整形。JMAのタイムスタンプ形式
// （YYYYMMDDHHmmss）・「実況フレームは現在より前を切り捨てる」というトリミング方針は
// bosai/nowc APIファミリー全体の性質であり降水固有の判断ではないため、変更理由が同じもの
// として共通化する。要素ごとの時刻一覧の在り処（系統とファイル名）は源泉の宣言が持つ。

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
 * 時刻一覧（`targetTimes*.json`）・雷放電位置データ（GeoJSON）は、タイル本体と違って
 * アプリ自身の`fetch()`で読む。**タイルURLは時刻一覧が返るまで確定しない**ため、ここで
 * フロントのホスティングを経由すると往復1つぶんが初回表示のクリティカルパスへ直列に
 * 乗る。タイルと同じ`tileBaseUrl()`（本番ではbackendのオリジン）を使って避ける。
 *
 * `tileBaseUrl()`は`window`を参照するため、モジュール読み込み時の定数ではなく
 * 呼び出し時に評価する関数として提供する（SSRで空文字に固定されるのを避ける）。
 */
function jmaProxyUrl(path: string): string {
  return `${tileBaseUrl()}${JMA_TILE_BASE_URL}${path}`;
}

type DeclaredElement = (typeof mapDisplay.weatherElements)[number];

/** 配信元から取る要素の宣言。要素id・パスの系統・時刻一覧のファイルは源泉が持つ。 */
type DeliveredElement = Extract<DeclaredElement, { readonly jmaElements: readonly [unknown, ...unknown[]] }>;

/** 時刻の段1つぶんの配信要素。 */
type JmaDelivery = DeliveredElement["jmaElements"][number];

type JmaPathGroup = JmaDelivery["pathGroup"];

type SourceKey<E> = E extends { readonly group: infer G extends string; readonly source: infer S extends string }
  ? `${G}/${S}`
  : never;

/** 配信元から取る要素の鍵（チップ/名前付きソース）。生成物から導くため、源泉から要素が消えれば
 * それを名指す呼び出し側の型検査が落ちる。 */
export type JmaElementKey = SourceKey<DeliveredElement>;

/** 配信元のタイルで描く要素の鍵。 */
type JmaTileElementKey = SourceKey<Extract<DeliveredElement, { readonly kind: "rasterTile" | "vectorTile" }>>;

/** 鍵に対応する源泉の宣言。 */
function declaredJmaElement(key: JmaElementKey): DeliveredElement {
  const found = mapDisplay.weatherElements.find(
    (element): element is DeliveredElement =>
      element.jmaElements.length > 0 && `${element.group}/${element.source}` === key,
  );
  if (found === undefined) throw new Error(`配信元の要素が源泉に宣言されていない: ${key}`);
  return found;
}

/** 鍵の、時刻の段`stage`（源泉の並び。近い時刻から0, 1, …）の配信要素。1つの名前付きソースが、
 * 選んだ時刻によって別の配信要素から届くことがある。 */
export function jmaDelivery(key: JmaElementKey, stage = 0): JmaDelivery {
  const delivery = declaredJmaElement(key).jmaElements[stage];
  if (delivery === undefined) throw new Error(`時刻の段が源泉に宣言されていない: ${key} 段${stage}`);
  return delivery;
}

/** 配信元はベクタで描く要素をMapbox Vector Tile（.pbf）、それ以外を画像（.png）で配る。 */
function tileExtension(kind: DeliveredElement["kind"]): "png" | "pbf" {
  return kind === "vectorTile" ? "pbf" : "png";
}

/** 配信元のタイルのフレームを決める時刻と系列。 */
interface JmaTileTime {
  basetime: string;
  /** risk/rasrfはエントリ自身が持つ値、nowcは常に"none"。 */
  member: string;
  validtime: string;
}

/** 配信元のタイルで描く要素の、そのフレームの描画ペイロード。要素id・系統・描き方（拡張子）は源泉の宣言から引く。
 * `stage`はフレームが属する時刻の段（`jmaDelivery`）。 */
export function jmaTilePayload(key: JmaTileElementKey, time: JmaTileTime, stage = 0): DynamicWeatherRenderPayload {
  const element = declaredJmaElement(key);
  if (element.kind !== "rasterTile" && element.kind !== "vectorTile") {
    throw new Error(`タイルで描かない要素のタイルを求めた: ${key}`);
  }
  const delivery = jmaDelivery(key, stage);
  const tileUrlTemplate = jmaTileUrlTemplate({
    group: delivery.pathGroup,
    element: delivery.id,
    basetime: time.basetime,
    member: time.member,
    validtime: time.validtime,
    extension: tileExtension(element.kind),
  });
  return { kind: element.kind, tileUrlTemplate };
}

/** 配信元のタイルパスが持つ可変部分。 */
interface JmaTileTarget {
  /** 配信系統。`targetTimes.json`の在り処もこれで決まる。 */
  group: JmaPathGroup;
  /** 要素id（`land`・`rain_mesh`・`hrpns`・`thns`等）。 */
  element: string;
  basetime: string;
  /** risk/rasrfはエントリ自身が持つ値、nowcは常に"none"。 */
  member: string;
  validtime: string;
  /** 洪水キキクルのみベクタタイル。 */
  extension?: "png" | "pbf";
}

/** ソース初期化時の仮URLに使う、実在しない時刻。 */
const PLACEHOLDER_TIME = "00000000000000";

/**
 * JMAタイルのURLテンプレート（`{z}/{x}/{y}`を含む絶対URL）。
 *
 * `.../data/<group>/<basetime>/<member>/<validtime>/surf/<element>/{z}/{x}/{y}.<ext>`という
 * **配信元のパス構造を表す唯一の場所**。呼び出し側は系統と要素だけを渡す——構造を各所で
 * 組み立てると、要素を1つ足すたびに同じ並びを書き写すことになる。
 */
export function jmaTileUrlTemplate(target: JmaTileTarget): string {
  const extension = target.extension ?? "png";
  return jmaElementUrl(target, `{z}/{x}/{y}.${extension}`);
}

/**
 * 配信元の要素配下URL。`suffix`はタイル座標（`{z}/{x}/{y}.png`）とGeoJSON
 * （`data.geojson?id=...`）で異なるが、そこまでのパス構造は共通のためここで組み立てる。
 */
export function jmaElementUrl(target: Omit<JmaTileTarget, "extension">, suffix: string): string {
  return jmaProxyUrl(
    `/jmatile/data/${target.group}/${target.basetime}/${target.member}/${target.validtime}` +
      `/surf/${target.element}/${suffix}`,
  );
}

/**
 * ソースを作るときの仮のURL（`features/map/scene/groups/weather.ts`）。
 *
 * 実データが来る前にsourceを作るための仮の値で、中身が届くと本物のURLへ差し替わる。
 * 時刻部分は実在しない値のため、万一このまま要求されても配信元で404になる。
 */
export function jmaPlaceholderTileUrl(element: Pick<DeliveredElement, "jmaElements" | "kind">): string {
  const [first] = element.jmaElements;
  return jmaTileUrlTemplate({
    group: first.pathGroup,
    element: first.id,
    basetime: PLACEHOLDER_TIME,
    member: "none",
    validtime: PLACEHOLDER_TIME,
    extension: tileExtension(element.kind),
  });
}

export interface JmaNowcastFrame {
  basetime: string;
  validtime: string;
  /** true: 予測フレーム（validtime > basetime）。false: 実況（validtime === basetime）。 */
  isForecast: boolean;
}

interface RawJmaTargetTime {
  basetime: string;
  validtime: string;
  /** このエントリが実際にカバーする要素id（例: "thns"=雷ナウキャスト、"trns"=竜巻発生確度
   * ナウキャスト、"liden"=雷放電位置データ）。降水ナウキャスト（N1/N2）は1エントリ1要素
   * 固定のため使わないが、雷・竜巻（N3）は5分おきのエントリの一部が"liden"のみ（雷放電
   * 位置データのみ、雷ナウキャスト自体は10分おきにしか更新されないため）で、その回だけ
   * thns/trnsのタイルが存在しない（5分ズレのbasetimeを使うと雷ナウキャストタイルが
   * 404になる）。thunderNowcast.ts側で、この配列にthns/trnsが含まれるエントリだけへ
   * 絞り込むために使う。 */
  elements?: string[];
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

/** 配信要素の時刻一覧（`targetTimes*.json`）を取得する。在り処（系統とファイル名）は源泉の宣言が持ち、
 * ここは`.../data/<系統>/<ファイル>`というパス構造だけを知る（タイル本体の`jmaTileUrlTemplate`と対）。
 * `label`はエラーメッセージに使う対象名（例: 「降水ナウキャスト」。「の時刻一覧」は本関数が付ける）。
 *
 * 行の形は系統ごとに違う（nowcはmemberを持たない、risk/rasrfはmember必須等）ため、
 * 呼び出し側が期待する行型を型引数で指定する——検証するのは「配列であること」までで、
 * 個々のフィールドの解釈は呼び出し側の責務。
 *
 * 時刻一覧が複数のファイルに分かれる要素（降水ナウキャストの実況と予測）は、全ファイルの行を
 * 宣言の順につなげて返す。一部のファイルだけ取れなくても残りで部分的な時系列を返し、
 * 全部取れなかったときだけ最初の失敗を投げる。
 *
 * 共通のfetchJson（lib/fetchJson.ts、通信エラー・HTTPエラー・解析エラーを全て
 * debugLogへ記録する）経由にすることで、fetch()自体の失敗（タイムアウト・通信エラー）が
 * どこにもログされない穴を防ぐ。 */
export async function fetchJmaTargetTimes<T = RawJmaTargetTime>(delivery: JmaDelivery, label: string): Promise<T[]> {
  const results = await Promise.allSettled(
    delivery.targetTimeFiles.map((file) => fetchTargetTimesFile(`/jmatile/data/${delivery.pathGroup}/${file}`, label)),
  );
  const fulfilled = results.filter((result) => result.status === "fulfilled");
  if (fulfilled.length === 0) {
    const [firstFailure] = results;
    throw firstFailure?.status === "rejected" ? firstFailure.reason : new Error(`${label}の時刻一覧が宣言されていない`);
  }
  return fulfilled.flatMap((result) => result.value) as T[];
}

/** 実況の最新フレーム（＝「現在」に最も近い実況値）のindex。実況フレームが1件も無ければ
 * 切り捨てるべき「過去」のフレーム自体が存在しないため、先頭(0)を返し全フレームを残す
 * （末尾[frames.length - 1]を返すと、実況0件時に最も未来の1フレームだけを残して残り
 * 全部を切り捨ててしまい、降水/雷/竜巻ナウキャストが実質空になる）。 */
function latestObservedFrameIndex(frames: readonly JmaNowcastFrame[]): number {
  for (let i = frames.length - 1; i >= 0; i--) {
    if (!frames[i].isForecast) return i;
  }
  return 0;
}

/** 実況フレームは現在時刻より前（過去〜現在）ぶんを多く含む。サイクリング向けアプリの
 * 性質上過去を振り返る用途は無いため、「現在」より前のフレームをすべて切り捨て、
 * スライダーの左端（index 0）が常に「現在」になるようにする。 */
export function trimToCurrentAndFuture<T extends JmaNowcastFrame>(frames: readonly T[]): T[] {
  if (frames.length === 0) return [];
  return frames.slice(latestObservedFrameIndex(frames));
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
