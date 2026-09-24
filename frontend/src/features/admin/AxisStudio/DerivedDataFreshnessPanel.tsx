"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button/Button";
import { Card } from "@/components/ui/Card/Card";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { getDerivedDataFreshness } from "@/features/admin/adminApi";
import type { DerivedDataFreshnessResponse } from "@/types/route";
import { type StatusRow, StatusRowList, StatusVerdict } from "./StatusRowList";
import { textVariants } from "@/components/ui/Text/Text";

function formatRunId(value: number | null): string {
  return value === null ? "-" : `#${value}`;
}

function formatCount(value: number): string {
  return value.toLocaleString("ja-JP");
}

function formatComputedAt(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString("ja-JP");
}

/** 表1つぶんの状態。「取込が新しくなったのに派生が古い」と「値の列に未計算が残っている」は
 * 判定の方式が違うが、読み手が知りたいのは「作り直しが要るかどうか」で同じ。行の見た目を
 * 揃え、方式の違いは開いた先の中身で表す。 */
function rowsFromReport(report: DerivedDataFreshnessResponse): StatusRow[] {
  return report.tables.map((table) => {
    const incomplete = table.columns.filter((column) => column.is_incomplete);
    const absent = table.columns.filter((column) => !column.is_incomplete && column.null_count > 0);
    // 行そのものが無いケース。鮮度（世代）でも完成度（NULL）でも表に出ない。
    const missing = table.missing_rows ?? 0;
    return {
      name: table.table_name,
      scale: `${formatCount(table.row_count)}行`,
      flagged: table.is_stale || incomplete.length > 0 || missing > 0,
      detail: [
        {
          label: table.source ?? "取込",
          value: `最新 ${formatRunId(table.latest_run_id)} / 反映 ${formatRunId(table.oldest_run_id)}`,
        },
        ...(table.coverage_parent === null
          ? []
          : [
              {
                label: `${table.coverage_parent} を覆う`,
                value:
                  missing > 0
                    ? `${formatCount(missing)}件ぶん行が無い（母数 ${formatCount(table.coverage_parent_row_count ?? 0)}）`
                    : `欠けなし（母数 ${formatCount(table.coverage_parent_row_count ?? 0)}）`,
              },
            ]),
        ...incomplete.map((column) => ({
          label: column.column,
          value: `未計算 ${formatCount(column.null_count)}件`,
        })),
        ...absent.map((column) => ({
          label: column.column,
          value: `値なし ${formatCount(column.null_count)}件（確定）`,
        })),
      ],
    };
  });
}

// 「データ保守」タブ（/admin）から、派生データ（precomputeバッチの出力）が作り直しを要する状態に
// ないかを見るパネル。MaterialCoveragePanel（材料の値がNULL/未取得かという完成度）とは別の
// 切り口——こちらは「取り込んだ生データが新しくなったのに、そこから計算した値が古いまま
// 残っていないか」を見る。集計はDB全表走査を伴うため、ボタン押下時のみ実行する。
export default function DerivedDataFreshnessPanel() {
  const [report, setReport] = useState<DerivedDataFreshnessResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleFetch = () => {
    setLoading(true);
    setError(null);
    getDerivedDataFreshness()
      .then((result) => setReport(result))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  };

  return (
    <Card className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        <span className={textVariants({ variant: "heading" })}>派生データ鮮度台帳</span>
        <InfoPopover triggerAriaLabel="派生データ鮮度台帳の説明">
          取り込んだ生データ（OSM・事故など）が新しくなったのに、そこから計算した派生データが
          古いまま残っていないかを機械判定する。対象はbackendの宣言（ORM）が決めるため、表や列が
          増減しても一覧は自動で追従する。あわせて値の列ごとに未計算の件数を数える——「確定して
          値が無い」列（橋の勾配・指定のない道など）は数に出すが作り直しの対象にはしない。
          DB全体の走査を伴うため集計には時間がかかる。
        </InfoPopover>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={handleFetch} disabled={loading}>
          {loading ? "集計中…" : report ? "再集計する" : "集計する"}
        </Button>
        {report && <span className={textVariants({ variant: "hint" })}>{formatComputedAt(report.computed_at)}</span>}
      </div>
      {error && <p className={textVariants({ variant: "error" })}>集計失敗: {error}</p>}
      {report && <FreshnessReportView report={report} />}
    </Card>
  );
}

/** 集計結果の描画。取得と分けてあるのは、認証の要る画面を通さずに見え方を確かめられる
 * ようにするため（この形なら固定のレポートを渡すだけで描画できる）。 */
function FreshnessReportView({ report }: { report: DerivedDataFreshnessResponse }) {
  const rows = rowsFromReport(report);
  const staleCount = rows.filter((row) => row.flagged).length;

  return (
    <>
      <StatusVerdict flagged={staleCount > 0}>
        {staleCount > 0 ? (
          <>
            <span>{staleCount}件が作り直し待ち</span>
            {/* 作り直しは本番VMで打つ。打つ形と理由は運用の文書が持つ（本番の置き場所の知識を画面に持たない）。 */}
            <span className={textVariants({ variant: "hint" })}>
              作り直しの手順: docs/conventions/deployment-sync.md「派生データの作り直し」
            </span>
          </>
        ) : (
          <span>すべて最新</span>
        )}
      </StatusVerdict>

      <StatusRowList groups={[{ rows }]} flaggedLabel="作り直しが必要" okLabel="最新" />
    </>
  );
}
