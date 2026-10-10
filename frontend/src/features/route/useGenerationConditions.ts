"use client";

import { useCallback, useMemo, useState } from "react";

import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { useStoredBooleanState, useStoredJsonState, useStoredState } from "@/hooks/useStoredState";
import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import { syncHardFilterKeys } from "@/features/route/hardFilterSync";
import { alignRoutePreference, routePreferenceToSend } from "@/features/route/routePreferenceSync";
import {
  acceptedDistanceInput,
  acceptedMaxRoutesInput,
  type GenerationConditionsSnapshot,
} from "@/features/route/savedConditions";
import type { Coordinates, HardFilterOverride, PinRole, PlaceCandidate, RoutePreferenceWeights } from "@/types/route";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

const WEIGHT_OVERRIDE_ENABLED_STORAGE_KEY = "ridecompass:weight-override-enabled";
const ROUTE_PREFERENCE_STORAGE_KEY = "ridecompass:route-preference";
const HARD_FILTERS_STORAGE_KEY = "ridecompass:hard-filters";
// 「条件」タブの入力値。場所（目的地・経由地のピン）は持たない——行くたびに変わるうえ、
// 古いピンが残っていると気づかないまま生成してしまう。
const DISTANCE_TARGETED_STORAGE_KEY = "ridecompass:distance-targeted";
const DISTANCE_STORAGE_KEY = "ridecompass:distance-km";
const MAX_ROUTES_STORAGE_KEY = "ridecompass:max-routes";

/** 形の項目ごとに入れ方を呼ぶ。入れ方の表は形と同じキーを全部持つ型なので、形に項目を足すと入れ方が要る。 */
function applyEachField<T extends object>(apply: { [K in keyof T]-?: (value: T[K]) => void }, value: T) {
  for (const key in apply) apply[key](value[key]);
}

interface GenerationConditionsInputs {
  /** 地図で出発地を置いたとき（出発地は位置の取得と同じ持ち主が持つ）。 */
  onOriginPlace: (point: Coordinates) => void;
}

/**
 * 生成の条件（「ルート設定」の入力）: 全長の目標を決めるか・距離・候補数・地点（出発地以外）・重み・除外と、地図のタップで
 * 置ける地点の役割と、保存した条件での入れ替え。保存する値は、読むときに今の画面が受け付ける範囲・今の項目へ揃える。
 */
