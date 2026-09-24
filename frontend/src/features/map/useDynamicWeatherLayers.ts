"use client";

// 動的気象レイヤーの取得・選んだ時刻に描くコマ・地図へ渡す描画内容・チップの取得状態。
// **要素を名指さない**——何を・どこから・どう読み・どのコマを描くかは源泉の宣言
// （`weatherSources.ts: WEATHER_SOURCES`）が持ち、ここは表示中のソースをループして、段の種類
// （配信元のタイル・配信元の地点・自前の格子）ごとに1つずつの実装で描画内容を作る。
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { MapLayerVisibility } from "@/features/map/layers/mapLayers";
import { deriveFetchLayerStatus, type LayerDataStatus } from "@/features/map/layers/mapLayers";
import {
  fetchJmaFrames,
  fetchJmaPointGeojson,
  jmaTilePayload,
  type JmaDelivery,
  type JmaFrame,
} from "@/features/map/layers/jmaDelivery";
import {
  WEATHER_SOURCES,
  gridStageFrames,
  jmaStageFrames,
  selectFrame,
  sourceTimeline,
  type GridValue,
  type StageFrameRef,
  type WeatherSource,
} from "@/features/map/layers/weatherSources";
import { precipitationCells } from "@/features/map/layers/precipitationNowcast";
import { windArrows, type MapViewport } from "@/features/map/layers/windLayer";
import {
  tileDeliveryFailureLayerIds,
  type DynamicWeatherGroupState,
  type DynamicWeatherLayerId,
  type DynamicWeatherRenderPayload,
} from "@/features/map/layers/dynamicWeather";
import { jmaTileFailures, subscribeJmaTileFailures } from "@/features/map/layers/jmaTileProtocol";
import { useWeatherGrid } from "@/features/map/useWeatherGrid";
import { usePolledFetch } from "@/features/map/usePolledFetch";
import type { WindGridPoint } from "@/types/weather";

/** 格子の段の描き方。読む値ごとに1つ。 */
const GRID_PAYLOAD: Record<
  GridValue,
  (grid: readonly WindGridPoint[], index: number, spacingDeg: number) => DynamicWeatherRenderPayload
> = {
  precipitation: precipitationCells,
  wind: windArrows,
};

/** 配信要素ごとの時刻一覧の読み取り結果。 */
type DeliveryResult = { frames: readonly JmaFrame[]; error: null } | { frames: readonly JmaFrame[]; error: string };

const EMPTY_RESULTS: ReadonlyMap<string, DeliveryResult> = new Map();

/** ソースが読む配信要素（重複なし）と、取得の失敗を記録するときの呼び名（最初に読むソースの名前）。 */
function deliveriesOf(sources: readonly WeatherSource[]): { delivery: JmaDelivery; label: string }[] {
  const byId = new Map<string, { delivery: JmaDelivery; label: string }>();
  for (const source of sources) {
    for (const stage of source.stages) {
      if (stage.origin === "jma" && !byId.has(stage.delivery.id)) {
        byId.set(stage.delivery.id, { delivery: stage.delivery, label: source.label });
      }
    }
  }
  return [...byId.values()];
}

/** 配信元の段の、選んだコマの地点を取る鍵（要素配下のURLと同じく、配信要素と時刻で決まる）。 */
function pointKey(delivery: JmaDelivery, frame: JmaFrame): string {
  return `${delivery.id}/${frame.basetime}/${frame.member}/${frame.validtime}`;
}

interface UseDynamicWeatherLayersOptions {
  /** 全レイヤーの表示状態（`MapLayerId`→boolean）。**動的気象レイヤーを足してもこの境界は
   * 変わらない**（`MapView`が受け取る`look.layerVisibility`と同じ形、
   * docs/modules/frontend/static-map-layers.md「表示状態の渡し方」）。 */
  visibility: MapLayerVisibility;
  /** チップ配下で非表示に選ばれている名前付きソース（▶パネルの「表示する情報」）。面同士が重なると
   * 混色して危険度を読み取れないため、要素単位で間引けるようにしている。非表示のソースが読む配信は、
   * 同じ配信を読む表示中のソースが無ければ取りに行かない（「表示中のものだけ叩く」方針）。 */
  hiddenSources: Partial<Record<DynamicWeatherLayerId, readonly string[]>>;
  mapViewport: MapViewport | null;
  /** 表示する時刻（出発時刻）と、刻みへ丸めた現在時刻（`useDepartureTime`）。各ソースは
   * `at`に対して源泉の規則でコマを選ぶ（刻みはソースごとに違ってよい）。 */
  at: Date;
  now: Date;
}

