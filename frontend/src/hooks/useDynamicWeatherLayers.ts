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
import {
  fetchCurrentRiskFrames,
  fetchLinearRainbandFrames,
  heavyRainRenderPayload,
  inundationRenderPayload,
  landRenderPayload,
  linearRainbandRenderPayload,
  type CurrentRiskFrames,
  type RiskFrameRef,
} from "@/components/Map/riskMap";
import type { DynamicWeatherFrame } from "@/components/Map/dynamicWeather";
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
// 降水短時間予報（改善計画T407）の再取得間隔。直近0〜6時間の"immed"系列が最も高頻度で
// 更新される部分（precipitationNowcast.ts: fetchRasrfFrames参照）に合わせる。
const RASRF_REFRESH_INTERVAL_MS = 10 * 60 * 1000;
// キキクル・線状降水帯予測マップ（改善計画T410）の再取得間隔。キキクルは10分おき更新
// （riskMap.tsのモジュールdocstring参照）に合わせる。
const RISK_MAP_REFRESH_INTERVAL_MS = 10 * 60 * 1000;

const EMPTY_RISK_FRAMES: DynamicWeatherFrame<RiskFrameRef>[] = [];
const EMPTY_CURRENT_RISK_FRAMES: CurrentRiskFrames = { land: EMPTY_RISK_FRAMES, heavyRain: EMPTY_RISK_FRAMES, inundation: EMPTY_RISK_FRAMES };

export interface UseDynamicWeatherLayersOptions {
  showWindVector: boolean;
  showPrecipitationNowcast: boolean;
  showThunderNowcast: boolean;
  showTornadoNowcast: boolean;
  showLandslideRisk: boolean;
  showHeavyRainRisk: boolean;
  showInundationRisk: boolean;
  showLinearRainbandRisk: boolean;
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
  showLandslideRisk,
  showHeavyRainRisk,
  showInundationRisk,
  showLinearRainbandRisk,
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

