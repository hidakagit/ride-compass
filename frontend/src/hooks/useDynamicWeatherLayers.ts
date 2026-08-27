"use client";

// 動的気象レイヤー（降水ナウキャスト・風/延長降水予報・雷/竜巻ナウキャスト）のフェッチ・
// 共有タイムライン・MapViewへ渡す描画ペイロードまでを1つのフックへ抽出したもの
// （改善計画T375、T284の分割方針決定を受けた実施）。元はpage.tsx内に直接書かれていた
// 3本のfetch effect（降水ナウキャストT170/T171・雷竜巻ナウキャストT204・
// useWeatherGrid経由の風/延長降水予報T183）と、そこから導出する共有タイムライン
// （T183再設計「時間経過はスライドバー1本で表現する」）・DynamicLayerTimeSlider向けの
// props・MapView向けのdynamicWeatherプロパティを、この1フックへまとめた。
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchNowcastFrames,
  precipitationFrames,
  precipitationRenderPayload,
  trimToCurrentAndFuture,
  type NowcastFrame,
} from "@/components/Map/precipitationNowcast";
import { windFrames, windRenderPayload, type MapViewport } from "@/components/Map/windLayer";
import {
  fetchThunderNowcastFrames,
  thunderFrames,
  thunderRenderPayload,
  tornadoRenderPayload,
  type ThunderNowcastFrame,
} from "@/components/Map/thunderNowcast";
import {
  formatDynamicFrameHourMinute,
  formatDynamicFrameMinuteOnly,
  formatDynamicFrameTime,
  frameIndexForTime,
  mergeFrameTimes,
  nearestTimeIndex,
  type DynamicWeatherLayerId,
  type DynamicWeatherRenderPayload,
} from "@/components/Map/dynamicWeather";
import type { DynamicLayerTimeSliderFrame } from "@/components/DynamicLayerTimeSlider/DynamicLayerTimeSlider";
import { useWeatherGrid } from "@/hooks/useWeatherGrid";
import { debugLog } from "@/lib/debugLog";

// 実況が5分毎に更新されるのに合わせた再取得間隔（降水・雷竜巻ナウキャスト共通、
// 雷は10分毎更新のため5分より長くても足りるが、実装を単純にするため揃えている）。
const NOWCAST_REFRESH_INTERVAL_MS = 5 * 60 * 1000;

export interface UseDynamicWeatherLayersOptions {
  showWindVector: boolean;
  showPrecipitationNowcast: boolean;
  showThunderNowcast: boolean;
  showTornadoNowcast: boolean;
  mapViewport: MapViewport | null;
}

export interface UseDynamicWeatherLayersResult {
  /** MapViewへそのまま渡す動的気象レイヤーのプロパティ（T183再設計、旧5個の個別props統合）。 */
  dynamicWeather: Partial<Record<DynamicWeatherLayerId, { visible: boolean; payload: DynamicWeatherRenderPayload | undefined }>>;
  /** DynamicLayerTimeSlider向けの目盛りラベル列。 */
  sliderFrames: DynamicLayerTimeSliderFrame[];
  /** スライダーのつまみ位置（共有のdynamicLayerTargetTimeに最も近いタイムライン上のindex）。 */
  sliderIndex: number;
  /** 「現在」ボタンのジャンプ先index（押された時点のtimelineから都度計算）。 */
  sliderCurrentIndex: number;
  /** スライダー操作: タイムライン上のindexを実時刻へ変換してdynamicLayerTargetTimeへ書き込む。 */
  handleSliderIndexChange: (index: number) => void;
  /** 「現在」ボタン: dynamicLayerTargetTimeを現在時刻に戻す。 */
  handleDynamicLayerNow: () => void;
  dynamicLayerLoading: boolean;
  dynamicLayerError: string | null;
}

/** 動的気象レイヤー（降水ナウキャスト・風/延長降水予報・雷/竜巻ナウキャスト）の
 * フェッチ・共有タイムライン・MapView向け描画ペイロードの管理（改善計画T375）。
 * 各要素は対応するshow*がtrueの間だけフェッチし、OFFの間はfetch自体しない
 * （他の外部APIと同じ「表示中のものだけ叩く」方針）。 */
