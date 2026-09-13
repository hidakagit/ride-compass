"use client";

import ErrorText from "@/components/ErrorText/ErrorText";
import InfoPopover from "@/components/Map/InfoPopover";
import { NewRouteIcon, RouteDiffIcon } from "@/components/Map/icons";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { formatDurationShort } from "@/lib/formatDuration";
import type { RouteCandidate } from "@/types/route";
import styles from "./RouteSplicePanel.module.css";

interface RouteSplicePanelProps {
  /** 編集の元。1本に固定で、地図で他候補を押しても変わらない。 */
  displayed: RouteCandidate;
  /** 適用済みの乗り換えの数。 */
  appliedCount: number;
  /** 次に選べる乗り換えがあるか（無ければ「他の候補と別の道を通る区間がありません」）。 */
  hasAlternatives: boolean;
  /** 直前の1手を戻す。 */
  onUndo: () => void;
  /** 「差分を見る」で評価した、いまの組み合わせの候補。まだ見ていなければnull。 */
  preview: RouteCandidate | null;
  /** 差分の評価を待っている間はtrue。 */
  previewing: boolean;
  /** いまの組み合わせを評価して結果を出す。 */
  onPreview: () => void;
  onApply: () => void;
  /** 合成した経路の評価を待っている間はtrue。 */
  applying: boolean;
  /** 合成に失敗した理由。押した場所から見えないと「押しても何も起きない」になる。 */
  error: string | null;
  /** 編集をやめて候補の一覧へ戻る。 */
  onCancel: () => void;
  /** 公開軸すべて（差分バーのラベルの正本）。 */
  axes: readonly PreferenceAxisDef[];
  /** 軸id→色（ルート設定パネルの軸チップと同じ色）。 */
  axisColors: Record<string, string>;
}

/** 寄与度の差がこれ未満の軸は差分バーへ出さない（1pxの破片が並ぶと読めない）。 */
const MIN_CONTRIBUTION_DELTA = 0.1;
/** 差分バーの下へ数値を書く軸の数。大きい順。 */
const LABELLED_DELTA_COUNT = 2;

