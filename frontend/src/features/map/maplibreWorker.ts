/** maplibre-glのWorkerの場所を、静的配信した複製へ向ける。
 *
 * これを呼ばずに地図を作ると、バンドラが解決できないURLをWorkerが読み込み、
 * スタイル処理とタイル取得が永久に止まる（`isStyleLoaded()`がtrueにならない）。
 * 複製は`scripts/copy-maplibre-worker.mjs`がビルド前に置く。
 */
import { setWorkerUrl } from "maplibre-gl";

const MAPLIBRE_WORKER_URL = "/maplibre/maplibre-gl-worker.mjs";

let applied = false;

export function configureMaplibreWorker(): void {
  if (applied) return;
  applied = true;
  setWorkerUrl(MAPLIBRE_WORKER_URL);
}