interface UseDynamicWeatherLayersResult {
  /** MapViewへそのまま渡す動的気象レイヤーのプロパティ（チップ→名前付きソース→表示・中身）。 */
  dynamicWeather: Partial<Record<DynamicWeatherLayerId, DynamicWeatherGroupState>>;
  /** チップごとのデータ取得状態。MapLibreのソースイベント（`useLayerDataStatus.ts`）は経由しない
   * ——時刻一覧・格子・地点は自前のJSで取りに行き、結果を流し込むだけのため、MapLibre側の
   * ソースイベントはその待ち時間・失敗を観測できない。 */
  dynamicWeatherDataStatus: Partial<Record<DynamicWeatherLayerId, LayerDataStatus>>;
}

export function useDynamicWeatherLayers({
  visibility,
  hiddenSources,
  mapViewport,
  at,
  now,
}: UseDynamicWeatherLayersOptions): UseDynamicWeatherLayersResult {
  const isShown = useCallback(
    (source: WeatherSource) =>
      visibility[source.group] === true && !(hiddenSources[source.group] ?? []).includes(source.source),
    [visibility, hiddenSources],
  );
  const shownSources = useMemo(() => WEATHER_SOURCES.filter(isShown), [isShown]);

  // 表示中のソースが読む配信要素。同じ時刻一覧のファイルを読む要素どうしは、未解決の取得を
  // 共有して往復を1回に畳む（`jmaDelivery.ts`）。
  const deliveries = useMemo(() => deliveriesOf(shownSources), [shownSources]);
  const deliveryIds = deliveries.map(({ delivery }) => delivery.id).join(",");
  // 全部を1本で取り直す。間隔は表示中の配信のうち最も更新の速い系統に合わせる（遅い系統を
  // 早めに取り直すぶんには古い表示にならない）。
  const intervalMs = Math.min(...deliveries.map(({ delivery }) => delivery.refreshIntervalMs));
  const fetchDeliveries = useCallback(
    async (): Promise<ReadonlyMap<string, DeliveryResult>> => {
      const settled = await Promise.allSettled(
        deliveries.map(({ delivery, label }) => fetchJmaFrames(delivery, label)),
      );
      return new Map(
        deliveries.map(({ delivery, label }, index): [string, DeliveryResult] => {
          const result = settled[index];
          if (result.status === "fulfilled") return [delivery.id, { frames: result.value, error: null }];
          const message = result.reason instanceof Error ? result.reason.message : `${label}の取得に失敗しました`;
          return [delivery.id, { frames: [], error: message }];
        }),
      );
    },
    // 配信要素の組が変わったときだけ作り直す（表示状態の再計算のたびに取り直さない）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [deliveryIds],
  );
  const { data: deliveryResults } = usePolledFetch(fetchDeliveries, EMPTY_RESULTS, {
    enabled: deliveries.length > 0,
    intervalMs: Number.isFinite(intervalMs) ? intervalMs : 0,
    label: "気象庁の時刻一覧",
  });

  // 自前の格子（風と降水の延長予報が共有する1回の取得、`useWeatherGrid.ts`）。
  const usesGrid = shownSources.some((source) => source.stages.some((stage) => stage.origin === "grid"));
  const grid = useWeatherGrid(usesGrid, mapViewport);

  // ソースごとの時系列と、選んだ時刻に描くコマ。
  const selected = useMemo(() => {
    const bySource = new Map<WeatherSource, StageFrameRef | undefined>();
    for (const source of WEATHER_SOURCES) {
      const timeline = sourceTimeline(
        source.stages.map((stage, index) =>
          stage.origin === "grid"
            ? gridStageFrames(index, grid.grid)
            : jmaStageFrames(index, deliveryResults.get(stage.delivery.id)?.frames ?? []),
        ),
      );
      bySource.set(source, selectFrame(source.frameRule, timeline, at, now)?.ref);
    }
    return bySource;
  }, [deliveryResults, grid.grid, at, now]);

  // 配信元から取る記号の段（gridMark）は、配信元が地点をGeoJSONで配る。タイルで描く段は時刻一覧
  // だけでURLが決まるが、この段は選んだコマが変わるたびに中身を取る。取れた中身を鍵（配信要素と
  // 時刻）で持ち、選んでいるコマの鍵と一致するときだけ描く——コマを動かした後に前のコマの取得が
  // 解決しても、別の時刻の地点を混ぜない。
  const pointRequests = useMemo(() => {
    const requests: { key: string; delivery: JmaDelivery; frame: JmaFrame; label: string }[] = [];
    for (const source of shownSources) {
      const ref = selected.get(source);
      if (ref === undefined || !("frame" in ref)) continue;
      const stage = source.stages[ref.stage];
      if (stage.origin !== "jma" || stage.kind !== "gridMark") continue;
      requests.push({
        key: pointKey(stage.delivery, ref.frame),
        delivery: stage.delivery,
        frame: ref.frame,
        label: source.label,
      });
    }
    return requests;
  }, [shownSources, selected]);
  const pointRequestKeys = pointRequests.map((request) => request.key).join(",");
  const [points, setPoints] = useState<ReadonlyMap<string, GeoJSON.FeatureCollection>>(new Map());
  useEffect(() => {
    let cancelled = false;
    const wanted = new Set(pointRequests.map((request) => request.key));
    for (const request of pointRequests) {
      fetchJmaPointGeojson(request.delivery, request.frame, request.label)
        .then((geojson) => {
          if (cancelled) return;
          setPoints((previous) => new Map([...previous].filter(([key]) => wanted.has(key))).set(request.key, geojson));
        })
        .catch(() => {
          // 取れなければ描かないだけに留める（取得の失敗はfetchJsonがdebugLogへ記録済み）。
        });
    }
    return () => {
      cancelled = true;
    };
    // 取りに行く鍵の組が変わったときだけ取り直す。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pointRequestKeys]);

  const payloadOf = useCallback(
    (source: WeatherSource): DynamicWeatherRenderPayload | undefined => {
      const ref = selected.get(source);
      if (ref === undefined) return undefined;
      const stage = source.stages[ref.stage];
      if ("index" in ref) {
        if (stage.origin !== "grid") return undefined;
        return GRID_PAYLOAD[stage.value](grid.effectiveGrid, ref.index, grid.effectiveGridSpacingDeg);
      }
      if (stage.origin !== "jma") return undefined;
      if (stage.kind === "gridMark") {
        const geojson = points.get(pointKey(stage.delivery, ref.frame));
        return geojson && { kind: "gridMark", geojson };
      }
      if (stage.kind === "gridFill") return undefined;
      return jmaTilePayload(stage.kind, stage.delivery, ref.frame);
    },
    [selected, grid.effectiveGrid, grid.effectiveGridSpacingDeg, points],
  );

  const dynamicWeather = useMemo(() => {
    const groups: Partial<Record<DynamicWeatherLayerId, DynamicWeatherGroupState>> = {};
    for (const source of WEATHER_SOURCES) {
      const group = (groups[source.group] ??= {});
      group[source.source] = { visible: isShown(source), payload: payloadOf(source) };
    }
    return groups;
  }, [isShown, payloadOf]);

  // 配信元のタイルが返らない状態は、空タイルで代替するぶんフェッチ側のerrorに現れない
  // （`jmaTileProtocol.ts`）。表示中のフレームのURLと突き合わせて、そのタイルを出している
  // チップだけをエラーにする。
  const tileFailures = useSyncExternalStore(subscribeJmaTileFailures, jmaTileFailures, jmaTileFailures);

  // チップごとの取得状態。チップは複数の名前付きソースを束ねるため、表示中のソースのどれかが
  // 描けていれば空とせず、どれかの取得が失敗していれば失敗、どれかがまだ取れていなければ読み込み中。
  const dynamicWeatherDataStatus = useMemo(() => {
    const status: Partial<Record<DynamicWeatherLayerId, LayerDataStatus>> = {};
    const groups = new Set(WEATHER_SOURCES.map((source) => source.group));
    for (const group of groups) {
      const sources = shownSources.filter((source) => source.group === group);
      const results = deliveriesOf(sources).map(({ delivery }) => deliveryResults.get(delivery.id));
      const readsGrid = sources.some((source) => source.stages.some((stage) => stage.origin === "grid"));
      const loading = results.some((result) => result === undefined) || (readsGrid && grid.loading);
      const error = results.find((result) => result?.error)?.error ?? (readsGrid ? grid.error : null);
      const hasFetched = results.some((result) => result !== undefined) || (readsGrid && grid.hasFetched);
      const hasPayload = sources.some((source) => dynamicWeather[source.group]?.[source.source]?.payload !== undefined);
      status[group] = deriveFetchLayerStatus(loading, error, hasPayload, hasFetched);
    }
    // 配信が落ちている要素を出しているチップは、フェッチ側が正常でもエラーにする
    // （deriveFetchLayerStatusと同じくエラーを最優先にする）。
    for (const layerId of tileDeliveryFailureLayerIds(dynamicWeather, tileFailures)) status[layerId] = "error";
    return status;
  }, [shownSources, deliveryResults, grid.loading, grid.error, grid.hasFetched, dynamicWeather, tileFailures]);

  return { dynamicWeather, dynamicWeatherDataStatus };
}
