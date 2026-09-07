// 気象庁ナウキャスト系（bosai/jmatile/data/nowc/配下、降水・雷/竜巻）に共通する
// 時刻一覧の取得・整形。JMAのタイムスタンプ形式
// （YYYYMMDDHHmmss）・「実況フレームは現在より前を切り捨てる」というトリミング方針は
// bosai/nowc APIファミリー全体の性質であり降水固有の判断ではないため、変更理由が同じもの
// として共通化する（設計原則6）。降水・雷それぞれ固有のURL構造（降水はN1実況/N2予測の
// 2ファイル、雷/竜巻はN3の1ファイルに実況・予測が同居）は呼び出し元に残す。

import { fetchJson } from "@/lib/fetchJson";
import { tileBaseUrl } from "@/lib/tileBaseUrl";

// JMA bosaiタイル系（時刻一覧JSON・ラスタタイルPNG）の共通ベースURL。
// バックエンドのプロキシ＋キャッシュ（backend/app/infrastructure/jma_tile_client.py、
// `GET /api/jma-tile/{path}`）経由にすることで、JMAの非公式内部APIへの直接アクセスを
// 避けつつ配信する。
export const JMA_TILE_BASE_URL = "/api/jma-tile/bosai";

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
export function jmaProxyUrl(path: string): string {
  return `${tileBaseUrl()}${JMA_TILE_BASE_URL}${path}`;
}

/** 配信元のタイルパスが持つ可変部分。 */
export interface JmaTileTarget {
  /** 配信系統。`targetTimes.json`の在り処もこれで決まる。 */
  group: "risk" | "nowc" | "rasrf";
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
export function jmaElementUrl(
  target: Omit<JmaTileTarget, "extension">,
  suffix: string,
): string {
  return jmaProxyUrl(
    `/jmatile/data/${target.group}/${target.basetime}/${target.member}/${target.validtime}` +
      `/surf/${target.element}/${suffix}`,
  );
}

/**
 * ソース初期化時のプレースホルダURL（`MapView.tsx: DYNAMIC_WEATHER_RENDERERS`）。
 *
 * 実データが来る前にsourceを作るための仮の値で、`applyDynamicWeatherState`が本物のURLへ
 * 差し替える。時刻部分は実在しない値のため、万一このまま要求されても配信元で404になる。
 */
export function jmaPlaceholderTileUrl(
  group: JmaTileTarget["group"],
  element: string,
  extension?: JmaTileTarget["extension"],
): string {
  return jmaTileUrlTemplate({
    group,
    element,
    basetime: PLACEHOLDER_TIME,
    member: "none",
    validtime: PLACEHOLDER_TIME,
    extension,
  });
}

export interface JmaNowcastFrame {
  basetime: string;
  validtime: string;
  /** true: 予測フレーム（validtime > basetime）。false: 実況（validtime === basetime）。 */
  isForecast: boolean;
}

export interface RawJmaTargetTime {
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

/** 気象庁の時刻一覧JSON（targetTimes_*.json）を取得する。labelはエラーメッセージに使う
 * 対象名（例:「降水ナウキャスト」「雷ナウキャスト」）。
 *
 * 共通のfetchJson（lib/fetchJson.ts、通信エラー・HTTPエラー・解析エラーを全て
 * debugLogへ記録する）経由にすることで、fetch()自体の失敗（タイムアウト・通信エラー）が
 * どこにもログされない穴を防ぐ。 */
export async function fetchJmaTargetTimes(url: string, label: string): Promise<RawJmaTargetTime[]> {
  const data = await fetchJson<unknown>(url, {
    timeoutMs: 15000,
    category: "api:jma-nowcast-times",
    errorLabel: `${label}の時刻一覧`,
  });
  if (!Array.isArray(data)) throw new Error(`${label}の時刻一覧の形式が想定と異なります`);
  return data as RawJmaTargetTime[];
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
