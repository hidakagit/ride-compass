"use client";

// 動的気象レイヤー（降水ナウキャスト・風/延長降水予報・雷/竜巻ナウキャスト）のフェッチ・
// 共有タイムライン・MapViewへ渡す描画ペイロードまでを1つのフックへ抽出したもの
// （改善計画T375、T284の分割方針決定を受けた実施）。元はpage.tsx内に直接書かれていた
// 3本のfetch effect（降水ナウキャストT170/T171・雷竜巻ナウキャストT204・
// useWeatherGrid経由の風/延長降水予報T183）と、そこから導出する共有タイムライン
// （T183再設計「時間経過はスライドバー1本で表現する」）・条件バー向けの
// 共有時刻・MapView向けのdynamicWeatherプロパティを、この1フックへまとめた。
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchNowcastFrames,
  fetchRasrfFrames,
  precipitationFrames,
  precipitationRenderPayload,
  trimToCurrentAndFuture,
  type NowcastFrame,
  type RasrfFrame,
} from "@/components/Map/precipitationNowcast";
import { windFrames, windRenderPayload, type MapViewport } from "@/components/Map/windLayer";
import {
  fetchThunderNowcastFrames,
  thunderFrames,
  thunderRenderPayload,
  tornadoRenderPayload,
  type ThunderNowcastFrame,
} from "@/components/Map/thunderNowcast";
import { fetchLidenFrames, fetchLidenGeojson, lidenFrames, type LidenFrame } from "@/components/Map/lidenLayer";
import {
  fetchCurrentRiskFrames,
  fetchLinearRainbandFrames,
  floodRenderPayload,
  heavyRainRenderPayload,
  inundationRenderPayload,
  landRenderPayload,
  linearRainbandRenderPayload,
  type CurrentRiskFrames,
  type RiskFrameRef,
} from "@/components/Map/riskMap";
import type { DynamicWeatherFrame } from "@/components/Map/dynamicWeather";
import {
  frameIndexForTime,
  isWithinFutureWindow,
  type DynamicWeatherGroupState,
  type DynamicWeatherLayerId,
  type DynamicWeatherRenderPayload,
} from "@/components/Map/dynamicWeather";
import type { LayerDataStatus } from "@/components/Map/mapLayers";
import { useWeatherGrid } from "@/hooks/useWeatherGrid";
import { usePolledFetch } from "@/hooks/usePolledFetch";

// 実況が5分毎に更新されるのに合わせた再取得間隔（降水・雷竜巻ナウキャスト共通、
// 雷は10分毎更新のため5分より長くても足りるが、実装を単純にするため揃えている）。
const NOWCAST_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
// 降水短時間予報（改善計画T407）の再取得間隔。直近0〜6時間の"immed"系列が最も高頻度で
// 更新される部分（precipitationNowcast.ts: fetchRasrfFrames参照）に合わせる。
const RASRF_REFRESH_INTERVAL_MS = 10 * 60 * 1000;
// キキクル・線状降水帯予測マップ（改善計画T410）の再取得間隔。キキクルは10分おき更新
// （riskMap.tsのモジュールdocstring参照）に合わせる。
const RISK_MAP_REFRESH_INTERVAL_MS = 10 * 60 * 1000;

// 線状降水帯予測マップ（改善計画T432でrisk系統からrasrf系統・「降水」チップ傘下へ再分類）を
// 重ねて表示する時間窓。「今後3時間以内に大雨のおそれ」という予報の意味そのものに合わせる。
const LINEAR_RAINBAND_WINDOW_MS = 3 * 60 * 60 * 1000;

