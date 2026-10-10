"use client";

import { useMemo, useState } from "react";

import { useStoredState } from "@/hooks/useStoredState";
import { useDepartureTime } from "@/features/conditions/useDepartureTime";
import { clampSpeedKmh } from "@/features/conditions/rideConditions";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

// 走行条件のうち想定速度だけを保つ（出発時刻・走行方位は行くたびに変わる）。
const ASSUMED_SPEED_STORAGE_KEY = "ridecompass:assumed-speed-kmh";

/**
 * 走行条件（走行方位・出発時刻・想定速度）。地図の見え方・生成リクエスト・道の詳細が同じ値を読む。
 * 想定速度は区間の通過予定時刻・到達予想時刻の基準になるため、どのモードの生成でも送る。
 */
export function useRideConditions() {
  const [bearingDeg, setBearingDeg] = useState(0);
  const departure = useDepartureTime();
  const [speedKmh, setSpeedKmh] = useStoredState<number>(
    ASSUMED_SPEED_STORAGE_KEY,
    routeGenerateConfig.default_assumed_speed_kmh,
    {
      serialize: String,
      // 保存値は画面の範囲内の整数だけを受け入れる（範囲が縮んだ後でも、範囲外の速度が復元されて送られない）。
      deserialize: (raw) => {
        const parsed = Number(raw);
        return clampSpeedKmh(parsed) === parsed ? parsed : null;
      },
    },
  );
  const ride = useMemo(() => ({ bearingDeg, at: departure.at, speedKmh }), [bearingDeg, departure.at, speedKmh]);
  return { bearingDeg, setBearingDeg, departure, speedKmh, setSpeedKmh, ride };
}