  // 降水短時間予報の時刻一覧（改善計画T407、60分〜15時間先）。「降水」チップの一部
  // （precipitationNowcast.ts: precipitationFrames参照）のため、ナウキャストと同じ
  // showPrecipitationNowcastで開閉する。取得失敗はnowcastと同じくエラーメッセージへ記録するが、
  // precipitationFramesがrasrfFrames=[]でも自然にextended予報へフォールバックするため、
  // 「降水」チップ自体は動作を続ける（フェイルソフト）。
  const [rasrfFrames, setRasrfFrames] = useState<RasrfFrame[]>([]);
  useEffect(() => {
    if (!showPrecipitationNowcast) return;
    let cancelled = false;
    const load = async () => {
      try {
        const frames = await fetchRasrfFrames();
        if (cancelled) return;
        setRasrfFrames(frames);
      } catch (error: unknown) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "降水短時間予報の取得に失敗しました";
        debugLog("api:jma-nowcast-times", "降水短時間予報の読み込みに失敗", { error: message }, "error");
      }
    };
    Promise.resolve().then(load);
    const intervalId = window.setInterval(load, RASRF_REFRESH_INTERVAL_MS);
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

  // キキクル（土砂・大雨・浸水、改善計画T410）の「現在」フレーム。3種で1本のtargetTimes.json
  // を共有するため（riskMap.ts参照）、いずれか1つでもONの間だけ1本のfetchでまとめて取得する
  // （thunderNowcastFramesと同じ考え方）。未来方向のフレームを持たないため取得失敗時も
  // nowcastのような「部分結果」は無く、フェッチ自体を諦めてエラーのみ記録する。
  const [currentRiskFrames, setCurrentRiskFrames] = useState<CurrentRiskFrames>(EMPTY_CURRENT_RISK_FRAMES);
  useEffect(() => {
    if (!showLandslideRisk && !showHeavyRainRisk && !showInundationRisk) return;
    let cancelled = false;
    const load = async () => {
      try {
        const frames = await fetchCurrentRiskFrames();
        if (cancelled) return;
        setCurrentRiskFrames(frames);
      } catch (error: unknown) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "危険度分布（キキクル）の取得に失敗しました";
        debugLog("api:jma-nowcast-times", "キキクルの読み込みに失敗", { error: message }, "error");
      }
    };
    Promise.resolve().then(load);
    const intervalId = window.setInterval(load, RISK_MAP_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [showLandslideRisk, showHeavyRainRisk, showInundationRisk]);

  // 線状降水帯予測マップ（改善計画T410）の「現在」フレーム。キキクルとはtargetTimes.json
  // 自体が別（rasrfのtargetTimes.jsonにelements違いの別行として混在、riskMap.ts参照）。
  const [linearRainbandFrames, setLinearRainbandFrames] = useState<DynamicWeatherFrame<RiskFrameRef>[]>(EMPTY_RISK_FRAMES);
  useEffect(() => {
    if (!showLinearRainbandRisk) return;
    let cancelled = false;
    const load = async () => {
      try {
        const frames = await fetchLinearRainbandFrames();
        if (cancelled) return;
        setLinearRainbandFrames(frames);
      } catch (error: unknown) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "線状降水帯予測マップの取得に失敗しました";
        debugLog("api:jma-nowcast-times", "線状降水帯予測マップの読み込みに失敗", { error: message }, "error");
      }
    };
    Promise.resolve().then(load);
    const intervalId = window.setInterval(load, RISK_MAP_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [showLinearRainbandRisk]);

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
  // キキクル3種+線状降水帯予測マップ（改善計画T410）。riskMap.tsが既にDynamicWeatherFrame
  // 形式で返すが、他レイヤーと異なり共有タイムライン・frameIndexForTimeには乗せない
  // （下記の理由）。
  const { land: landFramesList, heavyRain: heavyRainFramesList, inundation: inundationFramesList } = currentRiskFrames;

  // ONの全レイヤーのフレーム時刻を統合した共有タイムライン（T183再設計、実機フィードバック
  // 「時間経過はスライドバー1本で表現する」）。降水ナウキャスト（5分刻み）と風・延長予報
  // （1時間刻み）が混ざると、目盛りが「近い将来は細かく、遠い将来は粗い」を自然に実現する。
  // **キキクル・線状降水帯予測マップ（改善計画T410）はここに含めない**: frameIndexForTimeの
  // 範囲判定は`FRAME_RANGE_EPSILON_MS`（1秒）という狭い許容誤差で「選択中の時刻がこの
  // フレームの時刻とほぼ一致するか」を見る設計だが、これは「複数フレームの中から該当する
  // 1枚を選ぶ」用途（例: 5分刻みのナウキャストで正確な1枚を当てる）を想定したものであり、
  // 「常に1枚だけの現在値スナップショットを、10分に1回更新されるデータの鮮度のまま表示する」
  // キキクル系とは噛み合わない（実機確認: フレームのvalidtimeと実際の「今」の間には
  // 直近の更新から最大10分程度のズレが常にあり、1秒の許容誤差を必ず超える。実機で
  // このズレのせいで一切描画されない不具合を発見・修正した）。キキクル系はタイムラインとは
  // 別に「スライダーが『現在』位置にあるときだけ最新の1枚を表示し、未来側へ動かした間は
  // 非表示にする」（実機フィードバック「12時間後の雷が常時マップに警告されているのは嫌」、
  // 下記payload計算のisAtNow参照）。
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
  // キキクル・線状降水帯予測マップ（改善計画T410）。実機フィードバック「12時間後の雷が
  // 常時マップに警告されているのは嫌」: スライダーを未来へ動かしても常時表示したままだと、
  // 「現在」時点のスナップショットがあたかもその未来時刻の危険度であるかのように見えて
  // しまう。そのため他レイヤーのようなframeIndexForTimeによる時刻一致ではなく、
  // 「スライダーが『現在』位置にあるときだけ」表示する（sliderIndex/sliderCurrentIndexは
  // 同じtimelineに対するnearestTimeIndexの結果なので、一致=つまみが実質「現在」を指して
  // いる）。未来側へ動かした間はundefinedとなり非表示（frames自体は保持し続けるため、
  // 「現在」へ戻せば即座に再表示される）。
  const isAtNow = sliderIndex === sliderCurrentIndex;
  const landslideRiskPayload = useMemo(() => {
    if (!isAtNow) return undefined;
    const frame = landFramesList[0];
    return frame ? landRenderPayload(frame.ref) : undefined;
  }, [landFramesList, isAtNow]);
  const heavyRainRiskPayload = useMemo(() => {
    if (!isAtNow) return undefined;
    const frame = heavyRainFramesList[0];
    return frame ? heavyRainRenderPayload(frame.ref) : undefined;
  }, [heavyRainFramesList, isAtNow]);
  const inundationRiskPayload = useMemo(() => {
    if (!isAtNow) return undefined;
    const frame = inundationFramesList[0];
    return frame ? inundationRenderPayload(frame.ref) : undefined;
  }, [inundationFramesList, isAtNow]);
  const linearRainbandRiskPayload = useMemo(() => {
    if (!isAtNow) return undefined;
    const frame = linearRainbandFrames[0];
    return frame ? linearRainbandRenderPayload(frame.ref) : undefined;
  }, [linearRainbandFrames, isAtNow]);

  // MapViewへ渡す単一プロパティ（T183再設計、旧5個のprecipitation/wind個別propsを統合）。
  // 新しい動的気象要素を追加してもMapViewProps自体は変わらず、ここへ1エントリ足すだけでよい。
  const dynamicWeather = useMemo(
    () => ({
      windVector: { visible: showWindVector, payload: windPayload },
      precipitationNowcast: { visible: showPrecipitationNowcast, payload: precipitationPayload },
      thunderNowcast: { visible: showThunderNowcast, payload: thunderPayload },
      tornadoNowcast: { visible: showTornadoNowcast, payload: tornadoPayload },
      landslideRisk: { visible: showLandslideRisk, payload: landslideRiskPayload },
      heavyRainRisk: { visible: showHeavyRainRisk, payload: heavyRainRiskPayload },
      inundationRisk: { visible: showInundationRisk, payload: inundationRiskPayload },
      linearRainbandRisk: { visible: showLinearRainbandRisk, payload: linearRainbandRiskPayload },
    }),
    [
      showWindVector,
      windPayload,
      showPrecipitationNowcast,
      precipitationPayload,
      showThunderNowcast,
      thunderPayload,
      showTornadoNowcast,
      tornadoPayload,
      showLandslideRisk,
      landslideRiskPayload,
      showHeavyRainRisk,
      heavyRainRiskPayload,
      showInundationRisk,
      inundationRiskPayload,
      showLinearRainbandRisk,
      linearRainbandRiskPayload,
    ]
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
