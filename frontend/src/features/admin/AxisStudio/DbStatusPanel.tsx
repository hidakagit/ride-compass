"use client";

import { vocabulary } from "@/types/generated/vocabulary";
import { getDbStatus } from "@/features/admin/adminApi";
import type { DbStatusResponse } from "@/types/route";
import { formatCount, formatMoment, ReportCard } from "./ReportCard";
import { type StatusRow, StatusRowList, StatusVerdict } from "./StatusRowList";

function formatBytes(value: number): string {
  const mb = value / 1024 / 1024;
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}秒`;
  return `${Math.round(seconds / 60)}分`;
}

/** 「データ保守」タブの他のパネルと同じ1行の形。判定の種類（取込・テーブル・接続）が違っても、
 * 読み手が知りたいのは「注意が要るか」で同じなので見た目を揃える。 */
/** 行の見た目を揃えたぶん、何と何が並んでいるのかは見出しが引き受ける。並び順に根拠がある
 * 群（テーブルは容量の大きい順）は、その根拠も見出しへ書く。 */
interface StatusGroup {
  title: string;
  rows: StatusRow[];
}

/** 取込のrunの状態の呼び名（backendの宣言`SOURCE_RUN_STATUS_LABELS`）。宣言に無い状態は生のまま出す。 */
function runStatusLabel(status: string | null): string {
  return vocabulary.sourceRunStatuses.find((entry) => entry.key === status)?.label ?? status ?? "";
}

function groupsFromStatus(report: DbStatusResponse): StatusGroup[] {
  const imports: StatusRow[] = report.imports.map((entry) => ({
    name: entry.label,
    scale: entry.latest_id === null ? "記録なし" : `#${entry.latest_id} ${runStatusLabel(entry.latest_status)}`,
    flagged: entry.needs_attention,
    detail: [
      {
        label: "最終実行",
        value: `#${entry.latest_id ?? "-"} ・ ${formatMoment(entry.latest_finished_at)}`,
      },
      {
        label: "成功した最新",
        value:
          entry.latest_succeeded_id === null
            ? "なし"
            : `#${entry.latest_succeeded_id} ・ ${formatMoment(entry.latest_succeeded_finished_at)}`,
      },
      ...(entry.latest_item_count === null
        ? []
        : [
            {
              label: "取込件数",
              value: `${formatCount(entry.latest_item_count)}件`,
            },
          ]),
      ...Object.entries(entry.latest_identity).map(([key, value]) => ({
        label: key,
        value,
      })),
    ],
    note: entry.note || undefined,
  }));

  const connections: StatusRow = {
    // 見出しの「接続」と同じ名前にすると、群と行の区別がつかない。
    name: "同時接続",
    scale: `${report.connections.total} / ${report.connections.max_connections}`,
    flagged: report.connections.needs_attention,
    detail: [
      {
        label: "接続数",
        value: `${report.connections.total} / ${report.connections.max_connections}`,
      },
      {
        label: "未完了のまま放置",
        value:
          report.connections.idle_in_transaction === 0
            ? "なし"
            : `${report.connections.idle_in_transaction}件 ・ 最長 ${formatDuration(report.connections.longest_idle_transaction_seconds)}`,
      },
      {
        label: "実行中の最長",
        value:
          report.connections.longest_query_seconds <= 0
            ? "なし"
            : formatDuration(report.connections.longest_query_seconds),
      },
    ],
    note: report.connections.note || undefined,
  };

  // テーブルは数が多く（本番で20件超）、全部を並べると注意すべき行が埋もれる。注意のある
  // ものだけを行にし、残りは1行へ畳んで開いた先に一覧を置く。
  const tableRow = (entry: DbStatusResponse["tables"][number]): StatusRow => ({
    name: entry.table_name,
    scale: `${formatCount(entry.row_count)}行 ・ ${formatBytes(entry.total_bytes)}`,
    flagged: entry.needs_attention,
    detail: [
      { label: "行数", value: `${formatCount(entry.row_count)}件（実数）` },
      { label: "容量", value: formatBytes(entry.total_bytes) },
      { label: "統計の取得", value: formatMoment(entry.analyzed_at) },
      { label: "VACUUM", value: formatMoment(entry.vacuumed_at) },
      ...(entry.dead_tuples > 0 ? [{ label: "不要行", value: `${formatCount(entry.dead_tuples)}件` }] : []),
    ],
    note: entry.note || undefined,
  });

  const flagged = report.tables.filter((entry) => entry.needs_attention).map(tableRow);
  const rest = report.tables.filter((entry) => !entry.needs_attention);
  // 畳んだ行は、分けた基準（注意の有無）を自分で名乗る。「その他」では、隠された側が
  // 重要でないから省かれたのか、見るべきものが埋もれているのかが読めない。
  const restRow: StatusRow[] = rest.length
    ? [
        {
          name: `注意なし ${rest.length}テーブル`,
          scale: `${formatCount(sumRows(rest))}行 ・ ${formatBytes(sumBytes(rest))}`,
          flagged: false,
          detail: rest.map((entry) => ({
            label: entry.table_name,
            value: `${formatCount(entry.row_count)}行 ・ ${formatBytes(entry.total_bytes)}`,
          })),
        },
      ]
    : [];

  const tables = [...flagged, ...restRow];
  return [
    { title: "取込", rows: imports },
    { title: "接続", rows: [connections] },
    ...(tables.length ? [{ title: "テーブル（容量の大きい順）", rows: tables }] : []),
  ];
}

