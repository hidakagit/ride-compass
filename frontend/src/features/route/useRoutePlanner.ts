"use client";

import { useCallback } from "react";

import { useRouteGeneration, type RouteOutcomeKind } from "@/features/route/useRouteGeneration";
import { useRouteResults } from "@/features/route/useRouteResults";
import { useSpliceSession } from "@/features/route/useSpliceSession";
import type { GenerationConditionsState } from "@/features/route/useGenerationConditions";
import type { Coordinates } from "@/types/route";

interface RoutePlannerInputs {
  conditions: GenerationConditionsState;
  origin: Coordinates;
  /** 出発地が実際の位置か（現在地を取れたか、地図で置いたか）。 */
  originKnown: boolean;
  departure: { at: Date; pinned: boolean };
  assumedSpeedKmh: number;
  /** 「ルート結果」でしか中身が見えない結果が出た（生成の結果・入力の誤り・乗り換えで作った経路）。押した操作1回に1度。 */
  onOutcome: (outcome: RouteOutcomeKind) => void;
}

/**
 * ルートを作る機能の入口: 結果（`useRouteResults`）・生成（`useRouteGeneration`）・区間の乗り換え（`useSpliceSession`）を
 * つなぐ。生成と乗り換えが作った候補を結果へ入れ、全消去は結果と生成の両方を消す（乗り換えの編集は生成に結びつくので
 * 一緒に終わる）。乗り換えで作り始めると、直前の生成の失敗の文言を残さない。
 */
export function useRoutePlanner({ conditions, onOutcome, ...generationInputs }: RoutePlannerInputs) {
  const results = useRouteResults();
  const { replaceWithGenerated, replaceAndSelect, clear: clearResults } = results;

  const generation = useRouteGeneration({
    conditions,
    ...generationInputs,
    hasRoutes: results.routes.length > 0,
    onGenerated: replaceWithGenerated,
    onOutcome,
  });
  const { clear: clearGeneration, clearNotice } = generation;

  const splice = useSpliceSession({
    routes: results.routes,
    generatedInput: generation.generatedInput,
    hasSelectedRoute: results.selectedCandidate !== null,
    onApplyStart: clearNotice,
    onApplied: ({ routes, selectedRouteId }) => {
      replaceAndSelect(routes, selectedRouteId);
      onOutcome("fresh");
    },
  });

  /** 生成したルート（候補・選択・作った条件・実験スロット・案内）を消す。地点のピンは消さない。実験スロットも地図へ
   * 重ね描きされるので一緒に消す（押した見た目どおり地図が空になる）。 */
  const clear = useCallback(() => {
    clearResults();
    clearGeneration();
  }, [clearResults, clearGeneration]);

  return {
    results,
    generation,
    splice,
    clear,
    /** 軸を「未使用」と分ける重み。生成に使われた重みで、生成前は今の設定の重み（重みタブが薄く出す軸と同じ軸になる）。 */
    routeWeights: results.usedWeights ?? conditions.routePreference,
  };
}
