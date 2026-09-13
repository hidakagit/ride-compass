"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button/Button";
import { Card } from "@/components/ui/Card/Card";
import InfoPopover from "@/components/Map/InfoPopover";
import floatingPopoverStyles from "@/components/ui/floatingPopover.module.css";
import { getDerivedDataFreshness } from "@/services/derivedDataFreshnessApi";
import type { DerivedDataFreshnessResponse } from "@/types/route";
import styles from "./DerivedDataFreshnessPanel.module.css";

/** 派生データを依存順に作り直す単一の入口（`backend/app/batch/refresh_derived.py`）を、
 * **本番へ効かせるために実際に打つ形**で置く。古い・未計算がどれであっても打つのはこの1つ
 * なので、行ごとにバッチ名を散らさず画面に1つだけ置く。手順の正本は
 * `docs/disaster-recovery.md`。
 *
 * 稼働中のbackendコンテナの中では走らせない——そのコンテナのメモリ上限まで使い切ると
 * コンテナごとOOM killされ、サービス全体が止まる。別のコンテナを`--memory`付きで立てれば、
 * 上限を超えても止まるのはバッチだけで済む。`--skip-landcover`は、土地被覆のラスタが
 * VM上に無く回せないため。 */
export const REBUILD_COMMAND = [
  "sudo docker run --rm --network=host --memory=4g \\",
  "  -v /home/ubuntu/ridecompass-cache-data:/app/data \\",
  "  --env-file /home/ubuntu/ridecompass-backend.env \\",
  "  ridecompass-backend:latest \\",
  "  python -m app.batch.refresh_derived --skip-landcover",
].join("\n");

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

/** 1件ぶんの状態。世代比較（取込runが古いか）と完成度（未計算が残っているか）は判定の方式が
 * 違うが、読み手が知りたいのは「作り直しが要るかどうか」で同じ。行の見た目を揃え、方式の
 * 違いは開いた先の中身で表す。 */
interface FreshnessRow {
  name: string;
  /** 名前の右に出す規模（行数・未計算件数）。 */
  scale: string;
  needsRebuild: boolean;
  detail: { label: string; value: string }[];
  note?: string;
}

export function rowsFromReport(report: DerivedDataFreshnessResponse): FreshnessRow[] {
  const generations: FreshnessRow[] = report.generations.map((generation) => ({
    name: generation.table_name,
    scale: `${formatCount(generation.row_count)}行`,
    needsRebuild: generation.is_stale,
    detail: [
      ...generation.sources.map((source) => ({
        label: source.label,
        value:
          `最新 ${formatRunId(source.latest_available_run_id)} / ` +
          `反映 ${formatRunId(source.earliest_reflected_run_id)}` +
          (source.null_count > 0 ? ` / 未記録 ${formatCount(source.null_count)}` : ""),
      })),
      ...(generation.algorithm_version
        ? [
            {
              label: "版数",
              value:
                `現在 ${generation.algorithm_version.current_version} / ` +
                `記録 ${generation.algorithm_version.oldest_version ?? "-"}` +
                (generation.algorithm_version.null_count > 0
                  ? ` / 未記録 ${formatCount(generation.algorithm_version.null_count)}`
                  : ""),
            },
          ]
        : []),
    ],
  }));

  const completeness: FreshnessRow[] = report.completeness.map((entry) => ({
    name: entry.label,
    scale: entry.is_incomplete ? `未計算 ${formatCount(entry.uncalculated_count)}` : "未計算なし",
    needsRebuild: entry.is_incomplete,
    detail: [
      { label: "母集団", value: `${formatCount(entry.population)}件` },
      { label: "未計算", value: `${formatCount(entry.uncalculated_count)}件` },
      { label: "担当バッチ", value: entry.owner },
    ],
    note: entry.note || undefined,
  }));

  return [...generations, ...completeness];
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard
      ?.writeText(text)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => setCopied(false));
  };
  return (
    <button type="button" className={styles.copyButton} onClick={handleCopy}>
      {copied ? "コピーした" : "コピー"}
    </button>
  );
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
    <Card className={styles.panel}>
      <div className={styles.headingRow}>
        <span className={styles.heading}>派生データ鮮度台帳</span>
        <InfoPopover
          triggerClassName={styles.infoButton}
          triggerAriaLabel="派生データ鮮度台帳の説明"
          contentClassName={floatingPopoverStyles.floatingPopover}
        >
          取り込んだ生データ（OSM・事故など）が新しくなったのに、そこから計算した派生データが
          古いまま残っていないかを機械判定する。対象はbackendの宣言が決めるため、バッチが増減しても
          一覧は自動で追従する。系譜を持たない派生データは世代を比べられないため、代わりに未計算が
          何件残っているかを数える。DB全体の走査を伴うため集計には時間がかかる。
        </InfoPopover>
      </div>
      <div className={styles.controls}>
        <Button onClick={handleFetch} disabled={loading}>
          {loading ? "集計中…" : report ? "再集計する" : "集計する"}
        </Button>
        {report && <span className={styles.summary}>{formatComputedAt(report.computed_at)}</span>}
      </div>
      {error && <p className={styles.error}>集計失敗: {error}</p>}
      {report && <FreshnessReportView report={report} />}
    </Card>
  );
}

