"use client";

import { useCallback, useEffect, useState } from "react";
import FloatingPanel from "@/components/FloatingPanel/FloatingPanel";
import { getDebugStats, type DebugStats } from "@/services/debugStatsApi";
import { getFrontendVersion, type FrontendVersion } from "@/services/versionApi";
import styles from "./SystemStatusPanel.module.css";

interface SystemStatusPanelProps {
  open: boolean;
  onClose: () => void;
}

function formatStartedAt(iso: string): string {
  return new Date(iso).toLocaleString("ja-JP", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// last_error_type/last_error_atはバックエンド側で常に一緒に設定される（infrastructure/
// debug_log.pyの_record）。片方だけnullになる想定はないが、型はそれぞれ独立のためガードする。
function formatLastError(type: string | null, at: string | null): string {
  if (!type || !at) return "—";
  return `${type} (${formatStartedAt(at)})`;
}

// フロント・バックそれぞれの適用バージョン（commit・起動日時）とバックエンドの外部API
// 呼び出しサマリを、ログ本文とは別の独立パネルとして表示する（設定内のボタンから開閉）。
// 以前はDebugConsole（ログ本文）の上部に同居させていたが、更新頻度・情報源の異なる2種類の
// 情報が1つのスクロール領域に混ざって見づらいというフィードバックを受け分離した（2026-08-16）。
// プロセス内カウンタ（バックエンド）・モジュール評価時刻（フロント）のスナップショットのため、
// ポーリングはせず開いたときと「更新」ボタン押下時にだけ取得する。
export default function SystemStatusPanel({ open, onClose }: SystemStatusPanelProps) {
  const [backend, setBackend] = useState<DebugStats | null>(null);
  const [frontend, setFrontend] = useState<FrontendVersion | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [frontendError, setFrontendError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchAll = useCallback(() => {
    setLoading(true);
    getDebugStats()
      .then((data) => {
        setBackend(data);
        setBackendError(null);
      })
      .catch((error) => setBackendError(error instanceof Error ? error.message : String(error)));
    getFrontendVersion()
      .then((data) => {
        setFrontend(data);
        setFrontendError(null);
      })
      .catch((error) => setFrontendError(error instanceof Error ? error.message : String(error)))
      .finally(() => setLoading(false));
  }, []);

  // effect本体からの直接同期setState呼び出しを避け、マイクロタスク経由で実行する
  // （react-hooks/set-state-in-effect対策、page.tsxのfetchWeatherForと同じ流儀）。
  useEffect(() => {
    if (open) Promise.resolve().then(() => fetchAll());
  }, [open, fetchAll]);

  const externalEntries = backend ? Object.entries(backend.external) : [];
  const rejectionEntries = backend ? Object.entries(backend.rate_limit_rejections) : [];

  return (
    <FloatingPanel
      open={open}
      onClose={onClose}
      title="システム状況"
      // デバッグログパネル（topRem既定4.25）と同時に開いても両方のヘッダーが見える位置まで
      // 下へずらす（同じ既定位置だと後から開いた方が完全に覆い隠してしまうため）。
      // ドラッグで動かせるので、重なった場合はどちらかを移動すればよい。
      topRem={8.5}
      widthRem={24}
      maxHeightPx={480}
      headerButtons={
        <button type="button" onClick={fetchAll} disabled={loading} className={styles.refreshButton}>
          {loading ? "更新中…" : "更新"}
        </button>
      }
    >
      <div className={styles.content}>
        <div className={styles.versionGrid}>
          <div className={styles.versionCard}>
            <span className={styles.versionLabel}>フロントエンド</span>
            {frontendError && <span className={styles.error}>取得失敗: {frontendError}</span>}
            {frontend && (
              <>
                <span className={styles.commit}>{frontend.commit ?? "(ローカル)"}</span>
                <span className={styles.startedAt}>起動 {formatStartedAt(frontend.started_at)}</span>
              </>
            )}
          </div>
          <div className={styles.versionCard}>
            <span className={styles.versionLabel}>バックエンド</span>
            {backendError && <span className={styles.error}>取得失敗: {backendError}</span>}
            {backend && (
              <>
                <span className={styles.commit}>{backend.commit ?? "(ローカル)"}</span>
                <span className={styles.startedAt}>起動 {formatStartedAt(backend.started_at)}</span>
                <span className={styles.meta}>
                  engine {backend.engine} ・ debug_mode {backend.debug_mode ? "ON" : "OFF"}
                </span>
              </>
            )}
          </div>
        </div>

        {externalEntries.length > 0 && (
          <>
            <div className={styles.sectionHeading}>外部サービス呼び出しサマリ</div>
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>カテゴリ</th>
                    <th>呼出</th>
                    <th>エラー</th>
                    <th>最終失敗</th>
                    <th>hit率</th>
                    <th>平均</th>
                    <th>最大</th>
                  </tr>
                </thead>
                <tbody>
                  {externalEntries.map(([category, s]) => {
                    // エラーセルのtitleに内訳（原因別件数・再試行状況・stale代用回数）を出す。
                    // 一覧に列を増やさずとも「429かタイムアウトか」等をホバーで確認できるようにする
                    // （改善計画T92: /api/debug/statsで失敗の主な理由を推測できる情報がほしい、の対応）。
                    const errorTypeParts = Object.entries(s.error_types).map(([type, count]) => `${type}:${count}`);
                    if (s.retried_calls > 0) {
                      errorTypeParts.push(`再試行あり ${s.retried_calls}件(延べ${s.retry_attempts_total}回)`);
                    }
                    if (s.stale_fallback_used > 0) {
                      errorTypeParts.push(`古いキャッシュで代用 ${s.stale_fallback_used}件`);
                    }
                    return (
                      <tr key={category} data-level={s.errors > 0 ? "error" : undefined}>
                        <td className={styles.categoryCell}>{category}</td>
                        <td>{s.calls}</td>
                        <td title={errorTypeParts.length > 0 ? errorTypeParts.join(" / ") : undefined}>
                          {s.errors}
                        </td>
                        <td>{formatLastError(s.last_error_type, s.last_error_at)}</td>
                        <td>{s.cache_hit_rate != null ? `${Math.round(s.cache_hit_rate * 100)}%` : "—"}</td>
                        <td>{s.avg_ms}ms</td>
                        <td>{s.max_ms}ms</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}

        {rejectionEntries.length > 0 && (
          <div className={styles.rejections}>
            {rejectionEntries.map(([category, count]) => (
              <span key={category} className={styles.rejectionBadge}>
                429拒否: {category} {count}件
              </span>
            ))}
          </div>
        )}

        {!backend && !frontend && !backendError && !frontendError && <p className={styles.muted}>取得中…</p>}
      </div>
    </FloatingPanel>
  );
}
