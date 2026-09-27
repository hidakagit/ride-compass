"use client";

import { useCallback, useEffect, useState } from "react";

import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { debugLog } from "@/lib/debugLog";
import { LENS_DIFFICULTY_ID, LENS_NONE_ID } from "@/lib/mapDisplay/routeStyleModes";
import { fixedRouteCount, useRouteFormSubmit } from "@/features/route/RouteForm/useRouteFormSubmit";
import {
  buildGenerateRequest,
  generationConditionsKey,
  type GenerationInput,
} from "@/features/route/generationRequest";
import { generateRoutes, type GenerationProgress } from "@/features/route/routeApi";
import { orderByDuration } from "@/features/route/routeTabLabel";
import type { GenerationConditionsState } from "@/features/route/useGenerationConditions";
import type { Coordinates, RouteCandidate, RoutePreferenceWeights } from "@/types/route";
import { EXPERIMENT_SLOT_COLORS, MAX_EXPERIMENT_SLOTS, type ExperimentSlot } from "@/types/experimentSlot";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

/** 直近の生成の案内。失敗は前の候補を残したまま出すため、候補0件の理由と分けて持つ。 */
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
  /** 送った入力そのもの。乗り換えで合成した経路も同じ条件で評価する。返ってきた条件（`conditions`）でなく入力を
   * 持つのは、そちらが塗る軸（`lens_axis_id`）を含まないため。 */
  input: GenerationInput;
}

interface RouteGenerationInputs {
  conditions: GenerationConditionsState;
  origin: Coordinates;
  /** 出発地が実際の位置か（現在地を取れたか、地図で置いたか）。 */
  originKnown: boolean;
  departure: { at: Date; pinned: boolean };
  assumedSpeedKmh: number;
  /** 地図のレンズ（塗る軸）。 */
  lens: string;
  /** 候補が並んでいるか（「条件が変わった」は比べる候補があるときだけ出す）。 */
  hasRoutes: boolean;
  /** 生成の結果（所要時間の短い順に並べた候補と、backendが生成に使った重み）。候補0件でも呼ぶ。 */
  onGenerated: (result: { routes: RouteCandidate[]; routePreference: RoutePreferenceWeights }) => void;
  /** 「ルート結果」でしか見えない結果（候補0件・失敗・入力の誤り）を知らせる。 */
  onOutcome: (outcome: "fresh" | "failed") => void;
}

/**
 * ルート生成: 検証と送信、実行中の進み方、直近の案内（候補0件の理由・失敗の文言）、表示中の候補を作った条件と
 * いまのフォームのずれ、研究モードの実験スロット。入力は生成と「条件が変わったか」の判定が同じ関数で組み立てる。
 */