/** 集計結果の描画。取得と分けてあるのは、認証の要る画面を通さずに見え方を確かめられる
 * ようにするため（この形なら固定のレポートを渡すだけで描画できる）。 */
export function FreshnessReportView({ report }: { report: DerivedDataFreshnessResponse }) {
  const rows = rowsFromReport(report);
  const staleCount = rows.filter((row) => row.needsRebuild).length;

  return (
    <>
      <div className={staleCount > 0 ? styles.verdictStale : styles.verdictFresh}>
        {staleCount > 0 ? (
          <>
            <span className={styles.verdictText}>{staleCount}件が作り直し待ち</span>
            <div className={styles.commandRow}>
              <code className={styles.command}>{REBUILD_COMMAND}</code>
              <div className={styles.commandActions}>
                <CopyButton text={REBUILD_COMMAND} />
                <InfoPopover
                  triggerClassName={styles.infoButton}
                  triggerAriaLabel="このコマンドをどこで打つかの説明"
                  contentClassName={floatingPopoverStyles.floatingPopover}
                >
                  打つ場所は本番VM（SSHで入る）。手元の端末で打っても、そこから見えるのは
                  開発用のDBで、本番は古いまま変わらない。稼働中のDBに対して実行したあとは
                  タイル材料キャッシュの世代を上げる必要がある（上げないと、既にキャッシュ済み
                  だったタイルだけ古い値のまま復元され続ける）。手順の正本は docs/disaster-recovery.md。
                </InfoPopover>
              </div>
            </div>
          </>
        ) : (
          <span className={styles.verdictText}>すべて最新</span>
        )}
      </div>

      <ul className={styles.rows}>
        {rows.map((row) => (
          <li key={row.name}>
            <details className={styles.row}>
              <summary className={styles.rowSummary}>
                <span className={row.needsRebuild ? styles.markStale : styles.markFresh} aria-hidden="true" />
                <span className={styles.rowName}>{row.name}</span>
                <span className={styles.rowScale}>{row.scale}</span>
                <span className={styles.srOnly}>{row.needsRebuild ? "作り直しが必要" : "最新"}</span>
              </summary>
              <dl className={styles.detail}>
                {row.detail.map((item) => (
                  <div key={item.label} className={styles.detailItem}>
                    <dt className={styles.detailLabel}>{item.label}</dt>
                    <dd className={styles.detailValue}>{item.value}</dd>
                  </div>
                ))}
              </dl>
              {row.note && <p className={styles.note}>{row.note}</p>}
            </details>
          </li>
        ))}
      </ul>
    </>
  );
}
