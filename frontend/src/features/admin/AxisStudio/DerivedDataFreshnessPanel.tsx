"use client";

import { getDerivedDataFreshness } from "@/features/admin/adminApi";
import type { DerivedDataFreshnessResponse } from "@/types/route";
import { formatCount, ReportCard } from "./ReportCard";
import { type StatusRow, StatusRowList, StatusVerdict } from "./StatusRowList";
import { textVariants } from "@/components/ui/Text/Text";

/** ソース1つぶんの状態。作り直しが要るかはbackendが決め（`needs_rebuild`）、理由の違いは開いた先の中身で表す。 */
function sourceRows(report: DerivedDataFreshnessResponse): StatusRow[] {
  return report.sources.map((source) => ({
    name: source.source,
    scale: "",
    flagged: source.needs_rebuild,
    detail: [
      {
        label: "成功した最新の取込",
        value: source.latest_run_id === null ? "なし（取込が1度も成功していない）" : `#${source.latest_run_id}`,
      },
      {
        label: "作り直しに使った取込",
        value: source.derived_run_id === null ? "なし（まだ作り直しに使っていない）" : `#${source.derived_run_id}`,
      },
    ],
  }));
}

function nullsOf(column: DerivedDataFreshnessResponse["tables"][number]["columns"][number]): string {
  return [
    ...(column.uncalculated_count > 0 ? [`未計算 ${formatCount(column.uncalculated_count)}件`] : []),
    ...(column.absent_count > 0 ? [`値なし ${formatCount(column.absent_count)}件（確定）`] : []),
  ].join(" / ");
}

/** 表1つぶんの状態。作り直しが要るかはbackendが決め（`needs_rebuild`）、理由の違いは開いた先の中身で表す。 */
function tableRows(report: DerivedDataFreshnessResponse): StatusRow[] {
  return report.tables.map((table) => {
    const incomplete = table.columns.filter((column) => column.uncalculated_count > 0);
    const absent = table.columns.filter((column) => column.uncalculated_count === 0 && column.absent_count > 0);
    return {
      name: table.table_name,
      scale: `${formatCount(table.row_count)}行`,
      flagged: table.needs_rebuild,
      detail: [
        // 行そのものが欠けるケース。完成度（NULL）では表に出ない。
        ...(table.coverage === null
          ? []
          : [
              {
                label: `${table.coverage.parent} を覆う`,
                value:
                  table.coverage.missing_rows > 0
                    ? `${formatCount(table.coverage.missing_rows)}件ぶん行が無い（母数 ${formatCount(table.coverage.parent_row_count)}）`
                    : `欠けなし（母数 ${formatCount(table.coverage.parent_row_count)}）`,
              },
            ]),
        ...[...incomplete, ...absent].map((column) => ({ label: column.column, value: nullsOf(column) })),
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
          古いまま残っていないかを、ソースごとに今の派生を作った取込と成功した最新の取込を比べて
          機械判定する。対象の表はbackendの宣言（ORM）が決めるため、表や列が増減しても一覧は自動で
          追従する。あわせて値の列ごとに未計算の件数を数える——「確定して値が無い」もの（橋の勾配・
          指定のない道・有効画素が足りない土地被覆など）は数に出すが作り直しの対象にはしない。
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
  const sources = sourceRows(report);
  const tables = tableRows(report);
  const staleCount = [...sources, ...tables].filter((row) => row.flagged).length;

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

      <StatusRowList
        groups={[
          { title: "取込", rows: sources },
          { title: "派生の表", rows: tables },
        ]}
        flaggedLabel="作り直しが必要"
        okLabel="最新"
      />
    </>
  );
}