export function useRouteGeneration({
  conditions,
  origin,
  originKnown,
  departure,
  assumedSpeedKmh,
  lens,
  hasRoutes,
  onGenerated,
  onOutcome,
}: RouteGenerationInputs) {
  const axisCatalog = useAxisCatalog();
  const researchEnabled = useResearchEnabled();
  // 実行中は順番待ちか実行中かと経過時間をボタンへ出し、終わった後は直近の案内を「ルート結果」欄に残す。
  const [generation, setGeneration] = useState<Generation>(GENERATION_IDLE);
  const [generatedConditions, setGeneratedConditions] = useState<GeneratedConditions | null>(null);
  // 実験スロット: 研究モードの生成結果の直近数件（地図の重ね描き・比較表）。
  const [experimentSlots, setExperimentSlots] = useState<ExperimentSlot[]>([]);

  const { routeMode, waypoints, destination, maxRoutesInput, hardFilters, routePreferenceToSend } = conditions;
  // いまのフォームから生成の入力を組み立てる。`destinationOverride`はbackendが補正した目的地。
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
        maxRoutes: fixedRouteCount(routeMode, waypoints.length) ?? Number(maxRoutesInput),
        assumedSpeedKmh,
        startTime: departure.at,
        startTimePinned: departure.pinned,
        hardFilters,
        // 軸カタログが届くまでは塗る軸を送らない（backendは知らない軸を黙って無視する）。
        lensAxisId: axisCatalog.loaded && lens !== LENS_NONE_ID && lens !== LENS_DIFFICULTY_ID ? lens : null,
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
      maxRoutesInput,
      assumedSpeedKmh,
      departure.at,
      departure.pinned,
      hardFilters,
      lens,
      axisCatalog.loaded,
      routePreferenceToSend,
    ],
  );

  // 表示中の候補を作った条件と、いまのフォームがずれているか（変えただけでは何も起きないことを知らせる）。
  const conditionsDirty =
    generatedConditions != null &&
    hasRoutes &&
    generationConditionsKey(buildCurrentGenerationInput(Number(conditions.distanceInput))) !== generatedConditions.key;

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
      // backendが目的地を補正したら、地図のピンも実際に使われた地点へ合わせる。
      if (used.corrected_destination) {
        conditions.setDestination(used.corrected_destination);
      }
      // 一覧は所要時間の短い順。
      onGenerated({ routes: orderByDuration(candidates), routePreference: used.route_preference });
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
      if (candidates.length === 0) {
        notice = {
          kind: "empty",
          message: noCandidatesReason ?? "条件に合うルート候補が見つかりませんでした。距離を変えて試してください。",
        };
        onOutcome("fresh");
      } else if (researchEnabled) {
        // 研究モードの生成だけを実験スロットへ残す。代表は難易度が最小の候補（backendの並びの先頭。一覧の並びとは別で、
        // 後で選び直しても変えない）。
        setExperimentSlots((prev) => {
          const next: ExperimentSlot = {
            id: `slot-${used.generated_at}-${Math.random().toString(36).slice(2, 8)}`,
            color: EXPERIMENT_SLOT_COLORS[0],
            conditions: used,
            topCandidate: candidates[0],
          };
          // 色は並びの位置で決める（最新が先頭の色）。
          return [next, ...prev]
            .slice(0, MAX_EXPERIMENT_SLOTS)
            .map((slot, i) => ({ ...slot, color: EXPERIMENT_SLOT_COLORS[i % EXPERIMENT_SLOT_COLORS.length] }));
        });
      }
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
    distance: conditions.distanceInput,
    routeMode,
    waypointCount: waypoints.length,
    destinationSet: destination !== null,
    originKnown,
    onGenerate: generate,
  });

  // 入力の検証の誤りも「ルート生成」を押した結果として同じく知らせる。
  useEffect(() => {
    if (routeFormSubmit.error) onOutcome("failed");
  }, [routeFormSubmit.error, onOutcome]);

  /** 直近の案内を消す（実行中なら何もしない）。 */
  const clearNotice = useCallback(
    () => setGeneration((current) => (current.status === "idle" ? GENERATION_IDLE : current)),
    [],
  );

  /** 生成の結果（作った条件・実験スロット・案内）を消す。 */
  const clear = useCallback(() => {
    setGeneratedConditions(null);
    setExperimentSlots([]);
    // 消した候補に向けた作り直しの失敗は、生成前の案内の場所へ持ち越さない。
    clearNotice();
  }, [clearNotice]);

  const running = generation.status === "running";
  const progress = generation.status === "running" ? generation.progress : null;

  return {
    submit: routeFormSubmit.handleSubmit,
    running,
    /** 順番待ちか（実行中のうち）。 */
    queued: progress?.status === "queued",
    /** 実行中の進み方の文言（進み方がまだ届いていなければundefined）。 */
    progressLabel:
      progress?.status === "queued"
        ? "順番待ち..."
        : progress?.status === "running"
          ? `生成中...(${Math.round(progress.elapsedMs / 1000)}秒経過)`
          : undefined,
    /** 押した「生成」が通らなかった理由（入力の誤り・生成の失敗）。候補がある間も、前の候補の上に出す。 */
    failure:
      routeFormSubmit.error ??
      (generation.status === "idle" && generation.notice?.kind === "failed" ? generation.notice.message : null),
    /** 候補が無いときに出す直近の案内（入力の誤りを先に）。 */
    lastMessage: routeFormSubmit.error ?? (generation.status === "idle" ? generation.notice?.message : undefined),
    conditionsDirty,
    destinationCorrected: generatedConditions?.destinationCorrected ?? false,
    weightsNotApplied: generatedConditions?.weightsNotApplied ?? false,
    /** 表示中の候補を作った生成の入力（生成していなければnull）。 */
    generatedInput: generatedConditions?.input ?? null,
    experimentSlots,
    clearNotice,
    clear,
  };
}
