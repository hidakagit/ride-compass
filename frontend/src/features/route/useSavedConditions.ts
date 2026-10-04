"use client";

import { useCallback, useMemo } from "react";

import { useStoredState } from "@/hooks/useStoredState";
import type { GenerationConditionsState } from "@/features/route/useGenerationConditions";
import {
  readSavedConditions,
  suggestedConditionName,
  withSavedCondition,
  type GenerationConditionsSnapshot,
  type SavedCondition,
} from "@/features/route/savedConditions";
import type { Coordinates } from "@/types/route";

// 保存先はこの端末のブラウザの中だけ（ログイン無しで使え、別の端末とは共有しない）。
const SAVED_CONDITIONS_STORAGE_KEY = "ridecompass:saved-conditions";

interface SavedConditionsInputs {
  conditions: GenerationConditionsState;
  /** いまの出発地（現在地か地図で置いた地点。位置が分からない間はnull）。 */
  origin: Coordinates | null;
  /** 出発地を地図で置いたか。 */
  originManual: boolean;
  /** 保存した出発地を地図で置いた出発地にする。 */
  onOriginPlace: (point: Coordinates) => void;
  /** 出発地を現在地へ戻す。 */
  onOriginFollowCurrent: () => void;
}

/** 名前を付けて保存した生成の条件の一覧と、いまの条件の保存・呼び出し・削除。 */
export function useSavedConditions({
  conditions,
  origin,
  originManual,
  onOriginPlace,
  onOriginFollowCurrent,
}: SavedConditionsInputs) {
  const [saved, setSaved] = useStoredState<SavedCondition[]>(SAVED_CONDITIONS_STORAGE_KEY, [], {
    serialize: (list) => JSON.stringify(list),
    deserialize: readSavedConditions,
  });

  // 出発地は保存のときに固定するかを選ぶので、ここには持たない。
  const current: Omit<GenerationConditionsSnapshot, "origin"> = useMemo(
    () => ({
      routeMode: conditions.routeMode,
      distance: conditions.distanceInput,
      maxRoutes: conditions.maxRoutesInput,
      waypoints: conditions.waypoints,
      destination: conditions.destination,
      routePreference: conditions.weightOverrideEnabled ? conditions.routePreference : null,
      hardFilters: conditions.hardFilters,
    }),
    [
      conditions.routeMode,
      conditions.distanceInput,
      conditions.maxRoutesInput,
      conditions.waypoints,
      conditions.destination,
      conditions.weightOverrideEnabled,
      conditions.routePreference,
      conditions.hardFilters,
    ],
  );
  const suggestedName = suggestedConditionName(current);

  // 名前が空なら仮の名前で保存する。固定しない出発地は、呼び出した時の現在地から作る印（null）で保存する。
  const save = useCallback(
    (name: string, fixOrigin: boolean) => {
      const entry = { ...current, origin: fixOrigin ? origin : null, name: name.trim() || suggestedName };
      setSaved((prev) => withSavedCondition(prev, entry));
    },
    [current, origin, suggestedName, setSaved],
  );

  const { restore } = conditions;
  const recall = useCallback(
    (entry: SavedCondition) => {
      restore(entry);
      if (entry.origin !== null) onOriginPlace(entry.origin);
      else if (originManual) onOriginFollowCurrent();
    },
    [restore, onOriginPlace, onOriginFollowCurrent, originManual],
  );

  const remove = useCallback(
    (name: string) => setSaved((prev) => prev.filter((entry) => entry.name !== name)),
    [setSaved],
  );

  return { saved, current, suggestedName, save, recall, remove };
}
