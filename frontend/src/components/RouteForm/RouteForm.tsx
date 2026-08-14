"use client";

import { useState } from "react";

interface RouteFormProps {
  onGenerate: (distanceKm: number) => void;
  loading: boolean;
}

export default function RouteForm({ onGenerate, loading }: RouteFormProps) {
  const [distance, setDistance] = useState("30");

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const value = Number(distance);
    if (Number.isNaN(value) || value <= 0) return;
    onGenerate(value);
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.75rem" }}>
      <label>
        距離
        <input
          type="number"
          min="1"
          step="1"
          value={distance}
          onChange={(e) => setDistance(e.target.value)}
          style={{ marginLeft: "0.5rem", width: "5rem" }}
        />
        km
      </label>
      <button type="submit" disabled={loading}>
        {loading ? "生成中..." : "ルート生成"}
      </button>
    </form>
  );
}
