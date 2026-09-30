"use client";

import { useCallback, useState } from "react";

import type { RouteCandidate, RoutePreferenceWeights, SelectedRouteSegment } from "@/types/route";

/** 「ルート結果」の比較タブの値（候補のタブの値は候補のid）。 */
export const COMPARISON_TAB = "comparison";

/**
 * 「ルート結果」の状態: 候補の一覧・選んだ候補・地図で押した区間・比較タブを見ているか・生成に使われた重み。
 * 生成と区間の乗り換えが結果を入れ、「ルート結果」の部品と地図が読む。
 */
export function useRouteResults() {
  const [routes, setRoutes] = useState<RouteCandidate[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  // 地図で押した区間。ある間、「ルート結果」はルート全体の代わりにこの区間の内訳を出す。候補を切り替える・
  // 作り直す・消すと外す（別の候補の区間を指したまま残らない）。
  const [selectedRouteSegment, setSelectedRouteSegment] = useState<SelectedRouteSegment | null>(null);
  // 「比較」タブを見ているか。選んだ候補は比較を見ている間も保ち、戻ったときにそのまま選ばれている。
  const [comparisonTabActive, setComparisonTabActive] = useState(false);
  // 生成に使われた重み（利用者の重みは生成後も変わりうる）。
  const [usedWeights, setUsedWeights] = useState<RoutePreferenceWeights | null>(null);

  /** 生成の結果で一覧を入れ替える。最初に選ぶのは先頭（最も早く着く候補）。 */
  const replaceWithGenerated = useCallback((generated: RouteCandidate[], routePreference: RoutePreferenceWeights) => {
    setRoutes(generated);
    setSelectedRouteId(generated[0]?.id ?? null);
    // 比較を開いたまま生成したら新しい候補へ戻す（比較表が残ると、生成が効かなかったように見える）。
    setComparisonTabActive(false);
    // 候補が入れ替わると、押していた区間も意味を失う。
    setSelectedRouteSegment(null);
    setUsedWeights(routePreference);
  }, []);

  /** 作った経路を入れた一覧へ替え、指定の候補を選ぶ（区間の乗り換え）。 */
  const replaceAndSelect = useCallback((next: RouteCandidate[], routeId: string) => {
    setRoutes(next);
    setSelectedRouteId(routeId);
    setSelectedRouteSegment(null);
  }, []);

  /** 候補・選択・使われた重みを消す。 */
  const clear = useCallback(() => {
    setRoutes([]);
    setSelectedRouteId(null);
    setComparisonTabActive(false);
    setUsedWeights(null);
    setSelectedRouteSegment(null);
  }, []);

  /** 候補のタブか比較タブを選ぶ。どちらでも押していた区間は外す。 */
  const selectTab = useCallback((value: string) => {
    setSelectedRouteSegment(null);
    if (value === COMPARISON_TAB) {
      setComparisonTabActive(true);
    } else {
      setComparisonTabActive(false);
      setSelectedRouteId(value);
    }
  }, []);

  const selectedCandidate = routes.find((route) => route.id === selectedRouteId) ?? null;

  return {
    routes,
    selectedRouteId,
    selectedCandidate,
    /** 選んだ候補が区間の内訳を持つか（区間まで確定したか）。 */
    hasDetail: (selectedCandidate?.segments.length ?? 0) > 0,
    selectedRouteSegment,
    selectSegment: setSelectedRouteSegment,
    comparisonTabActive,
    usedWeights,
    replaceWithGenerated,
    replaceAndSelect,
    clear,
    selectTab,
  };
}

export type RouteResults = ReturnType<typeof useRouteResults>;
