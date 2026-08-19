"use client";

import { PREFERENCE_AXES, SCORING_AXES } from "@/lib/evaluationAxes";
import type { ExperimentSlot } from "@/types/experimentSlot";
import styles from "./ComparisonPanel.module.css";

interface ComparisonPanelProps {
  slots: ExperimentSlot[];
}

interface MetricRow {
  label: string;
  format: (slot: ExperimentSlot) => string;
}

// 生値と絶対基準difficultyのみを比較対象にする。total_scoreは同一generate呼び出し内の
// 候補間でしか比較できない相対値のため、実験（スロット）間の比較表には出さない
// （相対評価の誤用防止をUIで強制する、研究インターフェース改善 §10-3）。
const METRIC_ROWS: MetricRow[] = [
  { label: "距離", format: (s) => `${s.topCandidate.distance_km.toFixed(1)} km` },
  {
    label: "獲得標高",
    format: (s) => (s.topCandidate.elevation_gain_m != null ? `${Math.round(s.topCandidate.elevation_gain_m)} m` : "—"),
  },
  {
    label: "風スコア",
    format: (s) => (s.topCandidate.wind_score != null ? `${s.topCandidate.wind_score.toFixed(1)} m/s` : "—"),
  },
  {
    label: "舗装率",
    format: (s) => (s.topCandidate.road_score != null ? `${Math.round(s.topCandidate.road_score)}%` : "—"),
  },
  {
    label: "停止密度",
    format: (s) => (s.topCandidate.stop_density != null ? `${s.topCandidate.stop_density.toFixed(2)} 回/km` : "—"),
  },
  {
    label: "車の圧迫感",
    format: (s) =>
      s.topCandidate.car_stress_score != null ? `${s.topCandidate.car_stress_score.toFixed(1)}` : "—",
  },
  {
    label: "自転車インフラ率",
    format: (s) =>
      s.topCandidate.bicycle_infra_score != null ? `${Math.round(s.topCandidate.bicycle_infra_score)}%` : "—",
  },
  {
    label: "交差点密度",
    format: (s) =>
      s.topCandidate.intersection_density != null ? `${s.topCandidate.intersection_density.toFixed(2)} 回/km` : "—",
  },
  {
    label: "事故密度",
    format: (s) =>
      s.topCandidate.accident_density != null ? `${s.topCandidate.accident_density.toFixed(2)} 件/(km・年)` : "—",
  },
  {
    label: "総合難易度[絶対基準]",
    format: (s) => (s.topCandidate.overall_difficulty != null ? `${s.topCandidate.overall_difficulty.toFixed(1)}` : "—"),
  },
];

// 重み表示は評価軸カタログ（lib/evaluationAxes.ts）から生成する（改善計画T45）。
// 以前はここへ手作業で軸を列挙しており、静的属性P1で追加されたstop_weightが
// 実験条件の表示から漏れていた（研究モードでstop_weightを変えて比較しても、
// 条件表示に差が現れず「同条件なのに結果が違う」ように見える実害があった）。
// カタログはWeightPanel/RouteListと同じ表示名を使うため、ラベルも自動的に揃う。
function formatWeights(slot: ExperimentSlot): string {
  const s = slot.conditions.scoring_weights;
  const p = slot.conditions.route_preference;
  const scoreLine = `score ${SCORING_AXES.map((axis) => `${axis.label}${s[axis.weightKey]}`).join("/")}`;
  const prefLine = `pref ${PREFERENCE_AXES.map((axis) => `${axis.label}${p[axis.weightKey]}`).join("/")}`;
  return `${scoreLine}\n${prefLine}`;
}

function formatGeneratedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// 実験スロット間の比較表（研究インターフェース改善 §10-3）。行=メトリクス、列=スロット
// （生成のたびに自動保存された直近最大3件）。スロットが2件以上たまった時だけ表示する。
export default function ComparisonPanel({ slots }: ComparisonPanelProps) {
  if (slots.length < 2) return null;

  return (
    <div className={styles.panel}>
      <p className={styles.hint}>
        直近{slots.length}回の生成結果を比較[各列は各回のtotal_score最上位候補。生値・絶対難易度のみで、
        リクエスト間の比較ができないtotal_scoreは含まない]
      </p>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th />
              {slots.map((slot) => (
                <th key={slot.id} title={formatWeights(slot)}>
                  <span className={styles.swatch} style={{ background: slot.color }} aria-hidden="true" />
                  {formatGeneratedAt(slot.conditions.generated_at)}
                  <br />
                  <span className={styles.engine}>{slot.engine}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {METRIC_ROWS.map((row) => (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                {slots.map((slot) => (
                  <td key={slot.id}>{row.format(slot)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
