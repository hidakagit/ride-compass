"use client";

import type { RouteCandidate } from "@/types/route";
import styles from "./RouteList.module.css";

interface RouteListProps {
  routes: RouteCandidate[];
  selectedRouteId: string | null;
  onSelect: (id: string) => void;
}

export default function RouteList({ routes, selectedRouteId, onSelect }: RouteListProps) {
  if (routes.length === 0) return null;

  return (
    <ul className={styles.list}>
      {routes.map((route) => {
        const selected = route.id === selectedRouteId;
        return (
          <li key={route.id}>
            <button
              type="button"
              onClick={() => onSelect(route.id)}
              className={selected ? `${styles.item} ${styles.itemSelected}` : styles.item}
            >
              {route.total_score != null && (
                <strong>総合スコア {Math.round(route.total_score)}点 / </strong>
              )}
              {route.direction_label}方向 — {route.distance_km.toFixed(1)} km
              {route.elevation_gain_m != null && ` / 獲得標高 ${Math.round(route.elevation_gain_m)} m`}
              {route.wind_score != null &&
                ` / ${route.wind_score >= 0 ? "向かい風" : "追い風"} ${Math.abs(route.wind_score).toFixed(1)} m/s`}
              {route.road_score != null && ` / 舗装率 ${Math.round(route.road_score)}%`}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
