// レイヤーごとのデータ取得状態（loading/empty/error、改善計画T87）の算出・追跡。
// MapView.tsxに直接埋め込まれていた純粋関数（computeLayerDataStatus・
// clearStaleTrackedSourceErrors）とそれを使う状態管理・イベント配線（erroredSourceIdsRef・
// recomputeLayerDataStatus）を1つのカスタムフックへ抽出した（改善計画T123、
// 2026-08-17レビューDEFER(a)の事前合意の履行）。
//
// MapView.tsxとの循環import回避のため、対象レイヤーの(source, source-layer)対応表
// （MapView.tsx: LAYER_DATA_SOURCES）はこのモジュールが持たず、呼び出し側から引数で渡す
// （このモジュール自体はMapView.tsxを一切importしない）。
import { useCallback, useMemo, useRef, type RefObject } from "react";
import type { LayerDataStatusByLayer, MapLayerId } from "@/components/Map/mapLayers";

export interface LayerDataSourceEntry {
  key: MapLayerId;
  sourceId: string;
  sourceLayer?: string;
}

// computeLayerDataStatusが必要とするMapインスタンスの最小限の形（構造的部分型のため、
// 実際のMapLibreMapをそのまま渡せる。テストでは最小限のフェイクだけを用意すればよい）。
export interface DataStatusMapLike {
  getSource(id: string): unknown;
  isSourceLoaded(id: string): boolean;
  querySourceFeatures(id: string, options: { sourceLayer: string }): unknown[];
}

// 表示ON中のレイヤーだけを対象に、(source, source-layer)ごとの現在状態から
// loading/empty/errorを判定する純粋関数（MapView.segments.test.tsと同じ考え方でテスト可能に
// エクスポートしている）。判定順序: エラー中 > 未読込(loading) > 読込済みだが0件(empty)。
// 正常時（既知件数のデータが描画できている状態）はキー自体を持たない。
export function computeLayerDataStatus(
  map: DataStatusMapLike,
  erroredSourceIds: ReadonlySet<string>,
  visibility: Partial<Record<MapLayerId, boolean>>,
  layerDataSources: readonly LayerDataSourceEntry[],
): LayerDataStatusByLayer {
  const status: LayerDataStatusByLayer = {};
  // road/carStress/designationのように複数レイヤーが同じ(sourceId,
  // sourceLayer)を共有するため、querySourceFeatures（実タイルのフィーチャーを走査する
  // 軽くない処理）を同じ引数で繰り返し呼ばないよう、この1回の呼び出し内でだけ結果を
  // メモ化する（レビュー指摘: road_surfaceは実測6,273件、共有4レイヤー分で素朴には
  // 4倍呼ばれていた。この関数はsourcedata等の高頻度イベントのたびに呼ばれるため無視できない）。
  const emptyBySourceLayer = new Map<string, boolean>();
  for (const { key, sourceId, sourceLayer } of layerDataSources) {
    if (!visibility[key]) continue;
    if (!map.getSource(sourceId)) continue;
    if (erroredSourceIds.has(sourceId)) {
      status[key] = "error";
      continue;
    }
    if (!map.isSourceLoaded(sourceId)) {
      status[key] = "loading";
      continue;
    }
    if (!sourceLayer) continue;
    const cacheKey = `${sourceId} ${sourceLayer}`;
    let isEmpty = emptyBySourceLayer.get(cacheKey);
    if (isEmpty === undefined) {
      isEmpty = map.querySourceFeatures(sourceId, { sourceLayer }).length === 0;
      emptyBySourceLayer.set(cacheKey, isEmpty);
    }
    if (isEmpty) status[key] = "empty";
  }
  return status;
}

function layerDataStatusEqual(a: LayerDataStatusByLayer, b: LayerDataStatusByLayer): boolean {
  const aKeys = Object.keys(a) as MapLayerId[];
  const bKeys = Object.keys(b) as MapLayerId[];
  if (aKeys.length !== bKeys.length) return false;
  return aKeys.every((key) => a[key] === b[key]);
}

