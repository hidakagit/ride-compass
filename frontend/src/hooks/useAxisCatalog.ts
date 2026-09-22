"use client";

import { useEffect, useSyncExternalStore } from "react";
import { getAxisCatalog } from "@/services/axisCatalogApi";
import { setTileVersions } from "@/services/regionApi";
import { axisCatalogFromResponse, EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";

// page.tsxとRouteSettingsPanel.tsx（page.tsxの子として初回描画時からマウントされる）が
// 同時にこのフックを呼びうるため、同時に飛んでいる（未解決の）フェッチだけをこの
// モジュールレベル変数で共有し、解決/失敗したら即座にクリアする（解決後の結果を
// 永続キャッシュしない——軸スタジオでの公開操作を再デプロイなしに反映するため、
// 後続の別マウント[例: モバイルのBottomSheetでタブを開き直す]では改めて最新を取得する）。
let inFlightCatalogFetch: ReturnType<typeof getAxisCatalog> | null = null;

function fetchAxisCatalogDeduped(): ReturnType<typeof getAxisCatalog> {
  if (inFlightCatalogFetch) return inFlightCatalogFetch;
  const request = getAxisCatalog().finally(() => {
    if (inFlightCatalogFetch === request) inFlightCatalogFetch = null;
  });
  inFlightCatalogFetch = request;
  return request;
}

// 上記の「同時に飛んでいる場合」の重複排除だけでは、page.tsxが先にマウント・フェッチ
// 完了した後にRouteSettingsPanel.tsxが再マウント（モバイルのBottomSheetでタブを
// 開き直す等）してフェッチし直すケースを救えない。解決済みカタログをモジュールレベルの
// 単一ストアとして持ち、全呼び出し元がuseSyncExternalStoreで同じオブジェクト参照を
// 購読することで、2インスタンス間で`axes`配列が食い違うことは構造的に起こらない
// （どちらかのフェッチが解決すれば全呼び出し元へ即座に反映される）。
let sharedCatalog: AxisCatalog = EMPTY_CATALOG;
const catalogListeners = new Set<() => void>();

function publishCatalog(next: AxisCatalog): void {
  sharedCatalog = next;
  catalogListeners.forEach((listener) => listener());
}

function subscribeToCatalog(listener: () => void): () => void {
  catalogListeners.add(listener);
  return () => {
    catalogListeners.delete(listener);
  };
}

function getCatalogSnapshot(): AxisCatalog {
  return sharedCatalog;
}

function getCatalogServerSnapshot(): AxisCatalog {
  return EMPTY_CATALOG;
}

function loadAxisCatalog(): void {
  fetchAxisCatalogDeduped()
    .then((response) => {
      // 取得成功時はaxesが空でもそのままbuildCatalogへ渡す（フェッチ未完了・失敗時のみ
      // 静的フォールバックに留まる、という区別に一本化する——「まだ取得中/取得失敗」と
      // 「取得成功したが軸が0件（全軸非公開）」を同一視すると、軸スタジオで全軸を
      // 非公開にしても静的フォールバックの軸が表示され続けてしまう）。
      // タイル世代は地図のソースURLに入るため、カタログを公開する前に渡す
      // （`hasTileVersions()`がtrueになってから地図のレイヤーが作られる）。
      setTileVersions(response.tile_versions ?? {});
      publishCatalog(
        axisCatalogFromResponse(
          response.axes,
          response.material_runtime_scales ?? {},
          // 取れた値が空でも既定へ戻さない（宣言が1件も持たない状態と区別が付かないため、
          // 空なら空のまま渡す）。使う側は自分が要るidが無ければ既定を持たない。
          response.client_tuning ?? {},
          response.accident_years ?? [],
        ),
      );
    })
    .catch(() => {
      // 他の呼び出し元が既に取得済みの正常なカタログは、この呼び出し元だけの失敗で
      // 巻き戻さない。まだ一度も成功していない場合だけ、失敗したことをUIへ見せられるよう
      // フラグを立てる（フェッチ自体の記録はfetchJsonがdebugLogへ済ませている）。
      if (!sharedCatalog.loaded && !sharedCatalog.failed) {
        publishCatalog({ ...sharedCatalog, failed: true });
      }
    });
}

/** 軸カタログの取得をやり直す（`failed`状態からの明示的な再試行導線用）。
 * 既に成功していれば何もしない。再取得中は`failed`を下ろし、UIが「取得中」へ戻る。 */
export function retryAxisCatalogFetch(): void {
  if (sharedCatalog.loaded) return;
  publishCatalog({ ...sharedCatalog, failed: false });
  loadAxisCatalog();
}

/** 軸カタログ。マウント時に一度`GET /api/axis-catalog`を取得し、軸スタジオがDBへ
 * 追加・公開した軸を反映する（is_publishedの切替も含め、再デプロイ不要で即座に
 * 反映される）。取得完了までとエラー時はビルド時点の静的カタログ（フォールバック）を
 * 返すため、呼び出し側は常に何かしらの一覧を受け取れる（loading状態を個別に扱う
 * 必要がない）。
 *
 * フォールバック中（`loaded=false`）の値を「軸スタジオの現在の公開軸集合」と取り違えて
 * 送信すると、実際の公開軸と食い違うroute_preferenceを送ってしまい422になりうる
 * （`page.tsx: handleGenerate`参照）。フォールバック値をUIの初期描画・地図レイヤーの初期状態
 * 用に使うことは問題ないが、APIへ送るペイロードの構築等「軸スタジオの現在の状態と一致して
 * いなければならない」処理では、必ず`loaded`を確認すること。このフックはaxis_idから
 * 観測/推定/動的カテゴリを引く手段を提供しない——backendのGET /api/axis-catalog
 * レスポンス自体には引き続き`category`フィールドが含まれる（他用途のため）が、
 * このフックはそれを消費しない。 */
export function useAxisCatalog(): AxisCatalog {
  useEffect(() => {
    loadAxisCatalog();
  }, []);

  return useSyncExternalStore(subscribeToCatalog, getCatalogSnapshot, getCatalogServerSnapshot);
}
