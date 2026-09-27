"use client";

import { useCallback, useMemo, useState } from "react";

import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { useStoredBooleanState, useStoredJsonState, useStoredState } from "@/hooks/useStoredState";
import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import type { RouteMode } from "@/features/route/RouteForm/useRouteFormSubmit";
import { syncHardFilterKeys } from "@/features/route/hardFilterSync";
import { alignRoutePreference, routePreferenceToSend } from "@/features/route/routePreferenceSync";
import type { Coordinates, HardFilterOverride, PinRole, RoutePreferenceWeights } from "@/types/route";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

const WEIGHT_OVERRIDE_ENABLED_STORAGE_KEY = "ridecompass:weight-override-enabled";
const ROUTE_PREFERENCE_STORAGE_KEY = "ridecompass:route-preference";
const HARD_FILTERS_STORAGE_KEY = "ridecompass:hard-filters";
// 「条件」タブの入力値。場所（目的地・経由地のピン）は持たない——行くたびに変わるうえ、
// 古いピンが残っていると気づかないまま生成してしまう。
const ROUTE_MODE_STORAGE_KEY = "ridecompass:route-mode";
const DISTANCE_STORAGE_KEY = "ridecompass:distance-km";
const MAX_ROUTES_STORAGE_KEY = "ridecompass:max-routes";

interface GenerationConditionsInputs {
  /** 地図で出発地を置いたとき（出発地は位置の取得と同じ持ち主が持つ）。 */
  onOriginPlace: (point: Coordinates) => void;
}

/**
 * 生成の条件（「ルート設定」の入力）: 周回か目的地か・距離・候補数・地点（出発地以外）・重み・除外と、地図のタップで
 * 置ける地点の役割。保存する値は、読むときに今の画面が受け付ける範囲・今の項目へ揃える。
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
  const clearWaypoints = useCallback(() => setWaypoints([]), []);

  // 目的地（あれば片道のルート）。
  const [destination, setDestination] = useState<Coordinates | null>(null);
  const clearDestination = useCallback(() => setDestination(null), []);
  // 地図のタップで置ける地点の役割（1つだけ）。無い間は地図を触ってもピンは増えない。
  const [armedPinRole, setArmedPinRole] = useState<PinRole | null>(null);

  // 周回か目的地か。切り替えても経由地・目的地は消さない（周回の間は地図に出さず送らないだけで、戻れば復元される）。
  const [routeMode, setRouteMode] = useStoredState<RouteMode>(ROUTE_MODE_STORAGE_KEY, "loop", {
    serialize: (mode) => mode,
    deserialize: (raw) => (raw === "loop" || raw === "destination" ? raw : null),
  });
  const changeRouteMode = useCallback(
    (mode: RouteMode) => {
      setRouteMode(mode);
      if (mode === "destination") {
        // 何も置いていなければ、次のタップで目的地を置けるようにする。既に置いてあれば、次のタップは経由地の
        // 追加かもしれないので自動では武装しない（目的地が意図せず上書きされる）。
        setArmedPinRole(destination === null && waypoints.length === 0 ? "destination" : null);
      } else {
        setArmedPinRole(null);
      }
    },
    [destination, waypoints.length, setRouteMode],
  );

  // 武装中の役割の地点として地図のタップを受ける。経由地だけは置いたあとも武装を続ける
  // （続けて何地点も置くのが普通の使い方で、1つ置くたびに押し直させない）。
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
      setWaypoints((prev) => [...prev, point]);
    },
    [onOriginPlace],
  );
  // 行を押して武装する。置いてある地点から武装しても値は残し、次のタップで置き換える（外してから置き直させない）。
  const armPinRole = useCallback((role: PinRole | null) => setArmedPinRole(role), []);

  // 距離の入力（文字列のまま）。表示中の候補を作った条件と比べて「生成条件が変更されています」を出すため、入力の形で持つ。
  const [distanceInput, setDistanceInput] = useStoredState(DISTANCE_STORAGE_KEY, "30", {
    serialize: (value) => value,
    // 保存値は画面の範囲内の数値だけを受け入れる（範囲が縮んだ後でも、範囲外の距離が復元されて送られない）。
    deserialize: (raw) => {
      const parsed = Number(raw);
      return Number.isFinite(parsed) && parsed >= 1 && parsed <= routeGenerateConfig.max_distance_km ? raw : null;
    },
  });
  // 候補数（文字列のまま、送るときに数へ）。
  const [maxRoutesInput, setMaxRoutesInput] = useStoredState(
    MAX_ROUTES_STORAGE_KEY,
    String(routeGenerateConfig.default_max_routes),
    {
      serialize: (value) => value,
      deserialize: (raw) => {
        const parsed = Number(raw);
        return Number.isInteger(parsed) && parsed >= 1 && parsed <= routeGenerateConfig.max_routes ? raw : null;
      },
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

  return {
    routeMode,
    changeRouteMode,
    distanceInput,
    setDistanceInput,
    maxRoutesInput,
    setMaxRoutesInput,
    waypoints,
    removeWaypoint,
    moveWaypoint,
    clearWaypoints,
    destination,
    setDestination,
    clearDestination,
    armedPinRole,
    armPinRole,
    placePin,
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
