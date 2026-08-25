"use client";

import { SCORING_AXES } from "@/lib/evaluationAxes";
import type { ExperimentSlot } from "@/types/experimentSlot";
import styles from "./ComparisonPanel.module.css";

interface ComparisonPanelProps {
  slots: ExperimentSlot[];
  /** axis_id→表示名の辞書（改善計画T320）。route_preferenceの重み表示に使う。呼び出し側
   * （page.tsx）がuseAxisCatalog経由で取得したもの。以前はビルド時静的な
   * PREFERENCE_AXES（既存7軸固定）を直接参照しており、軸スタジオで新規公開した軸の重みが
   * 比較表のツールチップに出ず、非公開化した軸は`p[axis.axisId]`がundefinedのまま
   * 「風undefined」のような表示になっていた（実際に送信されたroute_preferenceの
   * キー集合＝Object.keys(p)を正とし、ラベルだけこの辞書から引く形へ修正）。 */
  axisLabels: Record<string, string>;
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
//
// 改善計画T320: pref行は`slot.conditions.route_preference`（その回のgenerateへ実際に
// 送られ、backendがエコーした条件）のキー集合（Object.keys(p)）を正とする。以前は
// ビルド時静的なPREFERENCE_AXES（既存7軸固定）を回していたため、軸スタジオで新規
// 公開した軸の重みが表示されず、非公開化された軸は`p[axis.axisId]`がundefinedのまま
// 表示されていた。ラベルはaxisLabels（呼び出し側がuseAxisCatalog経由で取得した動的
// 辞書）から引き、未知のaxis_id（axisLabelsに無い）はaxis_idそのものにフォールバックする。
function formatWeights(slot: ExperimentSlot, axisLabels: Record<string, string>): string {
  const s = slot.conditions.scoring_weights;
  const p = slot.conditions.route_preference;
  const scoreLine = `score ${SCORING_AXES.map((axis) => `${axis.label}${s[axis.weightKey]}`).join("/")}`;
  const prefLine = `pref ${Object.entries(p)
    .map(([axisId, weight]) => `${axisLabels[axisId] ?? axisId}${weight}`)
    .join("/")}`;
  return `${scoreLine}\n${prefLine}`;
}

function formatGeneratedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// 実験スロット間の比較表（研究インターフェース改善 §10-3）。行=メトリクス、列=スロット
// （生成のたびに自動保存された直近最大3件）。スロットが2件以上たまった時だけ表示する。
export default function ComparisonPanel({ slots, axisLabels }: ComparisonPanelProps) {
  if (slots.length < 2) return null;

  return (
    <div className="flex flex-col gap-2">
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
                <th key={slot.id} title={formatWeights(slot, axisLabels)}>
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