function formatDelta(value: number, unit: string, digits: number): string {
  const rounded = Number(value.toFixed(digits));
  if (rounded === 0) return "±0";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(digits)}${unit}`;
}

/** 元→編集後で寄与度が動いた軸（大きい順）。減った軸は負、増えた軸は正。 */
export function contributionDeltas(
  base: Record<string, number>,
  after: Record<string, number>,
  axes: readonly PreferenceAxisDef[],
): { axisId: string; label: string; delta: number }[] {
  return axes
    .map((axis) => ({
      axisId: axis.axisId,
      label: axis.label,
      delta: (after[axis.axisId] ?? 0) - (base[axis.axisId] ?? 0),
    }))
    .filter((item) => Math.abs(item.delta) >= MIN_CONTRIBUTION_DELTA)
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
}

export default function RouteSplicePanel({
  displayed,
  appliedCount,
  hasAlternatives,
  onUndo,
  preview,
  previewing,
  onPreview,
  onApply,
  applying,
  error,
  onCancel,
  axes,
  axisColors,
}: RouteSplicePanelProps) {
  // edge_idsを返さないエンジン・古い候補では区間を出せない（backendが空で返す）。
  const unavailable = displayed.edge_ids.length === 0;
  const busy = previewing || applying;
  const deltas = preview ? contributionDeltas(displayed.axis_contributions, preview.axis_contributions, axes) : [];
  const scale = deltas.reduce((max, item) => Math.max(max, Math.abs(item.delta)), 0);

  const rows: { label: string; base: string; after: string | null; delta: number }[] = [
    {
      label: "距離",
      base: `${displayed.distance_km.toFixed(1)}km`,
      after: preview ? `${preview.distance_km.toFixed(1)}km` : null,
      delta: preview ? preview.distance_km - displayed.distance_km : 0,
    },
    {
      label: "所要",
      base: displayed.estimated_duration_seconds != null ? formatDurationShort(displayed.estimated_duration_seconds) : "—",
      after:
        preview?.estimated_duration_seconds != null ? formatDurationShort(preview.estimated_duration_seconds) : null,
      delta:
        preview?.estimated_duration_seconds != null && displayed.estimated_duration_seconds != null
          ? (preview.estimated_duration_seconds - displayed.estimated_duration_seconds) / 60
          : 0,
    },
    {
      label: "総合難易度",
      base: displayed.overall_difficulty != null ? `${Math.round(displayed.overall_difficulty)}` : "—",
      after: preview?.overall_difficulty != null ? `${Math.round(preview.overall_difficulty)}` : null,
      delta:
        preview?.overall_difficulty != null && displayed.overall_difficulty != null
          ? preview.overall_difficulty - displayed.overall_difficulty
          : 0,
    },
    {
      label: "負荷",
      base: displayed.difficulty_load != null ? `${Math.round(displayed.difficulty_load)}` : "—",
      after: preview?.difficulty_load != null ? `${Math.round(preview.difficulty_load)}` : null,
      delta:
        preview?.difficulty_load != null && displayed.difficulty_load != null
          ? preview.difficulty_load - displayed.difficulty_load
          : 0,
    },
  ];

  return (
    <section className={styles.panel} aria-labelledby="splice-heading">
      <div className={styles.headingRow}>
        <button type="button" className={styles.back} aria-label="編集をやめて候補へ戻る" onClick={onCancel}>
          ‹
        </button>
        <h3 className={styles.heading} id="splice-heading">
          区間の乗り換え
        </h3>
        {/* 使い方は画面へ書かずここへ置く（設計原則「冗長なものは削る」）。 */}
        <InfoPopover
          triggerClassName={styles.headingInfo}
          triggerAriaLabel="区間の乗り換えの説明"
          contentClassName={styles.headingInfoPopover}
        >
          地図の破線が、いまの道から乗り換えられる先です。タップするとそこへ乗り換わり、その先に
          分かれ道があれば次の破線が出ます。天秤は乗り換えた結果を評価するボタン、その隣は
          新しい候補として作るボタンです。差分バーは左へ伸びた軸ほど楽になっています。
        </InfoPopover>
        {!unavailable && (
          <div className={styles.headingActions}>
            <button
              type="button"
              className={styles.actionIcon}
              onClick={onPreview}
              disabled={appliedCount === 0 || busy}
              aria-busy={previewing}
              aria-label="差分を見る"
              title="差分を見る"
            >
              <RouteDiffIcon size={18} />
            </button>
            <button
              type="button"
              className={styles.actionIcon}
              onClick={onApply}
              disabled={appliedCount === 0 || busy}
              aria-busy={applying}
              aria-label="新しいルートを作る"
              title="新しいルートを作る"
            >
              <NewRouteIcon size={18} />
            </button>
          </div>
        )}
      </div>

      {unavailable ? (
        <p className={styles.note}>この候補は経路のEdge情報を持たないため、区間を出せません。</p>
      ) : (
        <>
          {/* 指標はルート結果パネルと同じもの。元と編集後を並べ、差は編集後の側へ添える。 */}
          <table className={styles.metrics}>
            <thead>
              <tr>
                <th />
                <th>元</th>
                <th>編集後</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label}>
                  <th scope="row">{row.label}</th>
                  <td className={styles.baseValue}>{row.base}</td>
                  <td className={styles.afterValue} data-worse={row.delta > 0} data-better={row.delta < 0}>
                    {row.after ?? "—"}
                    {row.after !== null && row.delta !== 0 && (
                      <span className={styles.metricDelta}>
                        {formatDelta(row.delta, "", row.label === "距離" ? 1 : 0)}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* 軸別は元・編集後の2本を並べず、差だけの1本にする。中央が0で、左が楽になった側。 */}
          {deltas.length > 0 && (
            <div className={styles.deltaBar}>
              <div className={styles.deltaEnds}>
                <span className={styles.better}>← 楽になった</span>
                <span className={styles.worse}>きつくなった →</span>
              </div>
              <div className={styles.deltaTrack} role="img" aria-label={deltas
                .map((item) => `${item.label} ${formatDelta(item.delta, "", 1)}`)
                .join("、")}>
                <div className={styles.deltaSide}>
                  {deltas
                    .filter((item) => item.delta < 0)
                    .map((item) => (
                      <span
                        key={item.axisId}
                        className={styles.deltaSegment}
                        style={{
                          width: `${(Math.abs(item.delta) / scale) * 50}%`,
                          background: axisColors[item.axisId] ?? "var(--color-muted)",
                        }}
                      />
                    ))}
                </div>
                <div className={styles.deltaCenter} />
                <div className={`${styles.deltaSide} ${styles.deltaSideRight}`}>
                  {deltas
                    .filter((item) => item.delta > 0)
                    .map((item) => (
                      <span
                        key={item.axisId}
                        className={styles.deltaSegment}
                        style={{
                          width: `${(Math.abs(item.delta) / scale) * 50}%`,
                          background: axisColors[item.axisId] ?? "var(--color-muted)",
                        }}
                      />
                    ))}
                </div>
              </div>
              <p className={styles.deltaLabels}>
                {deltas.slice(0, LABELLED_DELTA_COUNT).map((item) => (
                  <span key={item.axisId}>
                    {item.label} {formatDelta(item.delta, "", 1)}
                  </span>
                ))}
              </p>
            </div>
          )}

          {error && <ErrorText>{error}</ErrorText>}

          <div className={styles.footerRow}>
            <span className={styles.note}>
              {appliedCount > 0
                ? `${appliedCount}回乗り換え`
                : hasAlternatives
                  ? "地図の破線をタップして乗り換えます"
                  : "他の候補と別の道を通る区間がありません。"}
            </span>
            {appliedCount > 0 && (
              <button type="button" className={styles.undo} onClick={onUndo} disabled={busy}>
                1つ戻す
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
