"use client";

import { useCallback, useEffect, useState } from "react";
import FloatingPanel from "@/components/FloatingPanel/FloatingPanel";
import { getDebugStats, type DebugStats } from "@/services/debugStatsApi";
import { getFrontendVersion, type FrontendVersion } from "@/services/versionApi";
import { Button } from "@/components/ui/Button/Button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/Table/Table";
import { Badge } from "@/components/ui/Badge/Badge";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

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
    // getDebugStats()（バックエンド、ネットワーク往復を伴い所要時間が読めない）と
    // getFrontendVersion()（フロント自身のモジュール評価時刻、実質即時）を別々に
    // .finally()でsetLoading(false)すると、片方だけ先に解決した時点で「更新」ボタンが
    // 押せる状態へ戻りloading表示が消えてしまう。両方が完了するまでloadingを維持する
    // ようPromise.allでまとめる（下記の理由により失敗ケースも含めPromise.allで足りる）。
    const backendFetch = getDebugStats()
      .then((data) => {
        setBackend(data);
        setBackendError(null);
      })
      .catch((error) => setBackendError(error instanceof Error ? error.message : String(error)));
    const frontendFetch = getFrontendVersion()
      .then((data) => {
        setFrontend(data);
        setFrontendError(null);
      })
      .catch((error) => setFrontendError(error instanceof Error ? error.message : String(error)));
    // backendFetch/frontendFetchはいずれも自前で.catch()済みで拒否しないため、
    // Promise.allで両方の完了を待てば十分（片方が失敗しても他方の完了を待たずに
    // loadingが解除される事故を防げる）。
    Promise.all([backendFetch, frontendFetch]).then(() => setLoading(false));
  }, []);

  // effect本体からの直接同期setState呼び出しを避け、マイクロタスク経由で実行する
  // （react-hooks/set-state-in-effect対策、useWeatherConditions.tsのuseLocationFetchと同じ流儀）。
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
        <Button size="xs" onClick={fetchAll} disabled={loading}>
          {loading ? "更新中…" : "更新"}
        </Button>
      }
    >
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-2 py-1.5">
        <div className="grid grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] gap-2">
          <div className="flex flex-col gap-0.5 rounded-md border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2 py-1.5">
            <span className={cn(textVariants({ variant: "note" }), "tracking-wide uppercase")}>フロントエンド</span>
            {frontendError && <span className="text-[var(--color-danger)]">取得失敗: {frontendError}</span>}
            {frontend && (
              <>
                <span className="font-semibold [overflow-wrap:anywhere]">{frontend.commit ?? "(ローカル)"}</span>
                <span className="text-[var(--color-muted)]">起動 {formatStartedAt(frontend.started_at)}</span>
              </>
            )}
          </div>
          <div className="flex flex-col gap-0.5 rounded-md border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2 py-1.5">
            <span className={cn(textVariants({ variant: "note" }), "tracking-wide uppercase")}>バックエンド</span>
            {backendError && <span className="text-[var(--color-danger)]">取得失敗: {backendError}</span>}
            {backend && (
              <>
                <span className="font-semibold [overflow-wrap:anywhere]">{backend.commit ?? "(ローカル)"}</span>
                <span className="text-[var(--color-muted)]">起動 {formatStartedAt(backend.started_at)}</span>
                <span className="text-[var(--color-muted)]">debug_mode {backend.debug_mode ? "ON" : "OFF"}</span>
              </>
            )}
          </div>
        </div>

        {backend?.msm && (
          <div
            className="flex flex-col gap-1 rounded-sm border border-[var(--color-border)] p-2 data-[healthy=false]:border-[var(--color-danger)]"
            data-healthy={backend.msm.healthy ? "true" : "false"}
          >
            <span className={cn(textVariants({ variant: "note" }), "tracking-wide uppercase")}>予報（MSM）</span>
            <span className="text-[var(--color-muted)]">
              最新run {formatStartedAt(backend.msm.last_run_at)}（{backend.msm.run_age_hours}時間前）・ 予報の残り{" "}
              {backend.msm.remaining_hours}時間
            </span>
            {!backend.msm.healthy && (
              <span className="text-[var(--color-danger)]">配信が滞っています（バックエンドのWARNINGログを確認）</span>
            )}
          </div>
        )}

        {externalEntries.length > 0 && (
          <>
            <div className={cn(textVariants({ variant: "note" }), "mt-1 tracking-wide uppercase")}>
              外部サービス呼び出しサマリ
            </div>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader>カテゴリ</TableHeader>
                  <TableHeader>呼出</TableHeader>
                  <TableHeader>エラー</TableHeader>
                  <TableHeader>最終失敗</TableHeader>
                  <TableHeader>hit率</TableHeader>
                  <TableHeader>平均</TableHeader>
                  <TableHeader>最大</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {externalEntries.map(([category, s]) => {
                  // エラーセルのtitleに内訳（原因別件数・再試行状況・stale代用回数）を出す。
                  // 一覧に列を増やさずとも「429かタイムアウトか」等をホバーで確認できるようにする。
                  const errorTypeParts = Object.entries(s.error_types).map(([type, count]) => `${type}:${count}`);
                  if (s.retried_calls > 0) {
                    errorTypeParts.push(`再試行あり ${s.retried_calls}件(延べ${s.retry_attempts_total}回)`);
                  }
                  if (s.stale_fallback_used > 0) {
                    errorTypeParts.push(`古いキャッシュで代用 ${s.stale_fallback_used}件`);
                  }
                  return (
                    <TableRow
                      key={category}
                      data-level={s.errors > 0 ? "error" : undefined}
                      className="data-[level=error]:text-[var(--color-danger)]"
                    >
                      <TableCell className="text-[var(--color-accent)] in-data-[level=error]:text-[var(--color-danger)]">
                        {category}
                      </TableCell>
                      <TableCell>{s.calls}</TableCell>
                      <TableCell title={errorTypeParts.length > 0 ? errorTypeParts.join(" / ") : undefined}>
                        {s.errors}
                      </TableCell>
                      <TableCell>{formatLastError(s.last_error_type, s.last_error_at)}</TableCell>
                      <TableCell>{s.cache_hit_rate != null ? `${Math.round(s.cache_hit_rate * 100)}%` : "—"}</TableCell>
                      <TableCell>{s.avg_ms}ms</TableCell>
                      <TableCell>{s.max_ms}ms</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </>
        )}

        {rejectionEntries.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {rejectionEntries.map(([category, count]) => (
              <Badge key={category} variant="warning">
                429拒否: {category} {count}件
              </Badge>
            ))}
          </div>
        )}

        {!backend && !frontend && !backendError && !frontendError && (
          <p className={textVariants({ variant: "hint" })}>取得中…</p>
        )}
      </div>
    </FloatingPanel>
  );
}
