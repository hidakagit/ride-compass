"use client";

import { useCallback, useState } from "react";

import { debugLog } from "@/lib/debugLog";
import { useRouteFormSubmit } from "@/features/route/RouteForm/useRouteFormSubmit";
import {
  buildGenerateRequest,
  generationConditionsKey,
  type GenerationInput,
} from "@/features/route/generationRequest";
import { generateRoutes, type GenerationProgress } from "@/features/route/routeApi";
import { orderGenerated } from "@/features/route/routeTabLabel";
import type { GenerationConditionsState } from "@/features/route/useGenerationConditions";
import type { Coordinates, RouteCandidate, RoutePreferenceWeights } from "@/types/route";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

/** 押した「生成」の直近の結果。失敗は前の候補を残したまま出すため、候補0件の理由と分けて持つ。 */
type GenerationNotice = { kind: "failed" | "empty"; message: string };

/** ルート生成の進み方。同時に成り立つのは1つだけ。 */
type Generation =
  { status: "idle"; notice: GenerationNotice | null } | { status: "running"; progress: GenerationProgress | null };
const GENERATION_IDLE: Generation = { status: "idle", notice: null };

/** 表示中の候補を作ったときの条件。 */
interface GeneratedConditions {
  /** 送った入力から導いた比較のキー。いまのフォームから同じ関数で作ったキーと比べる。 */
  key: string;
  /** 目的地が道路網から外れていて、backendが最寄りの行ける地点へ補正したか。 */
  destinationCorrected: boolean;
  /** 利用者が重みを上書きしていたのに、軸カタログが無く送れなかったか（backendの既定の配分で探した）。 */
  weightsNotApplied: boolean;
  /** 送った入力そのもの。乗り換えで合成した経路も同じ条件で評価する。 */
  input: GenerationInput;
}

interface RouteGenerationInputs {
  conditions: GenerationConditionsState;
  origin: Coordinates;
  /** 出発地が実際の位置か（現在地を取れたか、地図で置いたか）。 */
  originKnown: boolean;
  departure: { at: Date; pinned: boolean };
  assumedSpeedKmh: number;
  /** 候補が並んでいるか（「条件が変わった」は比べる候補があるときだけ出す）。 */
  hasRoutes: boolean;
  /** 生成の結果（最速の1本を先頭に、残りを所要時間の短い順に並べた候補と、backendが生成に使った重み）。候補0件でも呼ぶ。 */
  onGenerated: (routes: RouteCandidate[], routePreference: RoutePreferenceWeights) => void;
  /** 押した「生成」の結果（候補・候補0件・失敗・入力の誤り）。どれも「ルート結果」でしか中身が見えない。 */
  onOutcome: (outcome: RouteOutcomeKind) => void;
}

/** 押した「生成」・「作成」の結果の種類。候補0件と失敗を、候補が出たことと見分ける。 */
export type RouteOutcomeKind = "fresh" | "empty" | "failed";

/**
 * ルート生成: 検証と送信、実行中の進み方、直近の案内（候補0件の理由・失敗の文言）、表示中の候補を作った条件と
 * いまのフォームのずれ。入力は生成と「条件が変わったか」の判定が同じ関数で組み立てる。
 */
