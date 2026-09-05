"use client";

import { formatMaterialValue, materialCatalogLabel, type AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { ExperimentSlot } from "@/types/experimentSlot";
import styles from "./ComparisonPanel.module.css";

interface ComparisonPanelProps {
  slots: ExperimentSlot[];
  /** axis_id→表示名の辞書。route_preferenceの重み表示に使う。呼び出し側（page.tsx）が
   * useAxisCatalog経由で取得したもの。実際に送信されたroute_preferenceのキー集合
   * （Object.keys(p)）を正とし、ラベルだけこの辞書から引く。 */
  axisLabels: Record<string, string>;
  /** 評価軸カタログ（axis_id・label・並び順の正本）。呼び出し側（page.tsx）が
   * useAxisCatalog().axesを渡す（RouteAxisProfileと同じ渡し方）。個別軸の生値行を
   * この一覧から`topCandidate.axis_difficulties[axisId]`ベースで動的生成することで、
   * 軸スタジオの軸増減へ自動追従させる（ハードコードした軸id→ラベル辞書は持たない）。 */
  axes: readonly PreferenceAxisDef[];
  /** 材料カタログ（material_id→label/unit、呼び出し側がuseMaterialCatalog()を渡す）。
   * `topCandidate.material_values`の行（風の追加負荷等）のラベル・単位表記に使う。
   * カタログに無いmaterial_id（表示専用に格下げされた旧材料等）はidそのものをラベルに、
   * 単位無しにフォールバックする。 */
  materials: readonly AxisMaterialOption[];
}

interface MetricRow {
  label: string;
  format: (slot: ExperimentSlot) => string;
}

// 距離・獲得標高は材料（重み>0の軸が参照するもの）ではなくルート自体の属性のため、
// material_valuesには乗らない固定行として残す。
const PHYSICAL_METRIC_ROWS: MetricRow[] = [
  { label: "距離", format: (s) => `${s.topCandidate.distance_km.toFixed(1)} km` },
  {
    label: "獲得標高",
    format: (s) => (s.topCandidate.elevation_gain_m != null ? `${Math.round(s.topCandidate.elevation_gain_m)} m` : "—"),
  },
];

// 材料値の生値行（重み>0の軸が参照する材料id→値、backend: RouteCandidate.material_values）。
// いずれかのスロットが値を持つ材料だけを行にする（buildAxisDifficultyRowsと同じ「実際に
// 評価できたものだけ表示する」規約）。ラベル・単位は材料カタログから引き、軸スタジオで
// 軸の参照材料が変わっても表示は自動追従する（material_id→ラベルのハードコード無し）。
function buildMaterialValueRows(slots: ExperimentSlot[], materials: readonly AxisMaterialOption[]): MetricRow[] {
  const materialIds = new Set<string>();
  for (const slot of slots) {
    for (const materialId of Object.keys(slot.topCandidate.material_values)) {
      materialIds.add(materialId);
    }
  }
  return [...materialIds].map((materialId) => ({
    label: materialCatalogLabel(materialId, materials),
    format: (slot: ExperimentSlot) => {
      const value = slot.topCandidate.material_values[materialId];
      return value != null ? formatMaterialValue(materialId, value, materials) : "—";
    },
  }));
}

// 全軸を合成した総合difficulty（RouteSegmentDetail.difficulty由来、domain/difficulty.py）。
// 特定のaxis_idに紐づかず「全軸の合成結果」という別概念のため、下記の個別軸行とは別枠で
// 表の末尾に固定する（routeStyleModes.tsのdifficultyモードが個別軸の汎用パターンに
// 乗らないのと同じ理由づけ）。
const OVERALL_DIFFICULTY_ROW: MetricRow = {
  label: "総合難易度[絶対基準]",
  format: (s) => (s.topCandidate.overall_difficulty != null ? `${s.topCandidate.overall_difficulty.toFixed(1)}` : "—"),
};

// 個別軸の生値行: `RouteCandidate.axis_difficulties`（axis_id→difficulty 0-100の
// 距離加重平均）ベースで動的に生成する。軸カタログ（`axes`、呼び出し側が
// useAxisCatalog().axesを渡す）の並び順をそのまま使い、表示するスロットのいずれか
// 1件でも値を持つ軸だけを行として残す（RouteAxisProfile.tsxの「このルートで実際に
// 評価できた軸だけ表示する」フィルタと同じ規約）。軸スタジオが軸を追加・削除する
// たびにこの表の行も自動で増減する（ハードコードした軸id一覧を持たないため手動追記が
// 不要）。風（wind）・舗装質（surface_q）の軸もここに含まれうるが、上記
// PHYSICAL_METRIC_ROWSの風スコア・舗装率（生の物理量）とは単位・意味が異なる別情報の
// ため、重複ではなく併存として扱う。
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

// 重み表示は評価軸カタログ（lib/evaluationAxes.ts）から生成する。ハードコードした
// 軸一覧を持たないため、軸が増減しても表示から漏れない。カタログはRouteSettingsPanel/
// RouteListと同じ表示名を使うため、ラベルも自動的に揃う。
//
// pref行は`slot.conditions.route_preference`（その回のgenerateへ実際に送られ、
// backendがエコーした条件）のキー集合（Object.keys(p)）を正とする。ラベルは
// axisLabels（呼び出し側がuseAxisCatalog経由で取得した動的辞書）から引き、未知の
// axis_id（axisLabelsに無い）はaxis_idそのものにフォールバックする。
function formatWeights(slot: ExperimentSlot, axisLabels: Record<string, string>): string {
  const p = slot.conditions.route_preference;
  return `pref ${Object.entries(p)
    .map(([axisId, weight]) => `${axisLabels[axisId] ?? axisId}${weight}`)
    .join("/")}`;
}

function formatGeneratedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// 実験スロット間の比較表（研究インターフェース改善 §10-3）。行=メトリクス、列=スロット
// （生成のたびに自動保存された直近最大3件）。スロットが2件以上たまった時だけ表示する。
export default function ComparisonPanel({ slots, axisLabels, axes, materials }: ComparisonPanelProps) {
  if (slots.length < 2) return null;

  // 表示順: ルート属性（距離・獲得標高）→ 材料値の生値（material_values駆動）→ 個別軸の
  // 生値（axis_difficulties駆動、軸スタジオの軸増減に自動追従）→ 全軸合成の総合難易度。
  const rows: MetricRow[] = [
    ...PHYSICAL_METRIC_ROWS,
    ...buildMaterialValueRows(slots, materials),
    ...buildAxisDifficultyRows(slots, axes),
    OVERALL_DIFFICULTY_ROW,
  ];

  return (
    <div className="flex flex-col gap-2">
      <p className={styles.hint}>
        直近{slots.length}回の生成結果を比較[各列は各回のoverall_difficulty最小候補。生の物理量・軸別難易度[0-100、絶対基準、軸スタジオの重みで自動追従]・総合難易度]
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