const EMPTY_RISK_FRAMES: DynamicWeatherFrame<RiskFrameRef>[] = [];
const EMPTY_CURRENT_RISK_FRAMES: CurrentRiskFrames = {
  land: EMPTY_RISK_FRAMES,
  heavyRain: EMPTY_RISK_FRAMES,
  inundation: EMPTY_RISK_FRAMES,
  flood: EMPTY_RISK_FRAMES,
};
const EMPTY_NOWCAST_FRAMES: NowcastFrame[] = [];
const EMPTY_RASRF_FRAMES: RasrfFrame[] = [];
const EMPTY_THUNDER_NOWCAST_FRAMES: ThunderNowcastFrame[] = [];
const EMPTY_LIDEN_FRAMES: LidenFrame[] = [];

export interface UseDynamicWeatherLayersOptions {
  showWindVector: boolean;
  showPrecipitationNowcast: boolean;
  showThunderNowcast: boolean;
  showTornadoNowcast: boolean;
  showLiden: boolean;
  showLandslideRisk: boolean;
  showHeavyRainRisk: boolean;
  showInundationRisk: boolean;
  showFloodRisk: boolean;
  mapViewport: MapViewport | null;
}

export interface UseDynamicWeatherLayersResult {
  /** MapViewへそのまま渡す動的気象レイヤーのプロパティ（T183再設計、旧5個の個別props統合。
   * 改善計画T432でグループ内の複数ソース[raster/gridFill/gridMark]を同時に持てる形へ
   * 一般化した）。 */
  dynamicWeather: Partial<Record<DynamicWeatherLayerId, DynamicWeatherGroupState>>;
  /** レイヤーごとのデータ取得状態（改善計画T608）。各要素のフェッチ（`usePolledFetch`/
   * `useWeatherGrid`）自身が持つloading/errorと、選択中の共有時刻に対応するpayloadの
   * 有無から直接算出する——MapLibreのソースイベント（改善計画T87、`useLayerDataStatus.ts`）は
   * 経由しない。これらのレイヤーは実際の外部フェッチが自前のJSコード（`usePolledFetch`等）で
   * 行われ、結果を`map.getSource(id).setData(...)`で流し込むだけのため、MapLibre側の
   * ソースイベントは外部フェッチの待ち時間・失敗を観測できない（GeoJSON/ラスタ/ベクタの
   * いずれの`kind`でも、フェッチ自体はこのフックの外の世界で完結している）。 */
  dynamicWeatherDataStatus: Partial<Record<DynamicWeatherLayerId, LayerDataStatus>>;
  /** 共有時刻を任意の時刻へ設定する（条件バーの出発時刻）。 */
  setDynamicLayerTargetTime: (time: Date) => void;
  /** 共有時刻を現在時刻に戻す。 */
  handleDynamicLayerNow: () => void;
  /** 改善計画T414: windAxis（評価軸グループの風、backend API）が同じ[時刻]を共有するために
   * 公開する共有時刻そのもの（`at`クエリパラメータに使う）。 */
  dynamicLayerTargetTime: Date;
}

/** loading/error/payloadの有無から`LayerDataStatus`を1つ決める（改善計画T608）。
 * 判定順序はuseLayerDataStatus.ts: computeLayerDataStatusと同じ「エラー中 > 読込中 >
 * 読込済みだが値なし」。正常時（現在時刻に対応する値が描画できている）はundefined
 * （呼び出し元はキー自体を持たない状態として扱う）。 */
function dynamicWeatherStatus(loading: boolean, error: string | null, hasPayload: boolean): LayerDataStatus | undefined {
  if (error) return "error";
  if (loading) return "loading";
  if (!hasPayload) return "empty";
  return undefined;
}

/** 動的気象レイヤー（降水ナウキャスト・風/延長降水予報・雷/竜巻ナウキャスト・キキクル）の
 * フェッチ・共有タイムライン・MapView向け描画ペイロードの管理（改善計画T375）。
 * 各要素は対応するshow*がtrueの間だけフェッチし、OFFの間はfetch自体しない
 * （他の外部APIと同じ「表示中のものだけ叩く」方針）。 */
