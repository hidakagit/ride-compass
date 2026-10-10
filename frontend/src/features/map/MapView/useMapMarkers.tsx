"use client";

import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, Marker } from "maplibre-gl";

import type { Coordinates, LocationSource, PinRole, SelectedRouteSegment } from "@/types/route";
import {
  ORIGIN_MARK_COLOR,
  ORIGIN_MARK_FALLBACK_COLOR,
  PIN_MARK_BACKGROUND,
  PinMark,
  pinMarkText,
} from "@/components/PinMark/PinMark";
import { SelectedSpotIcon } from "@/components/ui/icons/icons";
import palette from "@/types/generated/palette.json";
import { runWhenStyleReady } from "@/features/map/layers/mapStyleOps";

/** 出発地点を見せる倍率（地図を作ったとき・出発地点が変わったとき）。 */
export const ORIGIN_ZOOM = 13;

// 出発地点は現在地の記号（十字線と中心の点）を面の色（テーマに従う）の円に乗せる。左右対称なので、アンカーは地点＝中心（"center"）。
// 中身の印はReactでportalして描く。
function createOriginMarkerElement(): HTMLDivElement {
  const el = document.createElement("div");
  el.style.cssText =
    "width:32px; height:32px; border-radius:50%; background:" +
    PIN_MARK_BACKGROUND.origin +
    "; display:flex; " +
    "align-items:center; justify-content:center; box-shadow:0 1px 4px rgba(0,0,0,0.4); " +
    "touch-action:none; cursor:grab;";
  return el;
}

// 経由地・目的地のピン。3つの地点はどれもつかんで動かせるため、出発地と同じ丸いバッジで揃える。白縁と影は
// どの配色の上でも輪郭が消えないため、touch-action:noneは指の起点がピンに乗ってもパンとして確定させるため。
function createPointMarkerElement(role: Exclude<PinRole, "origin">, label?: string): HTMLDivElement {
  const el = document.createElement("div");
  const background = PIN_MARK_BACKGROUND[role];
  el.textContent = pinMarkText(role, label);
  el.style.cssText =
    `width:26px; height:26px; border-radius:50%; background:${background}; color:#fff; ` +
    "font-size:13px; font-weight:bold; display:flex; align-items:center; justify-content:center; " +
    "border:2px solid #fff; box-shadow:0 1px 4px rgba(0,0,0,0.4); touch-action:none; cursor:grab;";
  return el;
}

/** 経由地・目的地の印を地図へ置く。動かせる間だけ、つかんで動かす・押す操作を結ぶ。 */
function addPointMarker(
  map: MapLibreMap,
  point: Coordinates,
  element: HTMLDivElement,
  editable: boolean,
  handlers: { onMove: (coordinates: Coordinates) => void; onClick: () => void },
): Marker {
  const marker = new maplibregl.Marker({ element, draggable: editable })
    .setLngLat([point.longitude, point.latitude])
    .addTo(map);
  if (editable) {
    marker.on("dragend", () => {
      const lngLat = marker.getLngLat();
      handlers.onMove({ latitude: lngLat.lat, longitude: lngLat.lng });
    });
    bindDragAwareClick(marker, element, handlers.onClick);
  }
  return marker;
}

// マーカーをドラッグした直後は、同じ操作の終わりにclickも飛ぶ。つかんで動かしただけで
// 削除・解除が起きないよう、ドラッグ由来の1回を読み飛ばす。
function bindDragAwareClick(marker: maplibregl.Marker, element: HTMLElement, onClick: () => void): void {
  let dragged = false;
  marker.on("dragstart", () => {
    dragged = true;
  });
  element.addEventListener("click", (event) => {
    event.stopPropagation();
    if (dragged) {
      dragged = false;
      return;
    }
    onClick();
  });
}

interface MapMarkersInputs {
  location: Coordinates;
  /** 出発地点の色。位置が取れず既定の地点（"default"）のときだけ灰色にする。 */
  locationSource: LocationSource;
  waypoints: Coordinates[];
  destination: Coordinates | null;
  selectedRouteSegment: SelectedRouteSegment | null;
  /** 地点をつかんで動かす・押して消すことを受け付けるか。falseの間、印は表示だけで動かせない。 */
  pointEditingEnabled: boolean;
  onPinPlace: (role: PinRole, coordinates: Coordinates) => void;
  onWaypointRemove: (index: number) => void;
  onWaypointMove: (index: number, coordinates: Coordinates) => void;
  onDestinationClear: () => void;
  onRouteSegmentSelect: (selection: SelectedRouteSegment | null) => void;
}

/**
 * 地図の地点の印（出発地・経由地・目的地・選んでいる区間）の作成・位置の更新・ドラッグ・後始末。
 * 印の中身のうちReactで描くもの（出発地の印・区間の印）は、返すportalを地図の部品が描く。
 */