export function useGenerationConditions({ onOriginPlace }: GenerationConditionsInputs) {
  const axisCatalog = useAxisCatalog();

  // 経由地（通る順）。
  const [waypoints, setWaypoints] = useState<Coordinates[]>([]);
  const removeWaypoint = useCallback((index: number) => {
    setWaypoints((prev) => prev.filter((_, i) => i !== index));
  }, []);
  const moveWaypoint = useCallback((index: number, point: Coordinates) => {
    setWaypoints((prev) => prev.map((current, i) => (i === index ? point : current)));
  }, []);

  // 目的地（あれば片道のルート）。
  const [destination, setDestination] = useState<Coordinates | null>(null);
  const clearDestination = useCallback(() => setDestination(null), []);
  // 地図のタップで置ける地点の役割（1つだけ）。無い間は地図を触ってもピンは増えない。利用者が置く操作を押したときだけ
  // 入れる——押さずに置けると、地図を見ているだけのつもりの操作で地点が置かれる。
  const [armedPinRole, setArmedPinRole] = useState<PinRole | null>(null);

  // 経由地を武装したとき、地図のタップで置き直す経由地（何番目か）。無ければタップは経由地を足す。
  const [replacingWaypoint, setReplacingWaypoint] = useState<number | null>(null);
  const waypointToReplace = armedPinRole === "waypoint" ? replacingWaypoint : null;

  // 武装中の役割の地点として地図のタップを受ける。経由地を足す間だけは置いたあとも武装を続ける
  // （続けて何地点も置くのが普通の使い方で、1つ置くたびに押し直させない）。上限に達したら武装を解く（解けた操作は押せないので、
  // 超える点は置かれない）。
  const placePin = useCallback(
    (role: PinRole, point: Coordinates) => {
      if (role === "origin") {
        onOriginPlace(point);
        setArmedPinRole(null);
        return;
      }
      if (role === "destination") {
        setDestination(point);
        setArmedPinRole(null);
        return;
      }
      if (waypointToReplace !== null) {
        moveWaypoint(waypointToReplace, point);
        setArmedPinRole(null);
        return;
      }
      setWaypoints((prev) => [...prev, point]);
      if (waypoints.length + 1 >= routeGenerateConfig.max_waypoints) setArmedPinRole(null);
    },
    [onOriginPlace, moveWaypoint, waypointToReplace, waypoints.length],
  );
  // 検索で置いた地点の候補。名前を出すのは、その地点がまだ候補の位置にある間だけ（ピンを動かす・地図で置き直すと、
  // 名前の所ではなくなる）。
  const [found, setFound] = useState<PlaceCandidate[]>([]);
  // 検索・地図の小窓で選んだ地点を置く（経由地は`waypointIndex`番目を置き直し、無ければ足す——地図で置き直す経由地を
  // 選んでいる途中でも、それは置き直さない）。地図のタップで置く状態は解く（次のタップで意図しない地点が置かれる）。
  const placeFound = useCallback(
    (role: PinRole, candidate: PlaceCandidate, waypointIndex: number | null) => {
      const point = { latitude: candidate.latitude, longitude: candidate.longitude };
      if (role !== "waypoint") placePin(role, point);
      else if (waypointIndex !== null) moveWaypoint(waypointIndex, point);
      else setWaypoints((prev) => [...prev, point]);
      setArmedPinRole(null);
      setFound((prev) => [...prev, candidate]);
    },
    [moveWaypoint, placePin],
  );
  /** 地点`at`が検索で置いたときの位置のままなら、その候補。 */
  const foundAt = useCallback(
    (at: Coordinates | null): PlaceCandidate | null =>
      at === null
        ? null
        : (found.findLast((candidate) => candidate.latitude === at.latitude && candidate.longitude === at.longitude) ??
          null),
    [found],
  );
  // 地図で置く操作を押して武装する（経由地は`waypointIndex`番目を置き直し、無ければ足す）。置いてある地点から武装しても値は
  // 残し、次のタップで置き換える（外してから置き直させない）。
  const armPinRole = useCallback((role: PinRole | null, waypointIndex: number | null = null) => {
    setArmedPinRole(role);
    setReplacingWaypoint(waypointIndex);
  }, []);
  // 経由地と目的地を一度に消す。地図のタップで置く状態も解く（消した地点を置き直す途中のまま残さない）。
  const clearPoints = useCallback(() => {
    setWaypoints([]);
    setDestination(null);
    armPinRole(null);
  }, [armPinRole]);

  // 全長の目標を決めるか。外すと距離を送らず、置いた地点へ良い道で向かう。
  const [distanceTargeted, setDistanceTargeted] = useStoredBooleanState(DISTANCE_TARGETED_STORAGE_KEY, true);

  // 距離の入力（文字列のまま）。表示中の候補を作った条件と比べて「生成条件が変更されています」を出すため、入力の形で持つ。
  const [distanceInput, setDistanceInput] = useStoredState(DISTANCE_STORAGE_KEY, "30", {
    serialize: (value) => value,
    deserialize: acceptedDistanceInput,
  });
  // 候補数（文字列のまま、送るときに数へ）。
  const [maxRoutesInput, setMaxRoutesInput] = useStoredState(
    MAX_ROUTES_STORAGE_KEY,
    String(routeGenerateConfig.default_max_routes),
    {
      serialize: (value) => value,
      deserialize: acceptedMaxRoutesInput,
    },
  );

  // 重みを上書きして送るか。OFFの間は重みを送らず、backendの既定で探す。重みを操作するとONになる。
  const [weightOverrideEnabled, setWeightOverrideEnabled] = useStoredBooleanState(
    WEIGHT_OVERRIDE_ENABLED_STORAGE_KEY,
    false,
  );
  // 初期値は空。既定の重みは実行時の軸カタログが配り、下で揃えるときに補う（ビルド時の写しを初期値にすると、
  // 軸の増減が次のデプロイまで届かない）。
  const [storedRoutePreference, setRoutePreference] = useStoredJsonState<RoutePreferenceWeights>(
    ROUTE_PREFERENCE_STORAGE_KEY,
    {},
  );
  // 画面が読む重みは、軸カタログの公開軸へ揃えたこの値だけ（保存値は次に重みを動かしたときに揃った形で書かれる）。
  const routePreference = useMemo(
    () => alignRoutePreference(storedRoutePreference, axisCatalog),
    [storedRoutePreference, axisCatalog],
  );
  // 除外の設定。常に送る。保存値に今は無い項目が混じっていても、読むときに今の項目へ揃える。
  const [hardFilters, setHardFilters] = useStoredState<HardFilterOverride>(
    HARD_FILTERS_STORAGE_KEY,
    DEFAULT_HARD_FILTERS,
    {
      serialize: (value) => JSON.stringify(value),
      deserialize: (raw) => {
        try {
          return syncHardFilterKeys(JSON.parse(raw) as HardFilterOverride, DEFAULT_HARD_FILTERS);
        } catch {
          return null;
        }
      },
    },
  );

  // いまの条件を、保存・呼び出しと同じ形1つで返す（保存・生成の入力・保存の説明はこれを読む）。
  const snapshot: GenerationConditionsSnapshot = useMemo(
    () => ({
      distanceTargeted,
      distance: distanceInput,
      maxRoutes: maxRoutesInput,
      waypoints,
      destination,
      routePreference: weightOverrideEnabled ? routePreference : null,
      hardFilters,
    }),
    [
      distanceTargeted,
      distanceInput,
      maxRoutesInput,
      waypoints,
      destination,
      weightOverrideEnabled,
      routePreference,
      hardFilters,
    ],
  );

  // 保存した条件で入れ替える（出発地は位置の持ち主が受け取るので、呼び出し側が渡す）。地点を入れ替えたので、置ける役割は
  // 選び直させる。
  const restore = useCallback(
    (saved: GenerationConditionsSnapshot) => {
      applyEachField<GenerationConditionsSnapshot>(
        {
          distanceTargeted: setDistanceTargeted,
          distance: setDistanceInput,
          maxRoutes: setMaxRoutesInput,
          waypoints: setWaypoints,
          destination: setDestination,
          routePreference: (weights) => {
            if (weights !== null) setRoutePreference(weights);
            setWeightOverrideEnabled(weights !== null);
          },
          hardFilters: setHardFilters,
        },
        saved,
      );
      setArmedPinRole(null);
    },
    [
      setDistanceTargeted,
      setDistanceInput,
      setMaxRoutesInput,
      setRoutePreference,
      setWeightOverrideEnabled,
      setHardFilters,
    ],
  );

  return {
    snapshot,
    restore,
    distanceTargeted,
    setDistanceTargeted,
    distanceInput,
    setDistanceInput,
    maxRoutesInput,
    setMaxRoutesInput,
    waypoints,
    removeWaypoint,
    moveWaypoint,
    destination,
    setDestination,
    clearDestination,
    clearPoints,
    armedPinRole,
    waypointToReplace,
    armPinRole,
    placePin,
    placeFound,
    foundAt,
    weightOverrideEnabled,
    setWeightOverrideEnabled,
    routePreference,
    setRoutePreference,
    /** 生成リクエストと道の評価へ載せる重み（上書きしていない間・軸カタログが無い間はnull）。 */
    routePreferenceToSend: routePreferenceToSend(routePreference, axisCatalog.loaded, weightOverrideEnabled),
    hardFilters,
    setHardFilters,
  };
}

export type GenerationConditionsState = ReturnType<typeof useGenerationConditions>;
