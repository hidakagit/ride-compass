"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import MapView from "@/components/Map/MapView";
import BackendStatus from "@/components/BackendStatus";
import DebugPanel from "@/components/DebugPanel/DebugPanel";
import DebugConsole from "@/components/DebugConsole/DebugConsole";
import LocationControl from "@/components/LocationControl/LocationControl";
import MapLayerControls from "@/components/MapLayerControls/MapLayerControls";
import RouteForm from "@/components/RouteForm/RouteForm";
import RouteList from "@/components/RouteList/RouteList";
import WeatherPanel from "@/components/WeatherPanel/WeatherPanel";
import { generateRoutes } from "@/services/routeApi";
import { getCurrentWeather } from "@/services/weatherApi";
import type { Coordinates, LocationSource, RouteCandidate } from "@/types/route";
import type { WeatherConditions } from "@/types/weather";

// 開発時の初期地点フォールバック: 東京都北区・王子駅付近
const DEFAULT_LOCATION: Coordinates = { latitude: 35.7597, longitude: 139.7387 };
const DISTANCE_TOLERANCE_KM = 5;

export default function Home() {
  const [location, setLocation] = useState<Coordinates>(DEFAULT_LOCATION);
  const [locationSource, setLocationSource] = useState<LocationSource>("default");
  const [manualLat, setManualLat] = useState(String(DEFAULT_LOCATION.latitude));
  const [manualLng, setManualLng] = useState(String(DEFAULT_LOCATION.longitude));
  const [showManualInput, setShowManualInput] = useState(false);

  const [routes, setRoutes] = useState<RouteCandidate[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [weather, setWeather] = useState<WeatherConditions | null>(null);
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [weatherError, setWeatherError] = useState<string | null>(null);

  const [showElevation, setShowElevation] = useState(false);
  const [showRoad, setShowRoad] = useState(false);
  const [dynamicLayerOn, setDynamicLayerOn] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [regionZoomTooWide, setRegionZoomTooWide] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);

  const selectedCandidate = routes.find((r) => r.id === selectedRouteId) ?? null;
  const hasDetail = !!selectedCandidate?.segments && selectedCandidate.segments.length > 0;

  // 現在地取得（失敗時は王子付近のデフォルト座標のまま）
  useEffect(() => {
    if (!navigator.geolocation) return;

    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocation({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        });
        setLocationSource("geolocation");
      },
      () => {
        setLocationSource("default");
      },
      { timeout: 8000 }
    );
  }, []);

  // 現在地が変わったらその地点の天候を取得（ルート生成時の風評価の起点にもなる）。
  // マウント直後はDEFAULT_LOCATIONで取得が走り、その直後にGeolocationが成功すると
  // 実際の現在地でも取得が走る。ネットワーク遅延次第で先に投げた方が後に返ってくることが
  // あるため、リクエストごとに連番を振り「一番最後に投げたリクエストの結果か」を確認してから
  // setWeatherする（古い応答が新しい応答を上書きしないようにする）。
  const latestWeatherRequestId = useRef(0);
  const fetchWeatherFor = useCallback((next: Coordinates) => {
    const requestId = ++latestWeatherRequestId.current;
    setWeatherLoading(true);
    setWeatherError(null);
    getCurrentWeather(next)
      .then((conditions) => {
        if (requestId !== latestWeatherRequestId.current) return;
        setWeather(conditions);
      })
      .catch((error: unknown) => {
        if (requestId !== latestWeatherRequestId.current) return;
        setWeatherError(error instanceof Error ? error.message : "不明なエラーが発生しました");
      })
      .finally(() => {
        if (requestId !== latestWeatherRequestId.current) return;
        setWeatherLoading(false);
      });
  }, []);

  useEffect(() => {
    // fetchWeatherForはsetState呼び出しを含むため、effect本体からの直接同期呼び出しを避けて
    // マイクロタスク経由で実行する（react-hooks/set-state-in-effect対策）
    Promise.resolve().then(() => fetchWeatherFor(location));
  }, [location, fetchWeatherFor]);

  function handleManualSubmit(event: React.FormEvent) {
    event.preventDefault();
    const latitude = Number(manualLat);
    const longitude = Number(manualLng);
    if (Number.isNaN(latitude) || Number.isNaN(longitude)) return;
    setLocation({ latitude, longitude });
    setLocationSource("manual");
  }

  async function handleGenerate(distanceKm: number) {
    setLoading(true);
    setErrorMessage(null);
    try {
      const candidates = await generateRoutes({
        latitude: location.latitude,
        longitude: location.longitude,
        distance_km: distanceKm,
        distance_tolerance_km: DISTANCE_TOLERANCE_KM,
        route_type: "loop",
      });
      setRoutes(candidates);
      setSelectedRouteId(candidates[0]?.id ?? null);
      if (candidates.length === 0) {
        setErrorMessage("条件に合うルート候補が見つかりませんでした。距離を変えて試してください。");
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "不明なエラーが発生しました");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <aside
        style={{
          width: sidebarCollapsed ? "2.75rem" : "340px",
          flexShrink: 0,
          overflowY: "auto",
          borderRight: "1px solid #e5e7eb",
          padding: sidebarCollapsed ? "0.5rem 0.25rem" : "1rem",
          display: "flex",
          flexDirection: "column",
          gap: "1rem",
        }}
      >
        <button
          type="button"
          onClick={() => setSidebarCollapsed((v) => !v)}
          aria-label={sidebarCollapsed ? "パネルを開く" : "パネルを閉じる"}
          style={{ alignSelf: "flex-start" }}
        >
          {sidebarCollapsed ? "▶" : "◀"}
        </button>

        {!sidebarCollapsed && (
          <>
            <header>
              <h1 style={{ fontSize: "1.3rem", marginBottom: "0.25rem" }}>RideCompass</h1>
              <p style={{ color: "#666", fontSize: "0.85rem" }}>ロードバイク向け周回ルート生成アプリ（プロトタイプ）</p>
            </header>

            <BackendStatus />
            <DebugPanel />
            <WeatherPanel weather={weather} loading={weatherLoading} error={weatherError} />

            <LocationControl
              location={location}
              source={locationSource}
              manualLat={manualLat}
              manualLng={manualLng}
              showManualInput={showManualInput}
              onManualLatChange={setManualLat}
              onManualLngChange={setManualLng}
              onToggleManualInput={() => setShowManualInput((v) => !v)}
              onManualSubmit={handleManualSubmit}
            />

            <RouteForm onGenerate={handleGenerate} loading={loading} />

            {errorMessage && <p style={{ color: "#dc2626", fontSize: "0.85rem" }}>{errorMessage}</p>}

            <MapLayerControls
              showElevation={showElevation}
              onShowElevationToggle={setShowElevation}
              showRoad={showRoad}
              onShowRoadToggle={setShowRoad}
              dynamicLayerOn={dynamicLayerOn}
              onDynamicLayerToggle={setDynamicLayerOn}
              hasDetail={hasDetail}
              regionZoomTooWide={regionZoomTooWide}
              onRefresh={() => setRefreshToken((v) => v + 1)}
            />

            <RouteList routes={routes} selectedRouteId={selectedRouteId} onSelect={setSelectedRouteId} />
          </>
        )}
      </aside>

      <div style={{ flex: 1, position: "relative" }}>
        <MapView
          routes={routes}
          selectedRouteId={selectedRouteId}
          location={location}
          showElevation={showElevation}
          showRoad={showRoad}
          dynamicLayerOn={dynamicLayerOn}
          onRegionZoomHintChange={setRegionZoomTooWide}
          refreshToken={refreshToken}
        />
        <DebugConsole />
      </div>
    </div>
  );
}
