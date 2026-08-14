"use client";

interface MapLayerControlsProps {
  showElevation: boolean;
  onShowElevationToggle: (on: boolean) => void;
  showRoad: boolean;
  onShowRoadToggle: (on: boolean) => void;
  dynamicLayerOn: boolean;
  onDynamicLayerToggle: (on: boolean) => void;
  hasDetail: boolean;
  regionZoomTooWide: boolean;
  onRefresh: () => void;
}

export default function MapLayerControls({
  showElevation,
  onShowElevationToggle,
  showRoad,
  onShowRoadToggle,
  dynamicLayerOn,
  onDynamicLayerToggle,
  hasDetail,
  regionZoomTooWide,
  onRefresh,
}: MapLayerControlsProps) {
  const showRoadLegend = showRoad && !regionZoomTooWide;
  const showWindLegend = dynamicLayerOn && hasDetail;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", fontSize: "0.85rem" }}>
      <strong>地図レイヤー</strong>

      <div>
        <div style={{ color: "#666", marginBottom: "0.2rem" }}>常時表示（表示中の地域全体・変わらないデータ、標高/路面は同時に重ね表示可）</div>
        <label style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
          <input type="checkbox" checked={showElevation} onChange={(e) => onShowElevationToggle(e.target.checked)} />
          標高（国土地理院 色別標高図）
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
          <input type="checkbox" checked={showRoad} onChange={(e) => onShowRoadToggle(e.target.checked)} />
          路面で色分け
        </label>
        {showRoad && regionZoomTooWide && (
          <p style={{ color: "#b45309", margin: "0.25rem 0 0" }}>表示範囲が広すぎます。地図をズームインしてください。</p>
        )}
      </div>

      <div>
        <div style={{ color: "#666", marginBottom: "0.2rem" }}>選択中ルートのみ（時間で変わるデータ）</div>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.3rem",
            color: hasDetail ? undefined : "#999",
          }}
        >
          <input
            type="checkbox"
            checked={dynamicLayerOn}
            disabled={!hasDetail}
            onChange={(e) => onDynamicLayerToggle(e.target.checked)}
          />
          風の影響を表示
        </label>
      </div>

      {showRoadLegend && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
          <span style={{ width: "10px", height: "10px", background: "#16a34a", display: "inline-block", borderRadius: "2px" }} />
          舗装路
          <span style={{ width: "10px", height: "10px", background: "#dc2626", display: "inline-block", borderRadius: "2px", marginLeft: "0.4rem" }} />
          未舗装等
          <span style={{ width: "10px", height: "10px", background: "#9ca3af", display: "inline-block", borderRadius: "2px", marginLeft: "0.4rem" }} />
          不明
        </div>
      )}

      {showWindLegend && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
          <span style={{ width: "10px", height: "10px", background: "#16a34a", display: "inline-block", borderRadius: "2px" }} />
          易しい
          <span style={{ width: "10px", height: "10px", background: "#f59e0b", display: "inline-block", borderRadius: "2px", marginLeft: "0.4rem" }} />
          普通
          <span style={{ width: "10px", height: "10px", background: "#dc2626", display: "inline-block", borderRadius: "2px", marginLeft: "0.4rem" }} />
          難しい
        </div>
      )}

      <button type="button" onClick={onRefresh} style={{ alignSelf: "flex-start" }}>
        変わらないデータを更新
      </button>
    </div>
  );
}
