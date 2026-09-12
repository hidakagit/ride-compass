// JMA動的タイルの要求をMapLibreから横取りし、在否インデックス（`jmaTileIndex.ts`）で
// 「空だと確認済み」のタイルはネットワークへ出さずに透明タイルを返すカスタムプロトコル。
//
// MapLibreのソース設定は連続したズーム区間しか表現できず「このタイルは空」を伝える手段が
// 無いため、タイルURLのスキームを`jmatile://`にして`maplibregl.addProtocol`で受ける。
// ハンドラは実URL（`jmatile://`を剥がしたもの）へfetchするか、透明タイルを返すかだけを
// 決め、それ以外の挙動（キャッシュ・再試行）はMapLibreと通常のHTTPに委ねる。

import maplibregl from "maplibre-gl";

import { buildJmaTileIndexLookup, isKnownEmptyTile, type JmaTileIndexLookup, type JmaTileIndexResponse } from "@/components/Map/jmaTileIndex";

/** タイルURLへ付けるスキーム。`jmatile://https://host/...`の形になる。 */
const JMA_TILE_PROTOCOL = "jmatile";

/** 1x1の完全に透明なPNG（全チャネル0）。空と分かっているタイルの代わりに返す。
 *
 * MapLibreはこの1画素を`tileSize`ぶんへ引き伸ばすため、**不透明な画素が1つでも入ると
 * タイル全面がその色で塗られる**。空タイルは全ズーム・全座標で返るので、地図全体が
 * 塗り潰される。`jmaTileProtocol.test.ts`が画素を復号して不透明度0を検査する。 */
const TRANSPARENT_PNG = Uint8Array.from(
  atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII="),
  (c) => c.charCodeAt(0),
);

/** テスト用。空タイルとして返すPNGのバイト列。 */
export function emptyRasterTileBytes(): Uint8Array {
  return TRANSPARENT_PNG;
}
/** 空のMVT（ベクタタイルのソースへ返す用）。0バイトが「地物なし」を表す。 */
const EMPTY_MVT = new Uint8Array(0);

// ハンドラはMapLibre内部から都度呼ばれるため、インデックスはモジュールスコープに置く
// （Reactのstateを閉じ込めると古い値を握り続ける）。
let lookup: JmaTileIndexLookup | null = null;
let registered = false;

/** 在否インデックスを差し替える。取得できていない間はnullのままで、その間は素通しになる。 */
export function setJmaTileIndex(response: JmaTileIndexResponse | null): void {
  lookup = buildJmaTileIndexLookup(response);
}

/** テスト・デバッグ用。現在インデックスが有効かどうか。 */
export function hasJmaTileIndex(): boolean {
  return lookup !== null;
}

/** `jmatile://`を剥がして実URLへ戻す。 */
export function toRealUrl(url: string): string {
  return url.replace(new RegExp(`^${JMA_TILE_PROTOCOL}://`), "");
}

/** タイルURLへスキームを付ける（`DYNAMIC_WEATHER_RENDERERS`のテンプレートで使う）。 */
export function withJmaTileProtocol(url: string): string {
  return `${JMA_TILE_PROTOCOL}://${url}`;
}

async function handleJmaTileRequest(
  params: { url: string },
  abortController: AbortController,
): Promise<{ data: ArrayBuffer | Uint8Array }> {
  const realUrl = toRealUrl(params.url);
  if (isKnownEmptyTile(lookup, realUrl)) {
    // ネットワークへ出さない。ベクタとラスタで空の表現が違うため拡張子で分ける。
    return { data: realUrl.endsWith(".pbf") ? EMPTY_MVT : TRANSPARENT_PNG };
  }
  const response = await fetch(realUrl, { signal: abortController.signal });
  if (!response.ok) {
    // 404（疎な格子状タイルでは正常系）を含め、失敗は空タイルとして扱う。MapLibreは
    // 失敗タイルを再試行しないため、ここで例外にすると以後その位置が永久に空白になる。
    return { data: realUrl.endsWith(".pbf") ? EMPTY_MVT : TRANSPARENT_PNG };
  }
  return { data: await response.arrayBuffer() };
}

/** MapLibreへプロトコルを登録する（多重登録は無害だが1回で足りる）。 */
export function registerJmaTileProtocol(): void {
  if (registered) return;
  maplibregl.addProtocol(JMA_TILE_PROTOCOL, handleJmaTileRequest);
  registered = true;
}
