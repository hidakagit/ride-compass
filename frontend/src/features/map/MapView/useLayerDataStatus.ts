// レイヤーごとのデータ取得状態（loading/empty/error）の算出と追跡。
import { useCallback, useMemo, useRef, type RefObject } from "react";
import type { LayerDataStatusByLayer, MapLayerId } from "@/features/map/layers/mapLayers";

export interface LayerDataSourceEntry {
  key: MapLayerId;
  sourceId: string;
  sourceLayer?: string;
}

// computeLayerDataStatusが必要とするMapインスタンスの最小限の形（構造的部分型のため、
// 実際のMapLibreMapをそのまま渡せる）。
interface DataStatusMapLike {
  getSource(id: string): unknown;
  isSourceLoaded(id: string): boolean;
  querySourceFeatures(id: string, options: { sourceLayer: string }): unknown[];
}

// 表示ON中のレイヤーだけを対象に、(source, source-layer)ごとの現在状態から
// loading/empty/errorを判定する純粋関数。判定順序: エラー中 > 未読込(loading) > 読込済みだが0件(empty)。
// 正常時（既知件数のデータが描画できている状態）はキー自体を持たない。
function computeLayerDataStatus(
  map: DataStatusMapLike,
  erroredSourceIds: ReadonlySet<string>,
  visibility: Partial<Record<MapLayerId, boolean>>,
  layerDataSources: readonly LayerDataSourceEntry[],
): LayerDataStatusByLayer {
  const status: LayerDataStatusByLayer = {};
  // 複数レイヤーが同じ(sourceId, sourceLayer)を共有する。querySourceFeaturesは実タイルの地物を走査して軽くなく、
  // この関数はsourcedata等の高頻度イベントのたびに呼ばれるので、同じ引数の結果をこの1回の呼び出しの中で使い回す。
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

// erroredSourceIdsは「次の取得サイクル開始（sourcedataloading）まで保持」する設計だが、
// 失敗した地点から一度も再取得が発生しない別の地点（既にタイルがキャッシュ済みの地点）へ
// 移動した場合、sourcedataloading自体が発火しないためエラー状態が解除される機会が永久に
// 来ず「取得失敗」が誤って残り続けてしまう。パン/ズームが収束した時点（moveend/zoomend）
// でも、保留中の取得が無い（isSourceLoaded=true）sourceは「このビューポートでは問題が
// 無い」とみなしてエラーを解除する。
//
// 重要: 呼び出し元はmoveend/zoomend（ビューポートが実際に変わった時点）に限定し、"idle"から
// 呼んではいけない。MapLibreのisSourceLoaded()は、タイルが'errored'（取得失敗のまま再試行
// されていない）状態でも「保留中の要求が無い」という理由でtrueを返す（'errored'を'loaded'と
// 同列に「settled」とみなすため）。ビューポートが変わっていない"idle"でこれを解除条件に使うと、
// 今まさに進行中の障害（例: バックエンド停止で該当タイルがずっとerrored状態のまま）を
// 「もう問題ない」と誤って解除してしまい、"取得失敗"表示が"データなし"に化けてしまう。
// moveend/zoomendは定義上ビューポートが実際に変わった時にしか発火しないため、そこでのisSourceLoaded()=trueは
// 「新しいビューポートのタイルは問題なく決着した」という意味を持てるが、同じ判定を"idle"だけに
// 基づいて行うことはできない。
function clearStaleTrackedSourceErrors(map: DataStatusMapLike, erroredSourceIds: Set<string>): boolean {
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
  /** 現在の表示ON/OFFフラグを都度読む（refを直接渡さず、呼び出し側で安定した関数として
   * 包む）。 */
  getVisibility: () => Partial<Record<MapLayerId, boolean>>;
  /** 状態が変わったときだけ呼ぶ（安定した関数で渡す）。 */
  onChange: (status: LayerDataStatusByLayer) => void;
}

// 地図のイベントの登録は呼び出し元が持ち、各イベントの受け手の中でこのフックが返す関数を呼ぶ。
export function useLayerDataStatus({ mapRef, layerDataSources, getVisibility, onChange }: UseLayerDataStatusArgs) {
  const erroredSourceIdsRef = useRef<Set<string>>(new Set());
  const lastStatusRef = useRef<LayerDataStatusByLayer>({});
  const trackedSourceIds = useMemo(() => new Set(layerDataSources.map((entry) => entry.sourceId)), [layerDataSources]);

  // 値が変わらなければonChangeを呼ばない（呼び出し元の再描画を起こさない）。
  const recompute = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const status = computeLayerDataStatus(map, erroredSourceIdsRef.current, getVisibility(), layerDataSources);
    if (layerDataStatusEqual(status, lastStatusRef.current)) return;
    lastStatusRef.current = status;
    onChange(status);
  }, [mapRef, getVisibility, onChange, layerDataSources]);

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

  // moveend/zoomend用。"idle"からは呼ばない（進行中の障害の"取得失敗"を解いてしまう）。
  const settleViewport = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    if (clearStaleTrackedSourceErrors(map, erroredSourceIdsRef.current)) recompute();
  }, [mapRef, recompute]);

  return { recompute, markSourceErrored, clearSourceLoading, notifySourceData, settleViewport };
}