function sumRows(entries: DbStatusResponse["tables"]): number {
  return entries.reduce((sum, entry) => sum + entry.row_count, 0);
}

function sumBytes(entries: DbStatusResponse["tables"]): number {
  return entries.reduce((sum, entry) => sum + entry.total_bytes, 0);
}

/** ヘッダーへ出す母数。畳んだ行の「N テーブル」が何分のNなのかは、全体の数が同じ画面に
 * 無いと読めない。 */
function summaryOf(report: DbStatusResponse): string {
  return [
    `${formatCount(report.tables.length)}テーブル`,
    `${formatCount(sumRows(report.tables))}行`,
    formatBytes(report.database_bytes),
  ].join(" ・ ");
}

// 「データ保守」タブ（/admin）の3枚目。派生データ鮮度台帳が拠って立つ土台の側を見る——取込runが
// 失敗していないか、行が本当に入っているか、プランナが使う統計が取れているか、
// トランザクションが放置されていないか。
export default function DbStatusPanel() {
  return (
    <ReportCard
      title="本番DBの状態"
      info={
        <>
          派生データの鮮度が拠って立つ土台の側を見る。生データの取込そのものが失敗していないか、
          行が本当に入っているか、プランナが使う統計が取れているか、トランザクションが放置されて
          いないか。行数は統計値ではなく実数を数えるため、DB全体の走査を伴い集計には時間がかかる。
        </>
      }
      load={getDbStatus}
      summary={summaryOf}
    >
      {(report) => <StatusRows report={report} />}
    </ReportCard>
  );
}

/** 行の描画。取得と分けてあるのは、認証の要る画面を通さずに見え方を確かめられるようにするため。 */
function StatusRows({ report }: { report: DbStatusResponse }) {
  const groups = groupsFromStatus(report);
  const attentionCount = groups.flatMap((group) => group.rows).filter((row) => row.flagged).length;
  return (
    <>
      <StatusVerdict flagged={attentionCount > 0}>
        <span>{attentionCount > 0 ? `${attentionCount}件に注意` : "注意はなし"}</span>
      </StatusVerdict>
      <StatusRowList groups={groups} flaggedLabel="注意が要る" okLabel="問題なし" />
    </>
  );
}
