"use client";

import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
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
  /** 評価軸カタログ（axis_id・label・並び順の正本、改善計画T421）。呼び出し側
   * （page.tsx）がuseAxisCatalog().axesを渡す（RouteAxisProfileと同じ渡し方）。
   * 個別軸の生値行（旧: 停止密度・車の圧迫感・自転車インフラ率・交差点密度・事故密度、
   * RouteCandidateのレガシー1軸1フィールド固定設計）を、この一覧から
   * `topCandidate.axis_difficulties[axisId]`ベースで動的生成することで、軸スタジオの
   * 軸増減へ自動追従させる（新しいハードコードした軸id→ラベル辞書は増やさない）。 */
  axes: readonly PreferenceAxisDef[];
}

interface MetricRow {
  label: string;
  format: (slot: ExperimentSlot) => string;
}

// 生の物理量（m・m/s・%）を比較対象にする静的行。distance_km・elevation_gain_m・
// wind_score・road_scoreはRouteCandidateの旧scoring.yaml時代のレガシーフィールドだが、
// axis_difficulties（0-100の正規化されたdifficulty）とは単位・意味が異なる生の物理量で
// あり、研究モードでは物理量そのものを見たい場面があるためそのまま残す（改善計画T421
// 調査結果、RouteListとは異なりComparisonPanelは詳細比較ツールという設計思想のため
// 単純化はしない）。total_scoreは同一generate呼び出し内の候補間でしか比較できない
// 相対値のため、実験（スロット）間の比較表には出さない（相対評価の誤用防止をUIで
// 強制する、研究インターフェース改善 §10-3）。
const PHYSICAL_METRIC_ROWS: MetricRow[] = [
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
];

// 全軸を合成した総合difficulty（RouteSegmentDetail.difficulty由来、domain/difficulty.py）。
// 特定のaxis_idに紐づかず「全軸の合成結果」という別概念のため、下記の個別軸行とは別枠で
// 表の末尾に固定する（routeStyleModes.tsのdifficultyモードが個別軸の汎用パターンに
// 乗らない、と同じ理由づけ。改善計画T421再検証結果）。
const OVERALL_DIFFICULTY_ROW: MetricRow = {
  label: "総合難易度[絶対基準]",
  format: (s) => (s.topCandidate.overall_difficulty != null ? `${s.topCandidate.overall_difficulty.toFixed(1)}` : "—"),
};

// 個別軸の生値行（改善計画T421）: `RouteCandidate.axis_difficulties`
// （axis_id→difficulty 0-100の距離加重平均、改善計画T402）ベースで動的に生成する。
// 軸カタログ（`axes`、呼び出し側がuseAxisCatalog().axesを渡す）の並び順をそのまま使い、
// 表示するスロットのいずれか1件でも値を持つ軸だけを行として残す（RouteAxisProfile.tsxの
// 「このルートで実際に評価できた軸だけ表示する」フィルタと同じ規約）。軸スタジオが軸を
// 追加・削除するたびにこの表の行も自動で増減し、以前の固定5行（停止密度・車の圧迫感・
// 自転車インフラ率・交差点密度・事故密度）のような手動追記漏れ（コメントに残る
// 「stop_weight漏れ」実績と同種の問題）が起きなくなる。風（wind）・舗装質（surface_q）の
// 軸もここに含まれうるが、上記PHYSICAL_METRIC_ROWSの風スコア・舗装率（生の物理量）とは
// 単位・意味が異なる別情報のため、重複ではなく併存として扱う。
function buildAxisDifficultyRows(slots: ExperimentSlot[], axes: readonly PreferenceAxisDef[]): MetricRow[] {
  return axes
    .filter((axis) => slots.some((slot) => slot.topCandidate.axis_difficulties[axis.axisId] != null))
    .map((axis) => ({
      label: axis.label,
      format: (slot: ExperimentSlot) => {
        const value = slot.topCandidate.axis_difficulties[axis.axisId];
        return value != null ? value.toFixed(1) : "—";
      },
    }));
}

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
export default function ComparisonPanel({ slots, axisLabels, axes }: ComparisonPanelProps) {
  if (slots.length < 2) return null;

  // 表示順: 生の物理量（距離・獲得標高・風スコア・舗装率）→ 個別軸の生値
  // （axis_difficulties駆動、軸スタジオの軸増減に自動追従）→ 全軸合成の総合難易度。
  const rows: MetricRow[] = [...PHYSICAL_METRIC_ROWS, ...buildAxisDifficultyRows(slots, axes), OVERALL_DIFFICULTY_ROW];

  return (
    <div className="flex flex-col gap-2">
      <p className={styles.hint}>
        直近{slots.length}回の生成結果を比較[各列は各回のtotal_score最上位候補。生の物理量・軸別難易度[0-100、絶対基準、軸スタジオの重みで自動追従]・
        総合難易度のみで、リクエスト間の比較ができないtotal_scoreは含まない]
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
            {rows.map((row) => (
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
