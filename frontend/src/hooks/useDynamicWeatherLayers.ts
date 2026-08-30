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
import { windPenaltyGridToCellFeatureCollection } from "@/components/Map/windPenalty";
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
  isWithinFutureWindow,
  mergeFrameTimes,
  nearestTimeIndex,
  type DynamicWeatherGroupState,
  type DynamicWeatherLayerId,
  type DynamicWeatherRenderPayload,
} from "@/components/Map/dynamicWeather";
import type { DynamicLayerTimeSliderFrame } from "@/components/DynamicLayerTimeSlider/DynamicLayerTimeSlider";
import { useWeatherGrid } from "@/hooks/useWeatherGrid";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
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

// コンパススライダー（WindBearingSlider）はドラッグ中onChangeを連続発火するため、
// windBearingDegをそのままuseMemoの依存に使うとドラッグのたびにGeoJSON再構築＋MapView側の
// source.setData()が連打される。useDynamicWayValues.ts（改善計画T423で旧
// useWindAxisPenalties.tsから汎用化）のbearingDegデバウンスと同じ値を使う。
const WIND_BEARING_DEBOUNCE_MS = 500;

// 線状降水帯予測マップ（改善計画T432でrisk系統からrasrf系統・「降水」チップ傘下へ再分類）を
// 重ねて表示する時間窓。「今後3時間以内に大雨のおそれ」という予報の意味そのものに合わせる。
const LINEAR_RAINBAND_WINDOW_MS = 3 * 60 * 60 * 1000;

const EMPTY_RISK_FRAMES: DynamicWeatherFrame<RiskFrameRef>[] = [];
const EMPTY_CURRENT_RISK_FRAMES: CurrentRiskFrames = { land: EMPTY_RISK_FRAMES, heavyRain: EMPTY_RISK_FRAMES, inundation: EMPTY_RISK_FRAMES };

export interface UseDynamicWeatherLayersOptions {
  showWindVector: boolean;
  /** 改善計画T414: 評価軸グループとしての風（windAxis）とパラメータ入力を共有するための
   * ユーザー指定走行方位（コンパススライダー、0〜360度、北=0・時計回り）。「環境」グループの
   * 風penalty gridFill表示（windVectorグループのpenaltyFillソース）の計算に使う。 */
  windBearingDeg: number;
  /** 改善計画T432: 環境グループの風penalty gridFillの表示ON/OFF。windVectorのチップON/OFFとは
   * 独立（ルート確定後はページ側がfalseへ倒す想定、page.tsx:
   * showWindPenaltyFill = showWindVector && !hasDetail参照）。 */
  showWindPenaltyFill: boolean;
  showPrecipitationNowcast: boolean;
  showThunderNowcast: boolean;
  showTornadoNowcast: boolean;
  mapViewport: MapViewport | null;
}

export interface UseDynamicWeatherLayersResult {
  /** MapViewへそのまま渡す動的気象レイヤーのプロパティ（T183再設計、旧5個の個別props統合。
   * 改善計画T432でグループ内の複数ソース[raster/gridFill/gridMark]を同時に持てる形へ
   * 一般化した）。 */
  dynamicWeather: Partial<Record<DynamicWeatherLayerId, DynamicWeatherGroupState>>;
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
  /** 改善計画T414: windAxis（評価軸グループの風、backend API）が同じ[時刻]を共有するために
   * 公開する共有時刻そのもの（`at`クエリパラメータに使う）。 */
  dynamicLayerTargetTime: Date;
}

/** 動的気象レイヤー（降水ナウキャスト・風/延長降水予報・雷/竜巻ナウキャスト・キキクル）の
 * フェッチ・共有タイムライン・MapView向け描画ペイロードの管理（改善計画T375）。
 * 各要素は対応するshow*がtrueの間だけフェッチし、OFFの間はfetch自体しない
 * （他の外部APIと同じ「表示中のものだけ叩く」方針）。ただしキキクル3種（改善計画T432、
 * 「防災」カテゴリ）はWarningBadgeと同じ常時マウントのためこの方針の対象外——
 * showX系オプションを持たず常にフェッチする。 */
