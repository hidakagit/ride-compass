import type { WeatherConditions } from "@/types/weather";

interface WeatherPanelProps {
  weather: WeatherConditions | null;
  loading: boolean;
  error: string | null;
}

export default function WeatherPanel({ weather, loading, error }: WeatherPanelProps) {
  if (loading) return <p style={{ fontSize: "0.9rem", color: "#666" }}>天候取得中...</p>;
  if (error) return <p style={{ fontSize: "0.9rem", color: "#dc2626" }}>{error}</p>;
  if (!weather) return null;

  return (
    <p style={{ fontSize: "0.9rem" }}>
      現在の天候: {weather.temperature_c.toFixed(1)}℃ / {weather.wind_direction_label}の風{" "}
      {weather.wind_speed_ms.toFixed(1)} m/s
      {weather.precipitation_probability_percent != null &&
        ` / 降水確率 ${Math.round(weather.precipitation_probability_percent)}%`}
    </p>
  );
}
