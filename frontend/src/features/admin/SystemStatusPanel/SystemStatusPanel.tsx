"use client";

import { useQuery } from "@tanstack/react-query";
import { formatJstDateTime } from "@/lib/time";
import FloatingPanel from "@/components/FloatingPanel/FloatingPanel";
import { getDebugStats } from "@/features/admin/adminApi";
import { getFrontendVersion } from "@/services/versionApi";
import { getQueryClient } from "@/lib/queryClient";
import { Button } from "@/components/ui/Button/Button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/Table/Table";
import { Badge } from "@/components/ui/Badge/Badge";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

interface SystemStatusPanelProps {
  open: boolean;
  onClose: () => void;
}

function errorText(error: unknown): string | null {
  if (error === null) return null;
  return error instanceof Error ? error.message : String(error);
}

function formatStartedAt(iso: string): string {
  return formatJstDateTime(new Date(iso));
}

function formatLastError(error: { type: string; at: string } | null): string {
  if (error === null) return "—";
  return `${error.type} (${formatStartedAt(error.at)})`;
}

// フロント・バックそれぞれの適用バージョン（commit・起動日時）とバックエンドの外部API
// 呼び出しサマリを、ログ本文とは別の独立パネルとして表示する（設定内のボタンから開閉）。
// プロセス内カウンタ（バックエンド）・モジュール評価時刻（フロント）のスナップショットのため、
// ポーリングはせず開いたときと「更新」ボタン押下時にだけ取得する。
export default function SystemStatusPanel({ open, onClose }: SystemStatusPanelProps) {
  const client = getQueryClient();
  const backendQuery = useQuery({ queryKey: ["debug-stats"], queryFn: getDebugStats, enabled: open }, client);
  const frontendQuery = useQuery(
    { queryKey: ["frontend-version"], queryFn: getFrontendVersion, enabled: open },
    client,
  );
  const backend = backendQuery.data ?? null;
  const frontend = frontendQuery.data ?? null;
  const backendError = errorText(backendQuery.error);
  const frontendError = errorText(frontendQuery.error);
  // 「更新」は両方が届くまで押せない（速い方が先に届いた時点で押せると、遅い方の取得中に重ねて取りに行く）。
  const loading = backendQuery.isFetching || frontendQuery.isFetching;
  const fetchAll = () => {
    void backendQuery.refetch();
    void frontendQuery.refetch();
  };

  const externalEntries = backend ? Object.entries(backend.external) : [];
  const rejectionEntries = backend ? Object.entries(backend.rate_limit_rejections) : [];

  return (
    <FloatingPanel
      open={open}
      onClose={onClose}
      title="システム状況"
      // デバッグログパネル（`components/DebugConsole/DebugConsole.tsx: DebugConsole`）と同時に開いても
      // 両方のヘッダーが見えるよう、それより下に置く（同じ位置だと後から開いた方が完全に覆い隠す）。
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
                  // エラー件数の下に原因別件数を1行に1つずつ小さく添える。一覧に列を増やさずに「429かタイムアウトか」等を
                  // 読めるようにする（titleはスマホで出ない）。
                  const errorTypeParts = Object.entries(s.error_types).map(([type, count]) => `${type}:${count}`);
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
                      <TableCell>
                        {s.errors}
                        {errorTypeParts.map((part) => (
                          <span key={part} className={cn(textVariants({ variant: "note" }), "block whitespace-nowrap")}>
                            {part}
                          </span>
                        ))}
                      </TableCell>
                      <TableCell>{formatLastError(s.last_error)}</TableCell>
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