export function useDynamicWeatherLayers({
  showWindVector,
  showPrecipitationNowcast,
  showThunderNowcast,
  showTornadoNowcast,
  mapViewport,
}: UseDynamicWeatherLayersOptions): UseDynamicWeatherLayersResult {
  // 動的気象レイヤーが指す対象時刻（T183再設計）。ONの全レイヤーのフレーム時刻を統合した
  // 1本のタイムライン（下記timeline）上の1点で、各レイヤーはこの時刻に対応する自分の
  // フレームを描画する。
  const [dynamicLayerTargetTime, setDynamicLayerTargetTime] = useState(() => new Date());

  // 降水ナウキャストの時刻一覧（改善計画T170/T171）。取得失敗時は例外を投げずnowcastErrorへ
  // 記録する（precipitationNowcast.tsのfetchNowcastFramesは両方失敗時のみ例外、片方だけの
  // 失敗は部分的な結果を返すため、ここへ来るのは両方失敗した場合のみ）。
  const [nowcastFrames, setNowcastFrames] = useState<NowcastFrame[]>([]);
  const [nowcastLoading, setNowcastLoading] = useState(false);
  const [nowcastError, setNowcastError] = useState<string | null>(null);
  useEffect(() => {
    if (!showPrecipitationNowcast) return;
    let cancelled = false;
    const load = async (isFirstLoad: boolean) => {
      if (isFirstLoad) setNowcastLoading(true);
      try {
        // 実況（targetTimes_N1）は現在時刻より前ぶんを多く含む。過去の降水を振り返る用途は
        // アプリの性質上無いため、trimToCurrentAndFutureで「現在」より前を切り捨て、
        // スライダーの左端（index 0）が常に「現在」になるようにする。
        const frames = trimToCurrentAndFuture(await fetchNowcastFrames());
        if (cancelled) return;
        setNowcastFrames(frames);
        setNowcastError(null);
      } catch (error: unknown) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "降水ナウキャストの取得に失敗しました";
        debugLog("api:jma-nowcast-times", "降水ナウキャストの読み込みに失敗", { error: message }, "error");
        setNowcastError(message);
      } finally {
        if (!cancelled && isFirstLoad) setNowcastLoading(false);
      }
    };
    Promise.resolve().then(() => load(true));
    const intervalId = window.setInterval(() => load(false), NOWCAST_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [showPrecipitationNowcast]);

  // 雷・竜巻の時刻一覧（改善計画T204）。同じtargetTimes_N3.json由来のため、どちらか一方でも
  // ONの間だけ1本のfetchで両方をカバーする（nowcastFramesと同じ理由・同じ更新間隔）。
  const [thunderNowcastFrames, setThunderNowcastFrames] = useState<ThunderNowcastFrame[]>([]);
  const [thunderNowcastLoading, setThunderNowcastLoading] = useState(false);
  const [thunderNowcastError, setThunderNowcastError] = useState<string | null>(null);
  useEffect(() => {
    if (!showThunderNowcast && !showTornadoNowcast) return;
    let cancelled = false;
    const load = async (isFirstLoad: boolean) => {
      if (isFirstLoad) setThunderNowcastLoading(true);
      try {
        const frames = trimToCurrentAndFuture(await fetchThunderNowcastFrames());
        if (cancelled) return;
        setThunderNowcastFrames(frames);
        setThunderNowcastError(null);
      } catch (error: unknown) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "雷ナウキャストの取得に失敗しました";
        debugLog("api:jma-nowcast-times", "雷・竜巻ナウキャストの読み込みに失敗", { error: message }, "error");
        setThunderNowcastError(message);
      } finally {
        if (!cancelled && isFirstLoad) setThunderNowcastLoading(false);
      }
    };
    Promise.resolve().then(() => load(true));
    const intervalId = window.setInterval(() => load(false), NOWCAST_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [showThunderNowcast, showTornadoNowcast]);

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
  const precipFramesList = useMemo(() => precipitationFrames(nowcastFrames, windGrid), [nowcastFrames, windGrid]);
  // 雷・竜巻は同じthunderNowcastFramesを共有する1本のフレーム列（改善計画T204）。
  const thunderFramesList = useMemo(() => thunderFrames(thunderNowcastFrames), [thunderNowcastFrames]);

  // ONの全レイヤーのフレーム時刻を統合した共有タイムライン（T183再設計、実機フィードバック
  // 「時間経過はスライドバー1本で表現する」）。降水ナウキャスト（5分刻み）と風・延長予報
  // （1時間刻み）が混ざると、目盛りが「近い将来は細かく、遠い将来は粗い」を自然に実現する。
  const activeFrameLists = useMemo(() => {
    const lists: { time: Date }[][] = [];
    if (showWindVector) lists.push(windFramesList);
    if (showPrecipitationNowcast) lists.push(precipFramesList);
    if (showThunderNowcast || showTornadoNowcast) lists.push(thunderFramesList);
    return lists;
  }, [showWindVector, windFramesList, showPrecipitationNowcast, precipFramesList, showThunderNowcast, showTornadoNowcast, thunderFramesList]);
  const timeline = useMemo(() => mergeFrameTimes(activeFrameLists), [activeFrameLists]);

  // スライダーのつまみ位置（共有のdynamicLayerTargetTimeに最も近いタイムライン上のindex）と、
  // 表示用ラベル列。正時判定はgetUTCMinutes()で行う（JSTはUTC+9:00ちょうどで分のずれが
  // 無いため、実行環境のローカルタイムゾーンに左右されずJSTの正時と一致する）。延長予報
  // （60分以降）は全フレームが正時のため、hourMark（目盛りの線を太くするだけ）は毎コマ
  // 付けても密度の問題は無いが、tickLabel（目盛りの下に出す文字）を毎時間ぶん全部
  // 「HH:mm」で出すと目盛り間隔に対して文字が重なってしまうため、2時間おきに間引く。
  // 正時でない密なコマ（降水ナウキャストの5分刻み等）は文字自体を短い分のみ表記にできる
  // ため、間引かず毎コマぶん出す。
  const sliderIndex = useMemo(() => nearestTimeIndex(timeline, dynamicLayerTargetTime), [timeline, dynamicLayerTargetTime]);
  const sliderFrames = useMemo<DynamicLayerTimeSliderFrame[]>(
    () =>
      timeline.map((time) => {
        const isHour = time.getUTCMinutes() === 0;
        return {
          label: formatDynamicFrameTime(time),
          hourMark: isHour,
          tickLabel: isHour
            ? time.getUTCHours() % 2 === 0
              ? formatDynamicFrameHourMinute(time)
              : undefined
            : formatDynamicFrameMinuteOnly(time),
        };
      }),
    [timeline]
  );
  // 「現在」に戻るボタンのジャンプ先index。ボタンはフェッチのたびではなく毎回押された
  // 時点の「現在」に戻したいため、timeline自体から都度計算する。
  const sliderCurrentIndex = useMemo(() => nearestTimeIndex(timeline, new Date()), [timeline]);

  const handleSliderIndexChange = useCallback(
    (index: number) => {
      const time = timeline[index];
      if (time) setDynamicLayerTargetTime(time);
    },
    [timeline]
  );
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
    return precipitationRenderPayload(nowcastFrames, effectiveWindGrid, effectiveGridSpacingDeg, precipFramesList[index].ref);
  }, [precipFramesList, dynamicLayerTargetTime, nowcastFrames, effectiveWindGrid, effectiveGridSpacingDeg]);
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

  // MapViewへ渡す単一プロパティ（T183再設計、旧5個のprecipitation/wind個別propsを統合）。
  // 新しい動的気象要素を追加してもMapViewProps自体は変わらず、ここへ1エントリ足すだけでよい。
  const dynamicWeather = useMemo(
    () => ({
      windVector: { visible: showWindVector, payload: windPayload },
      precipitationNowcast: { visible: showPrecipitationNowcast, payload: precipitationPayload },
      thunderNowcast: { visible: showThunderNowcast, payload: thunderPayload },
      tornadoNowcast: { visible: showTornadoNowcast, payload: tornadoPayload },
    }),
    [showWindVector, windPayload, showPrecipitationNowcast, precipitationPayload, showThunderNowcast, thunderPayload, showTornadoNowcast, tornadoPayload]
  );

  // 共有スライダーのloading/error表示。windLoading/windErrorは両要素が使う格子点フェッチ
  // （useWeatherGrid、ONのどちらか一方でも走る）、nowcastLoading/nowcastErrorは降水ナウキャスト
  // 固有のフェッチ、thunderNowcastLoading/thunderNowcastErrorは雷・竜巻共有のフェッチ。
  // 風のみONならnowcast/thunderの状態は無関係（フェッチ自体走らない）。
  const dynamicLayerLoading =
    windLoading || (showPrecipitationNowcast && nowcastLoading) || ((showThunderNowcast || showTornadoNowcast) && thunderNowcastLoading);
  const dynamicLayerError =
    windError ?? (showPrecipitationNowcast ? nowcastError : null) ?? (showThunderNowcast || showTornadoNowcast ? thunderNowcastError : null);

  return {
    dynamicWeather,
    sliderFrames,
    sliderIndex,
    sliderCurrentIndex,
    handleSliderIndexChange,
    handleDynamicLayerNow,
    dynamicLayerLoading,
    dynamicLayerError,
  };
}
