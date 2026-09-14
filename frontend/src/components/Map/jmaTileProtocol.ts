// JMA動的タイルの要求をMapLibreから横取りし、在否インデックス（`jmaTileIndex.ts`）で
// 「空だと確認済み」のタイルはネットワークへ出さずに透明タイルを返すカスタムプロトコル。
//
// MapLibreのソース設定は連続したズーム区間しか表現できず「このタイルは空」を伝える手段が
// 無いため、タイルURLのスキームを`jmatile://`にして`maplibregl.addProtocol`で受ける。
// ハンドラは実URL（`jmatile://`を剥がしたもの）へfetchするか、透明タイルを返すかだけを
// 決め、それ以外の挙動（キャッシュ・再試行）はMapLibreと通常のHTTPに委ねる。

import maplibregl from "maplibre-gl";

import { debugLog } from "@/lib/debugLog";

import { parseJmaTileElement } from "@/components/Map/jmaNowcastFrames";
import {
  buildJmaTileIndexLookup,
  isKnownEmptyTile,
  type JmaTileIndexLookup,
  type JmaTileIndexResponse,
} from "@/components/Map/jmaTileIndex";

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
  return TRANSPARENT_PNG.slice();
}
/** 空タイルの中身を**呼ぶたびに作り直して**返す（ベクタは0バイトのMVTが「地物なし」）。
 *
 * MapLibreはタイルのデータをWorkerへtransferして渡すため、一度返したArrayBufferは
 * detachedになる。同じインスタンスを使い回すと2回目以降のpostMessageが
 * "An ArrayBuffer is detached and could not be cloned"で失敗し、そのタイルが描画されない。 */
function emptyTileBytes(realUrl: string): Uint8Array {
  return realUrl.endsWith(".pbf") ? new Uint8Array(0) : TRANSPARENT_PNG.slice();
}

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

/** そのタイルURLを「空と分かっている」として素通りさせるか。ハンドラが実際に使う判定で、
 * **いま保持しているインデックス**を見る。差し替えが効いているかはこれを通してしか
 * 確かめられない（有効かどうかだけを見ると、古いインデックスを握り続けても気づけない）。 */
export function isKnownEmptyTileUrl(realUrl: string): boolean {
  return isKnownEmptyTile(lookup, realUrl);
}

// 配信の障害で返せなかったタイルは空タイルで代替するため、MapLibreのソースイベントにも
// 地図の見た目にも何も現れない。「平常時は透明」が正常系のレイヤー（キキクル等）では
// 危険度ゼロと見分けられないため、失敗を要素ごとに保持して購読側（動的気象レイヤーの
// データ取得状態）へ渡す。
//
// 値は失敗したタイルの要素配下URL（basetime・validtimeを含む）。購読側はいま描画している
// フレームのURLと突き合わせるため、フレームが進めば古い失敗は自然に無視される。
let tileFailures: ReadonlyMap<string, string> = new Map();
const failureListeners = new Set<() => void>();

/** 失敗中の要素id→要素配下URL。参照は変更時にだけ差し替わる（useSyncExternalStoreの
 * スナップショットとして使うため、同じ内容なら同じ参照を返す必要がある）。 */
export function jmaTileFailures(): ReadonlyMap<string, string> {
  return tileFailures;
}

export function subscribeJmaTileFailures(listener: () => void): () => void {
  failureListeners.add(listener);
  return () => {
    failureListeners.delete(listener);
  };
}

/** テスト用。失敗の記録を空へ戻す。 */
export function resetJmaTileFailures(): void {
  if (tileFailures.size === 0) return;
  publishFailures(new Map());
}

function publishFailures(next: ReadonlyMap<string, string>): void {
  tileFailures = next;
  for (const listener of failureListeners) listener();
}

function markDeliveryFailed(realUrl: string): void {
  const ref = parseJmaTileElement(realUrl);
  if (!ref || tileFailures.get(ref.element) === ref.prefix) return;
  const next = new Map(tileFailures);
  next.set(ref.element, ref.prefix);
  publishFailures(next);
}

/** 配信元が応答した（中身の有無は問わない）。疎な格子状タイルの404もここに当たる——
 * 空であることを配信元が答えているため、その要素の配信は生きている。 */
function markDeliveryHealthy(realUrl: string): void {
  const ref = parseJmaTileElement(realUrl);
  if (!ref || !tileFailures.has(ref.element)) return;
  const next = new Map(tileFailures);
  next.delete(ref.element);
  publishFailures(next);
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
  if (isKnownEmptyTileUrl(realUrl)) {
    // ネットワークへ出さない。ベクタとラスタで空の表現が違うため拡張子で分ける。
    return { data: emptyTileBytes(realUrl) };
  }
  let response: Response;
  try {
    response = await fetch(realUrl, { signal: abortController.signal });
  } catch (error) {
    // 中断（パン・ズームでMapLibreが要求を取り消す）は障害ではない。到達できないことは
    // 5xxと同じく配信の失敗として記録し、例外はそのままMapLibreへ返す。
    if (!(error instanceof DOMException && error.name === "AbortError")) markDeliveryFailed(realUrl);
    throw error;
  }
  if (!response.ok) {
    // どの失敗も空タイルとして返す。MapLibreは失敗タイルを再試行しないため、ここで例外に
    // すると以後その位置が永久に空白になる。ただし**404と5xxは意味が違う**——疎な格子状
    // タイルで404は正常系だが、5xxは配信の障害で、キキクルのように「平常時は透明」が
    // 正常系のレイヤーでは利用者が危険度ゼロと誤読しうる。区別して記録する。
    if (response.status !== 404) {
      debugLog(
        "weather",
        "JMAタイルの取得に失敗しました（空タイルで代替）",
        {
          url: realUrl,
          status: response.status,
        },
        "warn",
      );
      markDeliveryFailed(realUrl);
    } else {
      markDeliveryHealthy(realUrl);
    }
    return { data: emptyTileBytes(realUrl) };
  }
  markDeliveryHealthy(realUrl);
  return { data: await response.arrayBuffer() };
}

/** MapLibreへプロトコルを登録する（多重登録は無害だが1回で足りる）。 */
export function registerJmaTileProtocol(): void {
  if (registered) return;
  maplibregl.addProtocol(JMA_TILE_PROTOCOL, handleJmaTileRequest);
  registered = true;
}