export function useDynamicWeatherLayers({
  showWindVector,
  windBearingDeg,
  showWindPenaltyFill,
  showPrecipitationNowcast,
  showThunderNowcast,
  showTornadoNowcast,
  mapViewport,
}: UseDynamicWeatherLayersOptions): UseDynamicWeatherLayersResult {
  // 動的気象レイヤーが指す対象時刻（T183再設計）。ONの全レイヤーのフレーム時刻を統合した
  // 1本のタイムライン（下記timeline）上の1点で、各レイヤーはこの時刻に対応する自分の
  // フレームを描画する。
  const [dynamicLayerTargetTime, setDynamicLayerTargetTime] = useState(() => new Date());
  const debouncedWindBearingDeg = useDebouncedValue(windBearingDeg, WIND_BEARING_DEBOUNCE_MS);

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
  // を共有するため（riskMap.ts参照）1本のfetchでまとめて取得する（thunderNowcastFramesと
  // 同じ考え方）。改善計画T432: 「防災」カテゴリとしてWarningBadgeと同じ常時マウントに
  // したため、show*ガードを持たずマウント時に常にフェッチする。未来方向のフレームを
  // 持たないため取得失敗時もnowcastのような「部分結果」は無く、フェッチ自体を諦めて
  // エラーのみ記録する。
  const [currentRiskFrames, setCurrentRiskFrames] = useState<CurrentRiskFrames>(EMPTY_CURRENT_RISK_FRAMES);
  // 改善計画T425（ゼロベース網羅レビュー指摘）: 以前はエラーをdebugLogへ記録するのみで
  // dynamicLayerErrorへ反映しておらず、キキクル（「防災」カテゴリ、常時マウント）の取得が
  // 失敗してもユーザーへ一切可視化されなかった。
  const [currentRiskError, setCurrentRiskError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const frames = await fetchCurrentRiskFrames();
        if (cancelled) return;
        setCurrentRiskFrames(frames);
        setCurrentRiskError(null);
      } catch (error: unknown) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "危険度分布（キキクル）の取得に失敗しました";
        debugLog("api:jma-nowcast-times", "キキクルの読み込みに失敗", { error: message }, "error");
        setCurrentRiskError(message);
      }
    };
    Promise.resolve().then(load);
    const intervalId = window.setInterval(load, RISK_MAP_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  // 線状降水帯予測マップ（改善計画T410、T432で「降水」チップ傘下へ再分類）の「現在」フレーム。
  // キキクルとはtargetTimes.json自体が別（rasrfのtargetTimes.jsonにelements違いの別行として
  // 混在、riskMap.ts参照）。「降水」チップ（showPrecipitationNowcast）に連動する。
  const [linearRainbandFrames, setLinearRainbandFrames] = useState<DynamicWeatherFrame<RiskFrameRef>[]>(EMPTY_RISK_FRAMES);
  // 改善計画T425（ゼロベース網羅レビュー指摘）: currentRiskErrorと同じ理由でdynamicLayerErrorへ
  // 反映する（線状降水帯予測マップは「降水」チップ配下のためshowPrecipitationNowcast連動）。
  const [linearRainbandError, setLinearRainbandError] = useState<string | null>(null);
  useEffect(() => {
    if (!showPrecipitationNowcast) return;
    let cancelled = false;
    const load = async () => {
      try {
        const frames = await fetchLinearRainbandFrames();
        if (cancelled) return;
        setLinearRainbandFrames(frames);
        setLinearRainbandError(null);
      } catch (error: unknown) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "線状降水帯予測マップの取得に失敗しました";
        debugLog("api:jma-nowcast-times", "線状降水帯予測マップの読み込みに失敗", { error: message }, "error");
        setLinearRainbandError(message);
      }
    };
    Promise.resolve().then(load);
    const intervalId = window.setInterval(load, RISK_MAP_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [showPrecipitationNowcast]);

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
  // このズレのせいで一切描画されない不具合を発見・修正した）。改善計画T432:
  // キキクル3種（土砂・大雨・浸水）は「防災」カテゴリとして常時マウントへ変更したため、
  // タイムラインとの連動自体が無くなった（frames[0]があれば常に表示、下記payload計算
  // 参照）。線状降水帯予測マップだけは「今後3時間以内」という予報の性質上、共有タイムラインの
  // 選択時刻が現在〜3時間先の範囲内かどうかで表示を切り替える（isWithinFutureWindow、
  // dynamicWeather.ts参照）。
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
  // 環境グループの風penalty gridFill（改善計画T414、T432でDynamicWeatherRenderPayload型へ
  // 統一）。windPayload（矢印gridMark）と同じframeIndexForTime（同じwindFramesList・同じ
  // dynamicLayerTargetTime）を使うため、両者は常に同じ時刻のデータを指す。windBearingDegは
  // ユーザー指定の走行方位（全格子点共通）、デバウンス済みの値を使う
  // （WIND_BEARING_DEBOUNCE_MS参照）。
  const windPenaltyPayload = useMemo((): DynamicWeatherRenderPayload | undefined => {
    const index = frameIndexForTime(windFramesList, dynamicLayerTargetTime);
    if (index == null || effectiveWindGrid.length === 0) return undefined;
    return {
      kind: "gridFill",
      geojson: windPenaltyGridToCellFeatureCollection(
        effectiveWindGrid,
        windFramesList[index].ref,
        debouncedWindBearingDeg,
        effectiveGridSpacingDeg
      ),
    };
  }, [windFramesList, dynamicLayerTargetTime, effectiveWindGrid, debouncedWindBearingDeg, effectiveGridSpacingDeg]);
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
  // キキクル（改善計画T410、T432で「防災」カテゴリとして常時マウントへ変更）。isAtNow
  // ゲーティング（スライダーが「現在」位置にあるときだけ表示）は撤回した——キキクル3種は
  // もはやどのUIコントロール（チップ・スライダー）とも接続されず、WarningBadgeと同じ
  // 「常に現在値だけ見せる」独立表示になったため、「未来のスライダー位置で古いスナップ
  // ショットが誤解を招く」という当時（T410）の懸念は構造的に発生しない。frames[0]が
  // あれば常に表示する。
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

  // MapViewへ渡す単一プロパティ（T183再設計、旧5個のprecipitation/wind個別propsを統合。
  // 改善計画T432でグループ内に複数の名前付きソースを持てる形へ一般化した——windVectorは
  // 矢印[arrow]とpenalty面[penaltyFill]、precipitationNowcastは時系列3段[main]と線状降水帯
  // [linearRainband]を同時に持つ）。新しい動的気象要素を追加してもMapViewProps自体は
  // 変わらず、ここへ1エントリ足すだけでよい。
  const dynamicWeather = useMemo(
    () => ({
      windVector: {
        arrow: { visible: showWindVector, payload: windPayload },
        penaltyFill: { visible: showWindPenaltyFill, payload: windPenaltyPayload },
      },
      precipitationNowcast: {
        main: { visible: showPrecipitationNowcast, payload: precipitationPayload },
        linearRainband: { visible: showPrecipitationNowcast, payload: linearRainbandPayload },
      },
      thunderNowcast: { main: { visible: showThunderNowcast, payload: thunderPayload } },
      tornadoNowcast: { main: { visible: showTornadoNowcast, payload: tornadoPayload } },
      landslideRisk: { main: { visible: true, payload: landslideRiskPayload } },
      heavyRainRisk: { main: { visible: true, payload: heavyRainRiskPayload } },
      inundationRisk: { main: { visible: true, payload: inundationRiskPayload } },
    }),
    [
      showWindVector,
      windPayload,
      showWindPenaltyFill,
      windPenaltyPayload,
      showPrecipitationNowcast,
      precipitationPayload,
      linearRainbandPayload,
      showThunderNowcast,
      thunderPayload,
      showTornadoNowcast,
      tornadoPayload,
      landslideRiskPayload,
      heavyRainRiskPayload,
      inundationRiskPayload,
    ]
  );

  // 共有スライダーのloading/error表示。windLoading/windErrorは両要素が使う格子点フェッチ
  // （useWeatherGrid、ONのどちらか一方でも走る）、nowcastLoading/nowcastErrorは降水ナウキャスト
  // 固有のフェッチ、thunderNowcastLoading/thunderNowcastErrorは雷・竜巻共有のフェッチ。
  // 風のみONならnowcast/thunderの状態は無関係（フェッチ自体走らない）。currentRiskError
  // （キキクル）はshow*ガードを持たず常時マウントのため無条件に含める。linearRainbandError
  // （線状降水帯予測マップ）は「降水」チップ配下のためshowPrecipitationNowcast連動
  // （改善計画T425、以前はどちらもdynamicLayerErrorに含まれずエラーがユーザーへ不可視だった）。
  const dynamicLayerLoading =
    windLoading || (showPrecipitationNowcast && nowcastLoading) || ((showThunderNowcast || showTornadoNowcast) && thunderNowcastLoading);
  const dynamicLayerError =
    windError ??
    (showPrecipitationNowcast ? nowcastError : null) ??
    (showThunderNowcast || showTornadoNowcast ? thunderNowcastError : null) ??
    currentRiskError ??
    (showPrecipitationNowcast ? linearRainbandError : null);

  return {
    dynamicWeather,
    sliderFrames,
    sliderIndex,
    sliderCurrentIndex,
    handleSliderIndexChange,
    handleDynamicLayerNow,
    dynamicLayerLoading,
    dynamicLayerError,
    dynamicLayerTargetTime,
  };
}
