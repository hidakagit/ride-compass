"use client";

// 動的気象レイヤーの取得・選んだ時刻に描くコマ・地図へ渡す描画内容・チップの取得状態。
// **要素を名指さない**——何を・どこから・どう読み・どのコマを描くかは源泉の宣言
// （`weatherSources.ts: WEATHER_SOURCES`）が持ち、ここは表示中のソースをループして、段の種類
// （配信元のタイル・配信元の地点・自前の格子）ごとに1つずつの実装で描画内容を作る。
import { useQueries, type UseQueryResult } from "@tanstack/react-query";
import { useCallback, useMemo, useSyncExternalStore } from "react";
import type { MapLayerVisibility } from "@/features/map/layers/mapLayers";
import { deriveFetchLayerStatus, type LayerDataStatus } from "@/features/map/layers/mapLayers";
import {
  fetchJmaPointGeojson,
  fetchJmaTargetTimesFile,
  jmaFramesOf,
  jmaTargetTimesPaths,
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
import { getQueryClient } from "@/lib/queryClient";
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

/** 時刻一覧のファイル1つの取り方。間隔はそのファイルを読む表示中の要素のうち最も更新の速い系統に合わせる（遅い系統を
 * 早めに取り直すぶんには古い表示にならない）。失敗の文言に載る呼び名は最初に読む要素のもの（同じURLの同じ失敗を指す）。 */
interface TargetTimesFile {
  path: string;
  label: string;
  refreshIntervalMs: number;
}

/** ファイルの読み取りの状態。行も失敗も無ければ、まだ一度も届いていない。取り直しに失敗している間は、前に届いた行を
 * 使わずに失敗として数える（時刻一覧は数分で更新され、古い一覧のコマは表示時刻から外れていく）。 */
interface FileState {
  rows: readonly unknown[] | undefined;
  error: string | undefined;
}

const PENDING_FILE: FileState = { rows: undefined, error: undefined };

function fileStatesOf(results: readonly UseQueryResult<unknown[]>[]): FileState[] {
  return results.map((result) => ({
    rows: result.status === "success" ? result.data : undefined,
    error: result.status === "error" ? result.error.message : undefined,
  }));
}

function dataOf<T>(results: readonly UseQueryResult<T>[]): (T | undefined)[] {
  return results.map((result) => result.data);
}

function targetTimesFilesOf(deliveries: readonly { delivery: JmaDelivery; label: string }[]): TargetTimesFile[] {
  const byPath = new Map<string, TargetTimesFile>();
  for (const { delivery, label } of deliveries) {
    for (const path of jmaTargetTimesPaths(delivery)) {
      const known = byPath.get(path);
      byPath.set(path, {
        path,
        label: known?.label ?? label,
        refreshIntervalMs: Math.min(known?.refreshIntervalMs ?? Infinity, delivery.refreshIntervalMs),
      });
    }
  }
  return [...byPath.values()];
}

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

  // 表示中のソースが読む配信要素と、その時刻一覧のファイル。取りに行く単位はファイルで、同じファイルを読む要素
  // どうし（キキクルの各要素等）は1つの取得を共有する。
  const deliveries = useMemo(() => deliveriesOf(shownSources), [shownSources]);
  const files = useMemo(() => targetTimesFilesOf(deliveries), [deliveries]);
  const client = getQueryClient();
  const fileStates = useQueries(
    {
      queries: files.map((file) => ({
        queryKey: ["jma-target-times", file.path],
        queryFn: () => fetchJmaTargetTimesFile(file.path, file.label),
        refetchInterval: file.refreshIntervalMs,
      })),
      combine: fileStatesOf,
    },
    client,
  );
  const deliveryResults = useMemo(() => {
    const byPath = new Map(files.map((file, index) => [file.path, fileStates[index]]));
    const results = new Map<string, DeliveryResult>();
    for (const { delivery, label } of deliveries) {
      const states = jmaTargetTimesPaths(delivery).map((path) => byPath.get(path) ?? PENDING_FILE);
      // 読み込み中の間は結果を持たない（どれかのファイルがまだ一度も届いていない）。
      if (states.some((state) => state.rows === undefined && state.error === undefined)) continue;
      // 一部のファイルだけ取れなくても残りで部分的な時系列を作り、全部取れなかったときだけ最初の失敗を出す。
      const loaded = states.filter((state) => state.rows !== undefined);
      results.set(
        delivery.id,
        loaded.length > 0
          ? {
              frames: jmaFramesOf(
                delivery,
                loaded.flatMap((state) => state.rows!),
              ),
              error: null,
            }
          : { frames: [], error: states.find((state) => state.error)?.error ?? `${label}の時刻一覧が宣言されていない` },
      );
    }
    return results;
  }, [files, fileStates, deliveries]);

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
  // 取れなければ描かないだけに留める（取得の失敗はfetchJsonがdebugLogへ記録済み）。
  const pointData = useQueries(
    {
      queries: pointRequests.map((request) => ({
        queryKey: ["jma-points", request.key],
        queryFn: () => fetchJmaPointGeojson(request.delivery, request.frame, request.label),
      })),
      combine: dataOf,
    },
    client,
  );
  const points = useMemo(
    () =>
      new Map(
        pointRequests.flatMap((request, index): [string, GeoJSON.FeatureCollection][] => {
          const geojson = pointData[index];
          return geojson === undefined ? [] : [[request.key, geojson]];
        }),
      ),
    [pointRequests, pointData],
  );

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