export function useDynamicWeatherLayers({
  showWindVector,
  showPrecipitationNowcast,
  showThunderNowcast,
  showTornadoNowcast,
  showLiden,
  showLandslideRisk,
  showHeavyRainRisk,
  showInundationRisk,
  showFloodRisk,
  mapViewport,
}: UseDynamicWeatherLayersOptions): UseDynamicWeatherLayersResult {
  // 動的気象レイヤーが指す対象時刻（T183再設計）。ONの全レイヤーのフレーム時刻を統合した
  // 1本のタイムライン（下記timeline）上の1点で、各レイヤーはこの時刻に対応する自分の
  // フレームを描画する。
  const [dynamicLayerTargetTime, setDynamicLayerTargetTime] = useState(() => new Date());

  // 降水ナウキャストの時刻一覧（改善計画T170/T171）。取得失敗時は例外を投げずnowcastErrorへ
  // 記録する（precipitationNowcast.tsのfetchNowcastFramesは両方失敗時のみ例外、片方だけの
  // 失敗は部分的な結果を返すため、ここへ来るのは両方失敗した場合のみ）。
  // 改善計画T441: この後もwindow.setIntervalで定期的に再取得するフェイルソフト設計
  // （下の各fetch同様）のため、単発の取得失敗は"error"ではなく"warn"とする
  // （usePolledFetch.ts参照）。
  const {
    data: rawNowcastFrames,
    loading: nowcastLoading,
    error: nowcastError,
  } = usePolledFetch(fetchNowcastFrames, EMPTY_NOWCAST_FRAMES, {
    enabled: showPrecipitationNowcast,
    intervalMs: NOWCAST_REFRESH_INTERVAL_MS,
    label: "降水ナウキャスト",
  });
  // 実況（targetTimes_N1）は現在時刻より前ぶんを多く含む。過去の降水を振り返る用途は
  // アプリの性質上無いため、trimToCurrentAndFutureで「現在」より前を切り捨て、
  // スライダーの左端（index 0）が常に「現在」になるようにする。
  const nowcastFrames = useMemo(() => trimToCurrentAndFuture(rawNowcastFrames), [rawNowcastFrames]);

  // 降水短時間予報の時刻一覧（改善計画T407、60分〜15時間先）。「降水」チップの一部
  // （precipitationNowcast.ts: precipitationFrames参照）のため、ナウキャストと同じ
  // showPrecipitationNowcastで開閉する。取得失敗はnowcastと同じくエラーメッセージへ記録するが、
  // precipitationFramesがrasrfFrames=[]でも自然にextended予報へフォールバックするため、
  // 「降水」チップ自体は動作を続ける（フェイルソフト）。
  const { data: rasrfFrames } = usePolledFetch(fetchRasrfFrames, EMPTY_RASRF_FRAMES, {
    enabled: showPrecipitationNowcast,
    intervalMs: RASRF_REFRESH_INTERVAL_MS,
    label: "降水短時間予報",
  });

  // 雷・竜巻の時刻一覧（改善計画T204）。同じtargetTimes_N3.json由来のため、どちらか一方でも
  // ONの間だけ1本のfetchで両方をカバーする（nowcastFramesと同じ理由・同じ更新間隔）。
  const {
    data: rawThunderNowcastFrames,
    loading: thunderNowcastLoading,
    error: thunderNowcastError,
  } = usePolledFetch(fetchThunderNowcastFrames, EMPTY_THUNDER_NOWCAST_FRAMES, {
    enabled: showThunderNowcast || showTornadoNowcast,
    intervalMs: NOWCAST_REFRESH_INTERVAL_MS,
    label: "雷・竜巻ナウキャスト",
  });
  const thunderNowcastFrames = useMemo(
    () => trimToCurrentAndFuture(rawThunderNowcastFrames),
    [rawThunderNowcastFrames],
  );

  // 雷放電位置データ（改善計画T541）。同じtargetTimes_N3.json由来だが、雷・竜巻とは
  // 独立したON/OFFのため別のfetchで取得する（fetchLidenFramesがliden自体を含む
  // エントリだけへ絞り込む、lidenLayer.ts参照）。
  const {
    data: rawLidenNowcastFrames,
    loading: lidenNowcastLoading,
    error: lidenNowcastError,
  } = usePolledFetch(fetchLidenFrames, EMPTY_LIDEN_FRAMES, {
    enabled: showLiden,
    intervalMs: NOWCAST_REFRESH_INTERVAL_MS,
    label: "雷放電位置データ",
  });
  const lidenNowcastFrames = useMemo(() => trimToCurrentAndFuture(rawLidenNowcastFrames), [rawLidenNowcastFrames]);

  // キキクル4種（土砂災害・大雨・浸水・洪水）の「現在」フレーム。4種で1本のtargetTimes.json
  // を共有するため（riskMap.ts参照）1本のfetchでまとめて取得する（thunderNowcastFramesと
  // 同じ考え方で、いずれか1つでもONの間だけenabledにする）。未来方向のフレームを持たない
  // ため取得失敗時もnowcastのような「部分結果」は無く、フェッチ自体を諦めてエラーのみ
  // 記録する。
  const {
    data: currentRiskFrames,
    loading: currentRiskLoading,
    error: currentRiskError,
  } = usePolledFetch(
    fetchCurrentRiskFrames,
    EMPTY_CURRENT_RISK_FRAMES,
    {
      enabled: showLandslideRisk || showHeavyRainRisk || showInundationRisk || showFloodRisk,
      intervalMs: RISK_MAP_REFRESH_INTERVAL_MS,
      label: "危険度分布（キキクル）",
    },
  );

  // 線状降水帯予測マップ（改善計画T410、T432で「降水」チップ傘下へ再分類）の「現在」フレーム。
  // キキクルとはtargetTimes.json自体が別（rasrfのtargetTimes.jsonにelements違いの別行として
  // 混在、riskMap.ts参照）。「降水」チップ（showPrecipitationNowcast）に連動する。
  const {
    data: linearRainbandFrames,
    loading: linearRainbandLoading,
    error: linearRainbandError,
  } = usePolledFetch(
    fetchLinearRainbandFrames,
    EMPTY_RISK_FRAMES,
    { enabled: showPrecipitationNowcast, intervalMs: RISK_MAP_REFRESH_INTERVAL_MS, label: "線状降水帯予測マップ" },
  );

  // 風・降水延長予報（T183）が共有する格子点マップのフェッチ（useWeatherGrid.ts参照）。
  // どちらか一方でもONならenabledにすることで両方ONのときも1本のフェッチで済む。
  const {
    grid: windGrid,
    effectiveGrid: effectiveWindGrid,
    effectiveGridSpacingDeg,
    loading: windLoading,
    error: windError,
  } = useWeatherGrid(showWindVector || showPrecipitationNowcast, mapViewport);

  // 各要素のフレーム列（データ層、dynamicWeather.ts: DynamicWeatherFrame[]）。表示層は
  // ここから先、どの要素がどのデータソースから来ているかを一切意識しない
  // （T183再設計「データ取得の差異はデータ層で吸収」）。
  const windFramesList = useMemo(() => windFrames(windGrid), [windGrid]);
  const precipFramesList = useMemo(
    () => precipitationFrames(nowcastFrames, rasrfFrames, windGrid),
    [nowcastFrames, rasrfFrames, windGrid]
  );
  // 雷・竜巻は同じthunderNowcastFramesを共有する1本のフレーム列（改善計画T204）。
  const thunderFramesList = useMemo(() => thunderFrames(thunderNowcastFrames), [thunderNowcastFrames]);
  const lidenFramesList = useMemo(() => lidenFrames(lidenNowcastFrames), [lidenNowcastFrames]);
  // キキクル3種+線状降水帯予測マップ（改善計画T410）。riskMap.tsが既にDynamicWeatherFrame
  // 形式で返すが、他レイヤーと異なり共有タイムライン・frameIndexForTimeには乗せない
  // （下記の理由）。
  const {
    land: landFramesList,
    heavyRain: heavyRainFramesList,
    inundation: inundationFramesList,
    flood: floodFramesList,
  } = currentRiskFrames;

  const handleDynamicLayerNow = useCallback(() => setDynamicLayerTargetTime(new Date()), []);

  // 選択中の共有時刻（dynamicLayerTargetTime）に対応する各要素のペイロード。該当時刻が
  // その要素のデータ範囲外なら描画しない（frameIndexForTimeがnullを返す、「該当時間データが
  // ない場合、地図には描画しない」。端のフレームへクランプして古いデータを見せ続ける挙動は
  // 持たない）。表示層（MapView.tsx）はkindしか見ないため、降水がナウキャスト由来
  // （rasterTile）か延長予報由来（gridFill）かはここで既に吸収済み。
  const windPayload = useMemo(() => {
    const index = frameIndexForTime(windFramesList, dynamicLayerTargetTime);
    if (index == null || effectiveWindGrid.length === 0) return undefined;
    return windRenderPayload(effectiveWindGrid, windFramesList[index].ref);
  }, [windFramesList, dynamicLayerTargetTime, effectiveWindGrid]);
  const precipitationPayload = useMemo(() => {
    const index = frameIndexForTime(precipFramesList, dynamicLayerTargetTime);
    if (index == null) return undefined;
    return precipitationRenderPayload(
      nowcastFrames,
      rasrfFrames,
      effectiveWindGrid,
      effectiveGridSpacingDeg,
      precipFramesList[index].ref
    );
  }, [precipFramesList, dynamicLayerTargetTime, nowcastFrames, rasrfFrames, effectiveWindGrid, effectiveGridSpacingDeg]);
  // 雷・竜巻は同じフレーム列・同じrefを共有し、プロダクトコードだけが異なる
  // （thunderRenderPayload/tornadoRenderPayloadの違い、thunderNowcast.ts参照）。
  const thunderPayload = useMemo(() => {
    const index = frameIndexForTime(thunderFramesList, dynamicLayerTargetTime);
    if (index == null) return undefined;
    return thunderRenderPayload(thunderNowcastFrames, thunderFramesList[index].ref);
  }, [thunderFramesList, dynamicLayerTargetTime, thunderNowcastFrames]);
  const tornadoPayload = useMemo(() => {
    const index = frameIndexForTime(thunderFramesList, dynamicLayerTargetTime);
    if (index == null) return undefined;
    return tornadoRenderPayload(thunderNowcastFrames, thunderFramesList[index].ref);
  }, [thunderFramesList, dynamicLayerTargetTime, thunderNowcastFrames]);
  // 雷放電位置データ（改善計画T541）。配信元が実際の落雷地点をGeoJSONで提供するため、
  // 他要素と異なり選択フレームが変わるたびに個別fetchが要る（lidenLayer.ts参照）。
  // 取得済みgeojsonにref（frames内のindex）を添えて保持し、選択中のindexと一致する
  // ときだけpayloadへ反映する——scrub中に古いフェッチが新しいフェッチより後に解決しても、
  // 直前に選んでいた古い時刻のデータを新しい時刻の表示へ混ぜない。
  const lidenIndex = frameIndexForTime(lidenFramesList, dynamicLayerTargetTime);
  const lidenRef = lidenIndex == null ? undefined : lidenFramesList[lidenIndex].ref;
  const [lidenFetched, setLidenFetched] = useState<{ ref: number; geojson: GeoJSON.FeatureCollection } | undefined>();
  useEffect(() => {
    if (!showLiden || lidenRef == null) return;
    let cancelled = false;
    fetchLidenGeojson(lidenNowcastFrames, lidenRef)
      .then((geojson) => {
        if (cancelled || !geojson) return;
        setLidenFetched({ ref: lidenRef, geojson });
      })
      .catch(() => {
        // フェッチ失敗は表示しないだけに留める（他要素と同じフェイルソフト方針、
        // fetchJson自体がdebugLogへ記録済み）。
      });
    return () => {
      cancelled = true;
    };
  }, [showLiden, lidenRef, lidenNowcastFrames]);
  const lidenPayload = useMemo((): DynamicWeatherRenderPayload | undefined => {
    if (lidenIndex == null || !lidenFetched || lidenFetched.ref !== lidenRef) return undefined;
    return { kind: "gridMark", geojson: lidenFetched.geojson };
  }, [lidenIndex, lidenFetched, lidenRef]);
  // キキクル4種（改善計画T410）は未来方向のフレームを持たず「現在の危険度」単一値のみを
  // 配信するため、選択中の共有時刻に関わらずframes[0]（現在値）があれば表示する
  // （riskMap.ts冒頭コメント「他の動的レイヤーと違い共有タイムライン・frameIndexForTimeには
  // 乗せない」と対）。
  const landslideRiskPayload = useMemo(() => {
    const frame = landFramesList[0];
    return frame ? landRenderPayload(frame.ref) : undefined;
  }, [landFramesList]);
  const heavyRainRiskPayload = useMemo(() => {
    const frame = heavyRainFramesList[0];
    return frame ? heavyRainRenderPayload(frame.ref) : undefined;
  }, [heavyRainFramesList]);
  const inundationRiskPayload = useMemo(() => {
    const frame = inundationFramesList[0];
    return frame ? inundationRenderPayload(frame.ref) : undefined;
  }, [inundationFramesList]);
  // 洪水キキクル（改善計画T416）。他3種と同じ「frames[0]があれば表示」方針
  // （vectorTile kindのため戻り値の中身は異なるが、ここでの扱いは同型）。
  const floodRiskPayload = useMemo(() => {
    const frame = floodFramesList[0];
    return frame ? floodRenderPayload(frame.ref) : undefined;
  }, [floodFramesList]);
  // 線状降水帯予測マップ（改善計画T410、T432でrisk系統からrasrf系統・「降水」チップ傘下へ
  // 再分類）。他のキキクル3種と異なり「今後3時間以内におそれ」という予報の性質上、共有
  // タイムラインの選択時刻が現在〜3時間先の範囲内にあるときだけ、ナウキャスト/rasrf/
  // 延長予報のいずれかと重ねて表示する（isWithinFutureWindow、dynamicWeather.ts参照）。
  const linearRainbandVisible = useMemo(
    () => isWithinFutureWindow(dynamicLayerTargetTime, new Date(), LINEAR_RAINBAND_WINDOW_MS),
    [dynamicLayerTargetTime]
  );
  const linearRainbandPayload = useMemo(() => {
    if (!linearRainbandVisible) return undefined;
    const frame = linearRainbandFrames[0];
    return frame ? linearRainbandRenderPayload(frame.ref) : undefined;
  }, [linearRainbandFrames, linearRainbandVisible]);

  // MapViewへ渡す単一プロパティ（T183再設計、旧5個のprecipitation/wind個別propsを統合）。
  // 1グループが複数の名前付きソースを同時に持てる——precipitationNowcastは時系列3段
  // [main]と線状降水帯[linearRainband]を同時に持つ。新しい動的気象要素を追加しても
  // MapViewProps自体は変わらず、ここへ1エントリ足すだけでよい。
  const dynamicWeather = useMemo(
    () => ({
      windVector: {
        arrow: { visible: showWindVector, payload: windPayload },
      },
      precipitationNowcast: {
        main: { visible: showPrecipitationNowcast, payload: precipitationPayload },
        linearRainband: { visible: showPrecipitationNowcast, payload: linearRainbandPayload },
      },
      thunderNowcast: { main: { visible: showThunderNowcast, payload: thunderPayload } },
      tornadoNowcast: { main: { visible: showTornadoNowcast, payload: tornadoPayload } },
      liden: { main: { visible: showLiden, payload: lidenPayload } },
      landslideRisk: { main: { visible: showLandslideRisk, payload: landslideRiskPayload } },
      heavyRainRisk: { main: { visible: showHeavyRainRisk, payload: heavyRainRiskPayload } },
      inundationRisk: { main: { visible: showInundationRisk, payload: inundationRiskPayload } },
      floodRisk: { main: { visible: showFloodRisk, payload: floodRiskPayload } },
    }),
    [
      showWindVector,
      windPayload,
      showPrecipitationNowcast,
      precipitationPayload,
      linearRainbandPayload,
      showThunderNowcast,
      thunderPayload,
      showTornadoNowcast,
      tornadoPayload,
      showLiden,
      lidenPayload,
      showLandslideRisk,
      landslideRiskPayload,
      showHeavyRainRisk,
      heavyRainRiskPayload,
      showInundationRisk,
      inundationRiskPayload,
      showFloodRisk,
      floodRiskPayload,
    ]
  );

  // レイヤーごとのデータ取得状態（改善計画T608）。9レイヤー全てが同じdynamicWeatherStatus
  // 関数を通る——「読込中」表示のためにレイヤーの種類（raster/gridFill/gridMark/vectorTile）を
  // 意識する必要は無い。precipitationNowcastは「main」（ナウキャスト/短時間予報/延長予報の
  // 3段）と「linearRainband」（4つ目のソース）の両方を1つのチップとして統合する
  // （UI上のチップも1つのため、地図に何かしら描画できていればloading/errorとしない）。
  const dynamicWeatherDataStatus = useMemo(
    () => ({
      windVector: dynamicWeatherStatus(windLoading, windError, windPayload !== undefined),
      precipitationNowcast: dynamicWeatherStatus(
        nowcastLoading || linearRainbandLoading,
        nowcastError ?? linearRainbandError,
        precipitationPayload !== undefined || linearRainbandPayload !== undefined
      ),
      thunderNowcast: dynamicWeatherStatus(thunderNowcastLoading, thunderNowcastError, thunderPayload !== undefined),
      tornadoNowcast: dynamicWeatherStatus(thunderNowcastLoading, thunderNowcastError, tornadoPayload !== undefined),
      liden: dynamicWeatherStatus(lidenNowcastLoading, lidenNowcastError, lidenPayload !== undefined),
      landslideRisk: dynamicWeatherStatus(currentRiskLoading, currentRiskError, landslideRiskPayload !== undefined),
      heavyRainRisk: dynamicWeatherStatus(currentRiskLoading, currentRiskError, heavyRainRiskPayload !== undefined),
      inundationRisk: dynamicWeatherStatus(currentRiskLoading, currentRiskError, inundationRiskPayload !== undefined),
      floodRisk: dynamicWeatherStatus(currentRiskLoading, currentRiskError, floodRiskPayload !== undefined),
    }),
    [
      windLoading,
      windError,
      windPayload,
      nowcastLoading,
      linearRainbandLoading,
      nowcastError,
      linearRainbandError,
      precipitationPayload,
      linearRainbandPayload,
      thunderNowcastLoading,
      thunderNowcastError,
      thunderPayload,
      tornadoPayload,
      lidenNowcastLoading,
      lidenNowcastError,
      lidenPayload,
      currentRiskLoading,
      currentRiskError,
      landslideRiskPayload,
      heavyRainRiskPayload,
      inundationRiskPayload,
      floodRiskPayload,
    ]
  );

  return {
    dynamicWeather,
    dynamicWeatherDataStatus,
    setDynamicLayerTargetTime,
    handleDynamicLayerNow,
    dynamicLayerTargetTime,
  };
}
