"use client";

import { useCallback } from "react";

import { useStoredState } from "@/hooks/useStoredState";
import { readSavedPlaces, withSavedPlace, type SavedPlace } from "@/features/route/savedPlaces";

// 保存先はこの端末のブラウザの中だけ（保存した設定と同じ）。
const SAVED_PLACES_STORAGE_KEY = "ridecompass:saved-places";

/** 名前を付けて保存した地点の一覧と、保存・削除。 */
export function useSavedPlaces() {
  const [places, setPlaces] = useStoredState<SavedPlace[]>(SAVED_PLACES_STORAGE_KEY, [], {
    serialize: JSON.stringify,
    deserialize: readSavedPlaces,
  });

  const save = useCallback((place: SavedPlace) => setPlaces((prev) => withSavedPlace(prev, place)), [setPlaces]);

  const remove = useCallback(
    (place: SavedPlace) => setPlaces((prev) => prev.filter((saved) => saved.name !== place.name)),
    [setPlaces],
  );

  return { places, save, remove };
}

export type SavedPlacesState = ReturnType<typeof useSavedPlaces>;
