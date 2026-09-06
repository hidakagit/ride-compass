"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button/Button";
import { Card } from "@/components/ui/Card/Card";
import { getDerivedDataFreshness } from "@/services/derivedDataFreshnessApi";
import type { DerivedDataFreshnessResponse } from "@/types/route";
import styles from "./DerivedDataFreshnessPanel.module.css";

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

function StaleBadge({ isStale }: { isStale: boolean }) {
  return (
    <span className={isStale ? styles.badgeStale : styles.badgeFresh}>{isStale ? "鮮度不整合あり" : "鮮度OK"}</span>
  );
}

// 「鮮度」タブ（/admin）から、派生データ（precomputeバッチの出力）の鮮度台帳
// （backend GET /api/admin/derived-data/freshness）を見るパネル。MaterialCoveragePanel
// （材料の値がNULL/未取得かという完成度）とは別の切り口——行は存在するが、参照している
// 生データの世代が最新の取込より古いままではないか、という鮮度・世代を見る。
// 集計はDB全表走査を伴うため、開いたとき自動ではなく「集計する」ボタン押下時のみ実行する。
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
    <Card className={styles.panel}>
      <div className={styles.heading}>派生データ鮮度台帳</div>
      <p className={styles.hint}>
        edge_attribute_counts・way_attribute_counts・designation_attributes・way_landcoverが参照している生データの世代
        （取込run）が、最新の成功済み取込より古いままではないかを機械判定する。elevation_attributesは
        source_*_import_run_id列を持たないため世代比較ではなく完成度（road_edgesとの行数差分）のみ表示する
        ——鮮度ではない点に注意。DB全体の走査を伴うため集計には時間がかかる（ボタン押下時のみ実行）。
      </p>
      <div className={styles.controls}>
        <Button onClick={handleFetch} disabled={loading}>
          {loading ? "集計中…" : report ? "再集計する" : "集計する"}
        </Button>
        {report && <span className={styles.summary}>集計時刻 {formatComputedAt(report.computed_at)}</span>}
      </div>
      {error && <p className={styles.error}>集計失敗: {error}</p>}
      {report && (
        <>
          {report.generations.map((generation) => (
            <div key={generation.table_name} className={styles.tableBlock}>
              <div className={styles.tableName}>
                <span className={styles.tableNameText}>{generation.table_name}</span>
                <span className={styles.rowCount}>{formatCount(generation.row_count)}行</span>
                <StaleBadge isStale={generation.is_stale} />
              </div>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th scope="col">比較対象</th>
                      <th scope="col" className={styles.numeric}>
                        最新取込run
                      </th>
                      <th scope="col" className={styles.numeric}>
                        反映済み最古run
                      </th>
                      <th scope="col" className={styles.numeric}>
                        NULL件数
                      </th>
                      <th scope="col">鮮度</th>
                    </tr>
                  </thead>
                  <tbody>
                    {generation.sources.map((source) => (
                      <tr key={source.run_table} data-stale={source.is_stale}>
                        <td>{source.label}</td>
                        <td className={styles.numeric}>{formatRunId(source.latest_available_run_id)}</td>
                        <td className={styles.numeric}>{formatRunId(source.earliest_reflected_run_id)}</td>
                        <td className={styles.numeric}>{formatCount(source.null_count)}</td>
                        <td>
                          <StaleBadge isStale={source.is_stale} />
                        </td>
                      </tr>
                    ))}
                    {generation.algorithm_version && (
                      <tr data-stale={generation.algorithm_version.is_stale}>
                        <td>アルゴリズム版数（{generation.algorithm_version.owner}）</td>
                        <td className={styles.numeric}>{generation.algorithm_version.current_version}</td>
                        <td className={styles.numeric}>{generation.algorithm_version.oldest_version ?? "-"}</td>
                        <td className={styles.numeric}>{formatCount(generation.algorithm_version.null_count)}</td>
                        <td>
                          <StaleBadge isStale={generation.algorithm_version.is_stale} />
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          ))}

          <div className={styles.tableBlock}>
            <div className={styles.tableName}>
              <span className={styles.tableNameText}>elevation_attributes</span>
              <span className={styles.completenessNote}>完成度（鮮度ではない）</span>
            </div>
            <p className={styles.hint}>
              road_edges {formatCount(report.elevation.road_edges_total)}件のうち、標高計算が未完了なEdgeが{" "}
              {formatCount(report.elevation.uncalculated_count)}件。
            </p>
          </div>
        </>
      )}
    </Card>
  );
}