export function useRouteGeneration({
  conditions,
  origin,
  originKnown,
  departure,
  assumedSpeedKmh,
  hasRoutes,
  onGenerated,
  onOutcome,
}: RouteGenerationInputs) {
  // 実行中は順番待ちか実行中かと経過時間をボタンへ出し、終わった後は直近の案内を「ルート結果」欄に残す。
  const [generation, setGeneration] = useState<Generation>(GENERATION_IDLE);
  const [generatedConditions, setGeneratedConditions] = useState<GeneratedConditions | null>(null);

  const { routePreferenceToSend } = conditions;
  const { routeMode, waypoints, destination, maxRoutes, hardFilters } = conditions.snapshot;
  // いまの条件から生成の入力を組み立てる。`destinationOverride`はbackendが補正した目的地。
  const buildCurrentGenerationInput = useCallback(
    (distanceKm: number, destinationOverride?: Coordinates): GenerationInput => {
      const effectiveDestination = destinationOverride ?? destination;
      const destinationModePoints =
        routeMode === "destination" ? [...waypoints, ...(effectiveDestination ? [effectiveDestination] : [])] : [];
      return {
        origin,
        // 点を置いたときの探索の範囲はbackendが点から決めるため、距離は送らない。
        distanceKm: routeMode === "destination" && destinationModePoints.length > 0 ? null : distanceKm,
        distanceToleranceKm: routeGenerateConfig.default_distance_tolerance_km,
        maxRoutes: Number(maxRoutes),
        assumedSpeedKmh,
        startTime: departure.at,
        startTimePinned: departure.pinned,
        hardFilters,
        routePreference: routePreferenceToSend,
        waypoints: routeMode === "destination" ? waypoints : [],
        destination: routeMode === "destination" ? effectiveDestination : null,
      };
    },
    [
      routeMode,
      waypoints,
      destination,
      origin,
      maxRoutes,
      assumedSpeedKmh,
      departure.at,
      departure.pinned,
      hardFilters,
      routePreferenceToSend,
    ],
  );

  // 表示中の候補を作った条件と、いまのフォームがずれているか（変えただけでは何も起きないことを知らせる）。
  const conditionsDirty =
    generatedConditions != null &&
    hasRoutes &&
    generationConditionsKey(buildCurrentGenerationInput(Number(conditions.snapshot.distance))) !==
      generatedConditions.key;

  async function generate(distanceKm: number) {
    setGeneration({ status: "running", progress: null });
    let notice: GenerationNotice | null = null;
    try {
      const generationInput = buildCurrentGenerationInput(distanceKm);
      const {
        routes: candidates,
        conditions: used,
        noCandidatesReason,
      } = await generateRoutes(buildGenerateRequest(generationInput), (progress) =>
        setGeneration({ status: "running", progress }),
      );
      // backendが目的地を補正したら、地図のピンも実際に使われた地点へ合わせる。待つ間に置き直したピンは、利用者が
      // 次に使う地点なので動かさない（送った目的地のままのときだけ書き換える）。
      const corrected = used.corrected_destination;
      if (corrected) {
        conditions.setDestination((current) => (current === generationInput.destination ? corrected : current));
      }
      // 一覧は最速の1本を先頭に、残りは所要時間の短い順。
      onGenerated(orderGenerated(candidates), used.route_preference);
      // 補正があったら補正後の地点で入力を組み直す（ピンも動かしたので、直後に「条件が変わった」にならない）。
      const generatedInput = used.corrected_destination
        ? buildCurrentGenerationInput(distanceKm, used.corrected_destination)
        : generationInput;
      setGeneratedConditions({
        key: generationConditionsKey(generatedInput),
        destinationCorrected: Boolean(used.corrected_destination),
        weightsNotApplied: conditions.weightOverrideEnabled && generatedInput.routePreference === null,
        input: generatedInput,
      });
      // 候補が出たことは「ルート結果」の一覧と合図で分かるので、案内は候補0件のときだけ持つ。
      if (candidates.length === 0) {
        notice = {
          kind: "empty",
          message: noCandidatesReason ?? "条件に合うルート候補が見つかりませんでした。条件を変えて試してください。",
        };
      }
      onOutcome(candidates.length > 0 ? "fresh" : "empty");
    } catch (error) {
      const message = error instanceof Error ? error.message : "不明なエラーが発生しました";
      notice = { kind: "failed", message };
      debugLog("api:route", "ルート生成ハンドラで例外", { error: message }, "error");
      onOutcome("failed");
    } finally {
      setGeneration({ status: "idle", notice });
    }
  }

  const routeFormSubmit = useRouteFormSubmit({
    distance: conditions.snapshot.distance,
    routeMode,
    waypointCount: waypoints.length,
    destinationSet: destination !== null,
    originKnown,
  });

  /** 検証して生成する。入力の誤りも押した結果として知らせる。 */
  async function submit() {
    const distanceKm = routeFormSubmit.check();
    if (distanceKm === null) onOutcome("failed");
    else await generate(distanceKm);
  }

  /** 直近の案内を消す（実行中なら何もしない）。 */
  const clearNotice = useCallback(
    () => setGeneration((current) => (current.status === "idle" ? GENERATION_IDLE : current)),
    [],
  );

  /** 生成の結果（作った条件・案内）を消す。 */
  const clear = useCallback(() => {
    setGeneratedConditions(null);
    // 消した候補に向けた作り直しの失敗は、生成前の案内の場所へ持ち越さない。
    clearNotice();
  }, [clearNotice]);

  const running = generation.status === "running";
  const progress = generation.status === "running" ? generation.progress : null;
  // 入力の誤りは生成の前に止まるので、直前の生成の結果より先に出す。
  const outcome: GenerationNotice | null = routeFormSubmit.error
    ? { kind: "failed", message: routeFormSubmit.error }
    : generation.status === "idle"
      ? generation.notice
      : null;

  return {
    submit,
    running,
    /** 実行中の進み方の文言（進み方がまだ届いていなければundefined）。 */
    progressLabel:
      progress?.status === "queued"
        ? "順番待ち..."
        : progress?.status === "running"
          ? `生成中...(${Math.round(progress.elapsedMs / 1000)}秒経過)`
          : undefined,
    /** 押した「生成」の直近の案内（候補0件の理由・入力の誤りか失敗）。候補が出たとき・実行中・まだ押していないときはnull。 */
    outcome,
    /** 押した「生成」が通らなかった理由（入力の誤り・生成の失敗）。候補がある間も、前の候補の上に出す。 */
    failure: outcome?.kind === "failed" ? outcome.message : null,
    conditionsDirty,
    destinationCorrected: generatedConditions?.destinationCorrected ?? false,
    weightsNotApplied: generatedConditions?.weightsNotApplied ?? false,
    /** 表示中の候補を作った生成の入力（生成していなければnull）。 */
    generatedInput: generatedConditions?.input ?? null,
    clearNotice,
    clear,
  };
}
