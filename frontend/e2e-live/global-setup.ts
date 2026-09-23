import { LIVE_API, LIVE_POINT, decodeRoadTile, fetchCatalog, tileOf } from "./live";
import regionTileConfig from "@/types/generated/region-tile-config.json";
import { LIVE_ORIGIN } from "../playwright.live.config";

// 前提の不成立（backendが動いていない・起点が取込範囲外・基礎地図のURLのずれ・予報が古い）を最初に確かめ、
// 個々のテストの失敗として出さずに「前提不成立: 何を直せばよいか」で止める。テストの失敗は壊れ方の検知だけにする。

class Unmet extends Error {
  constructor(what: string, fix: string) {
    super(`前提不成立: ${what}。${fix}`);
  }
}

export default async function globalSetup(): Promise<void> {
  const health = await fetch(`${LIVE_API}/health`).catch(() => null);
  if (!health?.ok) {
    throw new Unmet(
      `${LIVE_API}/health に応答が無い`,
      "開発DBへ向けたbackendを手元で起動する（docs/conventions/testing.md パターン4「走らせ方」）",
    );
  }

  const catalog = await fetchCatalog();
  const version = catalog.tile_versions.road_surface;
  if (!version) throw new Unmet("軸カタログに路面タイルの世代が無い", "backendのDBの接続先と起動ログを確かめる");

  const { z, x, y } = tileOf(regionTileConfig.road_tile_max_zoom, LIVE_POINT);
  const tile = await fetch(`${LIVE_API}/api/region/road-surface-tiles/${z}/${x}/${y}.pbf?v=${version}`);
  const roads = tile.ok ? decodeRoadTile(Buffer.from(await tile.arrayBuffer())) : [];
  if (roads.length === 0) {
    throw new Unmet(
      `起点（${LIVE_POINT.latitude},${LIVE_POINT.longitude}）の路面タイル ${z}/${x}/${y} に道が無い（HTTP ${tile.status}）`,
      "開発DBの取込範囲の中の地点を E2E_LIVE_POINT=緯度,経度 で与える",
    );
  }

  const style = (await (await fetch(`${LIVE_API}/api/basemap/styles/liberty`)).json()) as {
    sources: Record<string, { url?: string; tiles?: string[] }>;
  };
  const urls = Object.values(style.sources).flatMap((source) => [source.url, ...(source.tiles ?? [])].filter(Boolean));
  const foreign = urls.filter((url) => !url!.startsWith(`${LIVE_ORIGIN}/`));
  if (foreign.length > 0) {
    throw new Unmet(
      `基礎地図のスタイルのURLがE2Eのオリジン（${LIVE_ORIGIN}）を指していない: ${foreign[0]}`,
      `backendを BASEMAP_PUBLIC_BASE_URL=${LIVE_ORIGIN}/api/basemap と CORS_ALLOWED_ORIGINS に ${LIVE_ORIGIN} を足して起動し直す`,
    );
  }

  // 予報（MSM）が古いと、時刻を入力に取る軸の値が来ないのは欠陥ではない。S3の該当の枝はこれを見て判定をやめる。
  const stats = (await (await fetch(`${LIVE_API}/api/debug/stats`)).json()) as { msm: { healthy: boolean } | null };
  process.env.E2E_LIVE_MSM_HEALTHY = stats.msm?.healthy ? "1" : "0";
}
