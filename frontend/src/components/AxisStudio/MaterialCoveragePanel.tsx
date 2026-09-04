"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button/Button";
import { Card } from "@/components/ui/Card/Card";
import InfoPopover from "@/components/Map/InfoPopover";
import recipeControlStyles from "@/components/Map/recipeControls.module.css";
import { getMaterialCoverage } from "@/services/materialCoverageApi";
import type { MaterialCoverageEntry, MaterialCoverageResponse } from "@/types/route";
import styles from "./MaterialCoveragePanel.module.css";

const POPULATION_LABELS: Record<NonNullable<MaterialCoverageEntry["population"]>, string> = {
  way: "Way",
  edge: "Edge",
};

function formatPercent(ratio: number | null): string {
  return ratio === null ? "-" : `${(ratio * 100).toFixed(1)}%`;
}

function formatCount(value: number | null): string {
  return value === null ? "-" : value.toLocaleString("ja-JP");
}

function formatComputedAt(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString("ja-JP");
}

/** 集計対象の材料を欠損割合の高い順に並べる（同率はカタログ順を維持する安定ソート）。 */
export function sortByMissingRatioDesc(entries: readonly MaterialCoverageEntry[]): MaterialCoverageEntry[] {
  return [...entries].sort((a, b) => (b.missing_ratio ?? -1) - (a.missing_ratio ?? -1));
}

// 「欠損時の扱い」でグループ分けする。欠損が「不明」（軸が評価対象外になる）の材料と、
// タグ不在をそのまま確定値（非該当等）として評価する材料は、欠損割合の数字が同じでも
// 意味が正反対のため、同じ表へ並べず見出しで分ける。
const GROUPS: ReadonlyArray<{
  semantics: NonNullable<MaterialCoverageEntry["missing_semantics"]>;
  title: string;
  hint: string;
}> = [
  {
    semantics: "unknown",
    title: "評価に影響する欠損",
    hint: "元データが無い区間では、この材料を使う軸が評価対象外になる。",
  },
  {
    semantics: "definite",
    title: "タグ不在を確定値として評価する材料（参考）",
    hint: "欠損は「該当なし」を意味し、評価に穴は開かない。",
  },
];

function CoverageTable({ entries }: { entries: readonly MaterialCoverageEntry[] }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">材料</th>
            <th scope="col">母集団</th>
            <th scope="col">欠損割合</th>
            <th scope="col" className={styles.numeric}>
              欠損 / 総数
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.material_id} data-missing-semantics={entry.missing_semantics ?? undefined}>
              <td title={entry.source}>{entry.label}</td>
              <td>{entry.population ? POPULATION_LABELS[entry.population] : "-"}</td>
              <td>
                <div className={styles.ratioCell}>
                  <span className={styles.ratioValue}>{formatPercent(entry.missing_ratio)}</span>
                  <span
                    className={styles.ratioBar}
                    role="presentation"
                    style={{ width: `${Math.round((entry.missing_ratio ?? 0) * 100)}%` }}
                  />
                </div>
              </td>
              <td className={styles.numeric}>
                {formatCount(entry.missing)} / {formatCount(entry.total)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// 「材料」タブ（/admin）から、材料ごとの欠損割合（backend GET /api/admin/material-catalog/
// coverage）を見るパネル。欠損データを取込側で推測して埋めるのではなく、欠損の実態を
// 見えるようにして「埋めるかどうか」の判断を軸定義側へ委ねるための画面。
// 集計はosm_raw_ways/road_edgesの全表走査を伴うため、開いたとき自動ではなく「集計する」
// ボタン押下時のみ実行する（DerivedDataFreshnessPanelと同じ流儀）。
export default function MaterialCoveragePanel() {
  const [report, setReport] = useState<MaterialCoverageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleFetch = () => {
    setLoading(true);
    setError(null);
    getMaterialCoverage()
      .then((result) => setReport(result))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  };

  const covered = report ? sortByMissingRatioDesc(report.materials.filter((m) => m.excluded_reason === null)) : [];
  const excluded = report ? report.materials.filter((m) => m.excluded_reason !== null) : [];

  return (
    <Card className={styles.panel}>
      <div className={styles.headingRow}>
        <div className={styles.heading}>材料ごとの欠損割合</div>
        <InfoPopover
          triggerClassName={recipeControlStyles.infoButton}
          triggerAriaLabel="欠損割合の見方"
          contentClassName={recipeControlStyles.infoTooltip}
        >
          <p className={styles.popoverParagraph}>
            材料の元データ（OSMタグ、またはEdge単位の派生テーブルの行）を持たない区間の割合。母集団はWay=
            osm_raw_ways全件、Edge=road_edges全件で、件数ベース（距離加重ではない）。
          </p>
          <p className={styles.popoverParagraph}>
            材料名にマウスを乗せると欠損の判定根拠（参照しているタグ・テーブル）を表示する。集計はDB全体を
            走査するため手動実行。
          </p>
        </InfoPopover>
      </div>
      <div className={styles.controls}>
        <Button onClick={handleFetch} disabled={loading}>
          {loading ? "集計中…" : report ? "再集計する" : "集計する"}
        </Button>
        {report && (
          <span className={styles.summary}>
            集計時刻 {formatComputedAt(report.computed_at)} ・ Way {formatCount(report.way_total)}件 ・ Edge{" "}
            {formatCount(report.edge_total)}件
          </span>
        )}
      </div>
      {error && <p className={styles.error}>集計失敗: {error}</p>}
      {report && (
        <>
          {GROUPS.map((group) => {
            const entries = covered.filter((entry) => entry.missing_semantics === group.semantics);
            if (entries.length === 0) return null;
            return (
              <section key={group.semantics} className={styles.group} aria-label={group.title}>
                <div className={styles.groupTitle}>{group.title}</div>
                <p className={styles.hint}>{group.hint}</p>
                <CoverageTable entries={entries} />
              </section>
            );
          })}
          {excluded.length > 0 && (
            <details className={styles.excluded}>
              <summary>集計対象外の材料（{excluded.length}件）</summary>
              <ul>
                {excluded.map((entry) => (
                  <li key={entry.material_id}>
                    <span className={styles.excludedLabel}>{entry.label}</span>: {entry.excluded_reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </Card>
  );
}