// T87実機確認で判明した不具合の対策: erroredSourceIdsは「次の取得サイクル開始
// （sourcedataloading）まで保持」する設計だが、失敗した地点から一度も再取得が発生しない
// 別の地点（既にタイルがキャッシュ済みの地点）へ移動した場合、sourcedataloading自体が
// 発火しないためエラー状態が解除される機会が永久に来ず「取得失敗」が誤って残り続けた
// （バックエンド停止→別地点でエラー発生→バックエンド復旧→キャッシュ済みの元の地点へ戻っても
// 「取得失敗」表示のまま、という形で実機確認時に再現）。パン/ズームが収束した時点
// （moveend/zoomend）でも、保留中の取得が無い（isSourceLoaded=true）sourceは
// 「このビューポートでは問題が無い」とみなしてエラーを解除する。
//
// 重要: 呼び出し元はmoveend/zoomend（ビューポートが実際に変わった時点）に限定し、"idle"から
// 呼んではいけない。MapLibreのisSourceLoaded()は、タイルが'errored'（取得失敗のまま再試行
// されていない）状態でも「保留中の要求が無い」という理由でtrueを返す（'errored'を'loaded'と
// 同列に「settled」とみなすため）。ビューポートが変わっていない"idle"でこれを解除条件に使うと、
// 今まさに進行中の障害（例: バックエンド停止で該当タイルがずっとerrored状態のまま）を
// 「もう問題ない」と誤って解除してしまい、"取得失敗"表示が"データなし"に化けてしまう
// （レビューで発見・修正、useLayerDataStatusのsettleViewport参照）。moveend/zoomendは
// 定義上ビューポートが実際に変わった時にしか発火しないため、そこでのisSourceLoaded()=trueは
// 「新しいビューポートのタイルは問題なく決着した」という意味を持てるが、同じ判定を"idle"だけに
// 基づいて行うことはできない。
export function clearStaleTrackedSourceErrors(map: DataStatusMapLike, erroredSourceIds: Set<string>): boolean {
  let changed = false;
  for (const sourceId of erroredSourceIds) {
    if (map.isSourceLoaded(sourceId)) {
      erroredSourceIds.delete(sourceId);
      changed = true;
    }
  }
  return changed;
}

interface UseLayerDataStatusArgs {
  mapRef: RefObject<DataStatusMapLike | null>;
  layerDataSources: readonly LayerDataSourceEntry[];
  /** 現在の表示ON/OFFフラグを都度読む（redrawPropsRef.current等、refを直接渡さず
   * 呼び出し側で安定した関数として包む）。 */
  getVisibility: () => Partial<Record<MapLayerId, boolean>>;
  onChangeRef: RefObject<(status: LayerDataStatusByLayer) => void>;
}

// T87: レイヤーデータ状態（loading/empty/error）の状態管理・再計算・イベント配線をまとめて
// 持つフック。呼び出し元（MapView.tsx）はmap.on("error"/"sourcedata"/"sourcedataloading"/
// "moveend"/"zoomend"/"idle", ...)自体は自分で登録し（他の関心事のハンドラと同じ
// 巨大useEffect内に既にあるため、登録自体を切り離すとかえって複雑になる）、各ハンドラの中で
// このフックが返す関数を呼ぶだけにする。
export function useLayerDataStatus({ mapRef, layerDataSources, getVisibility, onChangeRef }: UseLayerDataStatusArgs) {
  const erroredSourceIdsRef = useRef<Set<string>>(new Set());
  const lastStatusRef = useRef<LayerDataStatusByLayer>({});
  const trackedSourceIds = useMemo(() => new Set(layerDataSources.map((entry) => entry.sourceId)), [layerDataSources]);

  // 呼び出し元は複数（tracked sourceのsourcedata/sourcedataloading/errorイベント、
  // moveend/zoomend、表示ON/OFFが変わるeffect）だが、算出そのものはcomputeLayerDataStatus
  // （純粋関数）に閉じているため、ここでは「今のmap・エラー集合・表示状態を渡して呼ぶ」だけ。
  // 値が変わらなければコールバックを呼ばない（呼び出し元のuseState更新→再レンダーを
  // 無駄に発生させないため）。
  const recompute = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const status = computeLayerDataStatus(map, erroredSourceIdsRef.current, getVisibility(), layerDataSources);
    if (layerDataStatusEqual(status, lastStatusRef.current)) return;
    lastStatusRef.current = status;
    onChangeRef.current(status);
  }, [mapRef, getVisibility, onChangeRef, layerDataSources]);

  // 'error'イベント用。追跡対象外のsourceId（ルート系・ハロー等）は無視する。
  const markSourceErrored = useCallback(
    (sourceId: string) => {
      if (!trackedSourceIds.has(sourceId)) return;
      erroredSourceIdsRef.current.add(sourceId);
      recompute();
    },
    [trackedSourceIds, recompute],
  );

  // 'sourcedataloading'（新しい取得サイクルの開始）用。直前のエラー状態をクリアする。
  const clearSourceLoading = useCallback(
    (sourceId: string) => {
      if (!trackedSourceIds.has(sourceId)) return;
      erroredSourceIdsRef.current.delete(sourceId);
      recompute();
    },
    [trackedSourceIds, recompute],
  );

  // 'sourcedata'（取得の進行・完了）用。
  const notifySourceData = useCallback(
    (sourceId: string) => {
      if (!trackedSourceIds.has(sourceId)) return;
      recompute();
    },
    [trackedSourceIds, recompute],
  );

  // moveend/zoomend用。clearStaleTrackedSourceErrorsのdocstring参照（"idle"から呼んでは
  // いけない理由）。
  const settleViewport = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    if (clearStaleTrackedSourceErrors(map, erroredSourceIdsRef.current)) recompute();
  }, [mapRef, recompute]);

  return { recompute, markSourceErrored, clearSourceLoading, notifySourceData, settleViewport };
}
