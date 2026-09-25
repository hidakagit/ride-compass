"use client";

import { vocabulary } from "@/types/generated/vocabulary";
import { getMaterialCoverage } from "@/features/admin/adminApi";
import { formatCount, ReportCard } from "./ReportCard";
import type { MaterialCoverageEntry, MaterialCoverageResponse } from "@/types/route";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/Table/Table";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

// 母集団の名前と欠損の扱いの見出し・説明は、材料カタログの宣言（backend domain/material_catalog.py）が配る。
const POPULATION_LABELS = Object.fromEntries(vocabulary.materialPopulations.map((p) => [p.key, p.label])) as Record<
  NonNullable<MaterialCoverageEntry["population"]>,
  string
>;

function formatPercent(ratio: number | null): string {
  return ratio === null ? "-" : `${(ratio * 100).toFixed(1)}%`;
}

/** 集計対象の材料を欠損割合の高い順に並べる（同率はカタログ順を維持する安定ソート）。 */
function sortByMissingRatioDesc(entries: readonly MaterialCoverageEntry[]): MaterialCoverageEntry[] {
  return [...entries].sort((a, b) => (b.missing_ratio ?? -1) - (a.missing_ratio ?? -1));
}

type MissingSemantics = NonNullable<MaterialCoverageEntry["missing_semantics"]>;

// 「欠損時の扱い」でグループ分けする（見出しと並びはbackendの宣言）。宣言に無い扱い・null（集計対象の材料には
// 付かないはずの値）の材料は、下の未分類グループが拾う——表から消える材料を作らない。
const GROUP_BY_SEMANTICS = Object.fromEntries(
  vocabulary.materialMissingSemantics.map((entry) => [
    entry.key,
    { title: entry.title, hint: entry.hint, affectsEvaluation: entry.affects_evaluation },
  ]),
) as Record<MissingSemantics, { title: string; hint: string; affectsEvaluation: boolean }>;

const GROUPS = (Object.keys(GROUP_BY_SEMANTICS) as MissingSemantics[]).map((semantics) => ({
  semantics,
  ...GROUP_BY_SEMANTICS[semantics],
}));

function CoverageTable({ entries }: { entries: readonly MaterialCoverageEntry[] }) {
  return (
    <Table>
      <TableHead>
        <TableRow>
          <TableHeader scope="col">材料</TableHeader>
          <TableHeader scope="col">母集団</TableHeader>
          <TableHeader scope="col">欠損割合</TableHeader>
        </TableRow>
      </TableHead>
      <TableBody>
        {entries.map((entry) => (
          <TableRow
            key={entry.material_id}
            data-affects-evaluation={
              entry.missing_semantics
                ? String(GROUP_BY_SEMANTICS[entry.missing_semantics]?.affectsEvaluation)
                : undefined
            }
          >
            <TableCell title={entry.source}>{entry.label}</TableCell>
            <TableCell>{entry.population ? POPULATION_LABELS[entry.population] : "-"}</TableCell>
            <TableCell>
              <div className="flex min-w-32 flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <span className="min-w-14 whitespace-nowrap text-right tabular-nums">
                    {formatPercent(entry.missing_ratio)}
                  </span>
                  <span
                    className="block h-1.5 max-w-full rounded-full bg-[var(--color-accent)] in-data-[affects-evaluation=false]:bg-[var(--color-border-strong)]"
                    role="presentation"
                    style={{ width: `${Math.round((entry.missing_ratio ?? 0) * 100)}%` }}
                  />
                </div>
                <span className={cn(textVariants({ variant: "note" }), "whitespace-nowrap tabular-nums")}>
                  {formatCount(entry.missing)} / {formatCount(entry.total)}
                </span>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

// 「材料」タブ（/admin）から、材料ごとの欠損割合（backend GET /api/admin/material-catalog/
// coverage）を見るパネル。欠損データを取込側で推測して埋めるのではなく、欠損の実態を
// 見えるようにして「埋めるかどうか」の判断を軸定義側へ委ねるための画面。
export default function MaterialCoveragePanel() {
  return (
    <ReportCard
      title="材料ごとの欠損割合"
      info={
        <>
          <p className="m-0 [&+&]:mt-2">
            材料の元データ（OSMタグ、または区間単位の派生テーブルの行）を持たない区間の割合。母集団は
            {POPULATION_LABELS.way}=取り込んだOSMのway全件、{POPULATION_LABELS.edge}=道路グラフの区間全件で、
            件数ベース（距離加重ではない）。
          </p>
          <p className="m-0 [&+&]:mt-2">
            材料名にマウスを乗せると欠損の判定根拠（参照しているタグ・テーブル）を表示する。集計はDB全体を
            走査するため手動実行。
          </p>
        </>
      }
      load={getMaterialCoverage}
      summary={(report) =>
        `${POPULATION_LABELS.way} ${formatCount(report.way_total)}件 ・ ${POPULATION_LABELS.edge} ${formatCount(report.edge_total)}件`
      }
    >
      {(report) => <CoverageReport report={report} />}
    </ReportCard>
  );
}

function CoverageReport({ report }: { report: MaterialCoverageResponse }) {
  const covered = sortByMissingRatioDesc(report.materials.filter((m) => m.excluded_reason === null));
  const excluded = report.materials.filter((m) => m.excluded_reason !== null);
  // 集計対象なのにmissing_semanticsがどのグループにも該当しない材料。本来は起きないが、
  // 黙って表から消えるとカバレッジ画面が「欠損0件」に見えるため、拾って明示する。
  const groupedSemantics = new Set<string>(GROUPS.map((group) => group.semantics));
  const ungrouped = covered.filter(
    (entry) => entry.missing_semantics === null || !groupedSemantics.has(entry.missing_semantics),
  );

  return (
    <>
      {GROUPS.map((group) => {
        const entries = covered.filter((entry) => entry.missing_semantics === group.semantics);
        if (entries.length === 0) return null;
        return (
          <section key={group.semantics} className="mt-2 flex flex-col gap-1" aria-label={group.title}>
            <div className={cn(textVariants({ variant: "body" }), "font-bold")}>{group.title}</div>
            <p className={textVariants({ variant: "hint" })}>{group.hint}</p>
            <CoverageTable entries={entries} />
          </section>
        );
      })}
      {ungrouped.length > 0 && (
        <section className="mt-2 flex flex-col gap-1" aria-label="欠損時の扱いが不明な材料">
          <div className={cn(textVariants({ variant: "body" }), "font-bold")}>欠損時の扱いが不明な材料</div>
          <p className={textVariants({ variant: "hint" })}>
            集計対象なのにmissing_semanticsが付いていない。backend側の宣言漏れの可能性がある。
          </p>
          <CoverageTable entries={ungrouped} />
        </section>
      )}
      {excluded.length > 0 && (
        <details
          className={cn(
            textVariants({ variant: "hint" }),
            "[&_summary]:cursor-pointer [&_ul]:mt-1 [&_ul]:mb-0 [&_ul]:pl-5",
          )}
        >
          <summary>集計対象外の材料（{excluded.length}件）</summary>
          <ul>
            {excluded.map((entry) => (
              <li key={entry.material_id}>
                <span className="text-[var(--foreground)]">{entry.label}</span>: {entry.excluded_reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