export function useMapMarkers(
  mapRef: RefObject<MapLibreMap | null>,
  {
    location,
    locationSource,
    waypoints,
    destination,
    selectedRouteSegment,
    pointEditingEnabled,
    ...handlers
  }: MapMarkersInputs,
): ReactNode {
  const markerRef = useRef<Marker | null>(null);
  // 出発地点の印に当てた色の元。Markerは位置の更新で色を変えられないため、色が変わるときだけ作り直す。
  const appliedMarkerSourceRef = useRef<LocationSource | null>(null);
  const waypointMarkersRef = useRef<Marker[]>([]);
  const destinationMarkerRef = useRef<Marker | null>(null);
  const selectedSegmentMarkerRef = useRef<Marker | null>(null);
  // 出発地点の印の器（Markerの要素）と、中身の印の色。
  const [originMark, setOriginMark] = useState<{ element: HTMLDivElement; color: string } | null>(null);
  // 選んでいる区間の印の器（Markerの要素）。中身はアイコン集の形をportalで描く。
  const [selectedSegmentMark, setSelectedSegmentMark] = useState<HTMLDivElement | null>(null);
  // 印の操作（作ったときに一度だけ結ぶ）が、いまのpropsを読むための参照。
  const latestProps = { pointEditingEnabled, ...handlers };
  const latest = useRef(latestProps);
  useEffect(() => {
    latest.current = latestProps;
  });
  // 出発地点をドラッグで動かした直後の1回だけ、位置の更新でカメラを動かさない（その地点は既に画面に見えている）。
  const skipNextFlyToRef = useRef(false);

  // 地図を片付けたら、印は破棄した地図に付いたままなので捨てる（Strict Modeの二重マウントで、残った印が新しい地図に付かない）。
  useEffect(
    () => () => {
      markerRef.current = null;
      appliedMarkerSourceRef.current = null;
      waypointMarkersRef.current = [];
      destinationMarkerRef.current = null;
      selectedSegmentMarkerRef.current = null;
    },
    [],
  );

  // 位置が変わったら地図と出発地点の印を更新する。印をドラッグで動かした先は「地点を置く」へ渡す。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applyLocation = () => {
      if (skipNextFlyToRef.current) {
        skipNextFlyToRef.current = false;
      } else {
        map.flyTo({ center: [location.longitude, location.latitude], zoom: ORIGIN_ZOOM });
      }

      if (markerRef.current && appliedMarkerSourceRef.current === locationSource) {
        markerRef.current.setLngLat([location.longitude, location.latitude]);
      } else {
        markerRef.current?.remove();
        const color = locationSource === "default" ? ORIGIN_MARK_FALLBACK_COLOR : ORIGIN_MARK_COLOR;
        const element = createOriginMarkerElement();
        setOriginMark({ element, color });
        markerRef.current = new maplibregl.Marker({
          element,
          anchor: "center",
          draggable: latest.current.pointEditingEnabled,
        })
          .setLngLat([location.longitude, location.latitude])
          .addTo(map);
        markerRef.current.on("dragend", () => {
          const lngLat = markerRef.current!.getLngLat();
          skipNextFlyToRef.current = true;
          latest.current.onPinPlace("origin", { latitude: lngLat.lat, longitude: lngLat.lng });
        });
        appliedMarkerSourceRef.current = locationSource;
      }
    };

    runWhenStyleReady(map, applyLocation);
  }, [mapRef, location, locationSource]);

  // 経由地の印（数件なので作り直す）。番号で通る順を示し、押すと消す（すぐ打ち直せるため確かめない）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applyWaypointMarkers = () => {
      waypointMarkersRef.current.forEach((marker) => marker.remove());
      waypointMarkersRef.current = waypoints.map((point, index) =>
        addPointMarker(map, point, createPointMarkerElement("waypoint", String(index + 1)), pointEditingEnabled, {
          onMove: (coordinates) => latest.current.onWaypointMove(index, coordinates),
          onClick: () => latest.current.onWaypointRemove(index),
        }),
      );
    };

    runWhenStyleReady(map, applyWaypointMarkers);
  }, [mapRef, waypoints, pointEditingEnabled]);

  // 出発地マーカーのつかめる/つかめないは、マーカーを作り直さずに切り替える——作り直す
  // effect（上）はカメラ移動を伴うため、パネルを切り替えるたびに地図が飛んでしまう。
  useEffect(() => {
    markerRef.current?.setDraggable(pointEditingEnabled);
  }, [pointEditingEnabled]);

  // 目的地の印。押すと解除する。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applyDestinationMarker = () => {
      destinationMarkerRef.current?.remove();
      destinationMarkerRef.current = null;
      if (!destination) return;

      destinationMarkerRef.current = addPointMarker(
        map,
        destination,
        createPointMarkerElement("destination"),
        pointEditingEnabled,
        {
          onMove: (coordinates) => latest.current.onPinPlace("destination", coordinates),
          onClick: () => latest.current.onDestinationClear(),
        },
      );
    };

    runWhenStyleReady(map, applyDestinationMarker);
  }, [mapRef, destination, pointEditingEnabled]);

  // 選んでいる区間の印。選択が外れれば（どこで外しても）消える。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applySelectedSegmentMarker = () => {
      selectedSegmentMarkerRef.current?.remove();
      selectedSegmentMarkerRef.current = null;
      setSelectedSegmentMark(null);
      if (!selectedRouteSegment) return;

      const el = document.createElement("div");
      // touch-action:noneで、指の起点が印に乗ってもパンとして確定させる。
      el.style.cssText = `display:flex; color:${palette.semantic.inspected}; cursor:pointer; filter:drop-shadow(0 1px 2px rgba(0,0,0,0.5)); touch-action:none;`;
      setSelectedSegmentMark(el);
      el.setAttribute("aria-label", "選択中の区間");
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        latest.current.onRouteSegmentSelect(null);
      });
      selectedSegmentMarkerRef.current = new maplibregl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([selectedRouteSegment.longitude, selectedRouteSegment.latitude])
        .addTo(map);
    };

    runWhenStyleReady(map, applySelectedSegmentMarker);
  }, [mapRef, selectedRouteSegment]);

  return (
    <>
      {originMark !== null &&
        createPortal(<PinMark role="origin" size={20} color={originMark.color} />, originMark.element)}
      {selectedSegmentMark !== null && createPortal(<SelectedSpotIcon size={26} />, selectedSegmentMark)}
    </>
  );
}
