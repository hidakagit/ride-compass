"use client";

import { getDerivedDataFreshness } from "@/features/admin/adminApi";
import type { DerivedDataFreshnessResponse } from "@/types/route";
import { formatCount, ReportCard } from "./ReportCard";
import { type StatusRow, StatusRowList, StatusVerdict } from "./StatusRowList";
import { textVariants } from "@/components/ui/Text/Text";

function formatRunId(value: number | null): string {
  return value === null ? "-" : `#${value}`;
}

/** 表1つぶんの状態。作り直しが要るかはbackendが決め（`needs_rebuild`）、理由の違いは開いた先の中身で表す。 */
function rowsFromReport(report: DerivedDataFreshnessResponse): StatusRow[] {
  return report.tables.map((table) => {
    const incomplete = table.columns.filter((column) => column.is_incomplete);
    const absent = table.columns.filter((column) => !column.is_incomplete && column.null_count > 0);
    // 行そのものが無いケース。鮮度（世代）でも完成度（NULL）でも表に出ない。
    const missing = table.missing_rows ?? 0;
    return {
      name: table.table_name,
      scale: `${formatCount(table.row_count)}行`,
      flagged: table.needs_rebuild,
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
// 残っていないか」を見る。
export default function DerivedDataFreshnessPanel() {
  return (
    <ReportCard
      title="派生データ鮮度台帳"
      info={
        <>
          取り込んだ生データ（OSM・事故など）が新しくなったのに、そこから計算した派生データが
          古いまま残っていないかを機械判定する。対象はbackendの宣言（ORM）が決めるため、表や列が
          増減しても一覧は自動で追従する。あわせて値の列ごとに未計算の件数を数える——「確定して
          値が無い」列（橋の勾配・指定のない道など）は数に出すが作り直しの対象にはしない。
          DB全体の走査を伴うため集計には時間がかかる。
        </>
      }
      load={getDerivedDataFreshness}
    >
      {(report) => <FreshnessReportView report={report} />}
    </ReportCard>
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
