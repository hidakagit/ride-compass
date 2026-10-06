"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import { SPLICED_ROUTE_ID_PREFIX } from "@/features/route/routeTabLabel";
import type { RouteCandidate, RoutePreferenceWeights, SelectedRouteSegment } from "@/types/route";

/** 「ルート結果」の比較タブの値（候補のタブの値は候補のid）。 */
export const COMPARISON_TAB = "comparison";

/** 区間の乗り換えで作ったルート。元にしたルートとは別の1本で、元を上書きしない。 */
export interface EditedRoute {
  route: RouteCandidate;
  /** 元にしたルートのid（生成した候補か、先に作った編集）。 */
  originId: string;
  /** 作った順の番号（1から）。画面の名前「合成N」に使う。 */
  number: number;
}

/**
 * 「ルート結果」の状態: 生成した候補・編集で作ったルート・選んだルート・地図で押した区間・比較タブを見ているか・
 * 生成に使われた重み。生成と区間の乗り換えが結果を入れ、「ルート結果」の部品と地図が読む。
 */
export function useRouteResults() {
  const [generated, setGenerated] = useState<RouteCandidate[]>([]);
  // 作った順。生成し直す・消すと一緒に消える（編集は元にした生成に結びつく）。
  const [edits, setEdits] = useState<EditedRoute[]>([]);
  // 次に作るルートの番号。足すときに選ぶidを同じ操作の中で決めるため、一覧の長さでなくここから振る（一覧と一緒に1へ戻す）。
  const nextEditNumber = useRef(1);
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
    setGenerated(generated);
    setEdits([]);
    nextEditNumber.current = 1;
    setSelectedRouteId(generated[0]?.id ?? null);
    // 比較を開いたまま生成したら新しい候補へ戻す（比較表が残ると、生成が効かなかったように見える）。
    setComparisonTabActive(false);
    // 候補が入れ替わると、押していた区間も意味を失う。
    setSelectedRouteSegment(null);
    setUsedWeights(routePreference);
  }, []);

  /** 区間の乗り換えで作ったルートを足して選ぶ。idは画面が振る（backendは同じ値を毎回返す）。 */
  const addEdit = useCallback((route: RouteCandidate, originId: string) => {
    const number = nextEditNumber.current++;
    const id = `${SPLICED_ROUTE_ID_PREFIX}-${number}`;
    setEdits((current) => [...current, { route: { ...route, id }, originId, number }]);
    setSelectedRouteId(id);
    setSelectedRouteSegment(null);
  }, []);

  /** 候補・選択・使われた重みを消す。 */
  const clear = useCallback(() => {
    setGenerated([]);
    setEdits([]);
    nextEditNumber.current = 1;
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

  const routes = useMemo(() => [...generated, ...edits.map((edit) => edit.route)], [generated, edits]);
  const selectedCandidate = routes.find((route) => route.id === selectedRouteId) ?? null;
  const selectedEdit = useMemo(() => {
    const edit = edits.find((item) => item.route.id === selectedRouteId);
    return edit ? { ...edit, origin: routes.find((route) => route.id === edit.originId) ?? null } : null;
  }, [edits, routes, selectedRouteId]);

  return {
    /** 生成した候補と編集で作ったルートの全部（どちらも選べ、乗り換えの相手にもなる）。 */
    routes,
    generated,
    edits,
    selectedRouteId,
    selectedCandidate,
    /** 選んだルートが編集で作ったものなら、その編集と元のルート。 */
    selectedEdit,
    /** 選んだ候補が区間の内訳を持つか（区間まで確定したか）。 */
    hasDetail: (selectedCandidate?.segments.length ?? 0) > 0,
    selectedRouteSegment,
    selectSegment: setSelectedRouteSegment,
    comparisonTabActive,
    usedWeights,
    replaceWithGenerated,
    addEdit,
    clear,
    selectTab,
  };
}

export type RouteResults = ReturnType<typeof useRouteResults>;
