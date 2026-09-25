"use client";

import { formatMaterialValue, materialCatalogName, type AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { ExperimentSlot } from "@/types/experimentSlot";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/Table/Table";
import { textVariants } from "@/components/ui/Text/Text";
import { formatJstHourMinute } from "@/lib/time";

interface ComparisonPanelProps {
  slots: ExperimentSlot[];
  /** 軸id→名前（その回に送った重みの見出し）。 */
  axisLabels: Record<string, string>;
  /** 軸の並びと名前の正本（軸ごとの行を作る）。 */
  axes: readonly PreferenceAxisDef[];
  /** 材料の名前と単位（材料の値の行を作る）。 */
  materials: readonly AxisMaterialOption[];
}

interface MetricRow {
  label: string;
  format: (slot: ExperimentSlot) => string;
}

// 距離・獲得標高はルートそのものの量（材料の値には乗らない）。
const PHYSICAL_METRIC_ROWS: MetricRow[] = [
  { label: "距離", format: (s) => `${s.topCandidate.distance_km.toFixed(1)} km` },
  {
    label: "獲得標高",
    format: (s) => (s.topCandidate.elevation_gain_m != null ? `${Math.round(s.topCandidate.elevation_gain_m)} m` : "—"),
  },
];

// 材料の値の行（どれかの回が値を持つ材料だけ）。見出しは論理名だけ（物理名まで出すと見出しが伸び、値の列が画面の
// 外へ出る）。
function buildMaterialValueRows(slots: ExperimentSlot[], materials: readonly AxisMaterialOption[]): MetricRow[] {
  const materialIds = new Set<string>();
  for (const slot of slots) {
    for (const materialId of Object.keys(slot.topCandidate.material_values)) {
      materialIds.add(materialId);
    }
  }
  // 名前を引けない材料は行ごと出さない（材料idは内部名）。
  return [...materialIds].flatMap((materialId) => {
    const label = materialCatalogName(materialId, materials);
    if (label === undefined) return [];
    return [
      {
        label,
        format: (slot: ExperimentSlot) => {
          const value = slot.topCandidate.material_values[materialId];
          return value != null ? formatMaterialValue(materialId, value, materials) : "—";
        },
      },
    ];
  });
}

// 全軸を合成した総合難易度。軸には紐づかないので、表の末尾へ固定する。
const OVERALL_DIFFICULTY_ROW: MetricRow = {
  label: "総合難易度[絶対基準]",
  format: (s) => (s.topCandidate.overall_difficulty != null ? `${s.topCandidate.overall_difficulty.toFixed(1)}` : "—"),
};

// 軸ごとの難易度（0〜100の距離加重平均）の行。どれかの回が値を持つ軸だけ、カタログの並びで。
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

// その回に送った重み（backendが返した条件）。名前を引けない軸は軸idで埋めず件数だけ出す（軸idは内部名）。
function formatWeights(slot: ExperimentSlot, axisLabels: Record<string, string>): string {
  const entries = Object.entries(slot.conditions.route_preference);
  const named = entries.flatMap(([axisId, weight]) => {
    const label = axisLabels[axisId];
    return label === undefined ? [] : [`${label}${weight}`];
  });
  const unnamed = entries.length - named.length;
  return `pref ${[...named, ...(unnamed > 0 ? [`ほか${unnamed}軸`] : [])].join("/")}`;
}

/** 列の見出しへ載せきれない素性（正確な時刻・その回の重み）。見出しは時刻だけ（秒まで出すと列が伸びる）で、同じ分の
 * 2回は色で見分ける。 */
function slotProvenance(slot: ExperimentSlot, axisLabels: Record<string, string>): string {
  return `${slot.conditions.generated_at} / ${formatWeights(slot, axisLabels)}`;
}

/** 直近の生成結果を並べる比較表（列が回、行が量）。 */
export default function ComparisonPanel({ slots, axisLabels, axes, materials }: ComparisonPanelProps) {
  // 比べる相手がいない間は、何をすれば比べられるかを出す（空白だと壊れて見える）。
  if (slots.length < 2) {
    return (
      <p className={textVariants({ variant: "hint" })}>
        {slots.length === 0
          ? "ルートを生成すると、その回の結果がここへ積まれます。2回目以降を生成すると条件の違いを並べて比べられます。"
          : "もう1回生成すると、前回との違いをここで並べて比べられます。"}
      </p>
    );
  }

  const rows: MetricRow[] = [
    ...PHYSICAL_METRIC_ROWS,
    ...buildMaterialValueRows(slots, materials),
    ...buildAxisDifficultyRows(slots, axes),
    OVERALL_DIFFICULTY_ROW,
  ];

  return (
    <div className="flex flex-col gap-2">
      <p className={textVariants({ variant: "hint" })}>
        直近{slots.length}回の生成結果を並べています。各列はその回の先頭候補（最も易しい1本）で、
        行は上から順に、ルートそのものの量・材料の実測値・軸ごとの難易度（0〜100）・総合難易度です。
      </p>
      {/* 列は内容ではなく器の幅で決める。内容に合わせて伸ばすと、狭い画面で値の列が画面外へ出る。 */}
      <Table className="table-fixed [&_td]:[overflow-wrap:anywhere] [&_th]:whitespace-normal [&_th]:[overflow-wrap:anywhere]">
        <TableHead>
          <TableRow>
            <TableHeader />
            {slots.map((slot) => (
              <TableHeader key={slot.id} title={slotProvenance(slot, axisLabels)}>
                <span
                  className="mr-1 inline-block size-2.5 rounded-full"
                  style={{ background: slot.color }}
                  aria-hidden="true"
                />
                {formatJstHourMinute(new Date(slot.conditions.generated_at))}
              </TableHeader>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.label}>
              <TableHeader scope="row" className="w-24 whitespace-normal">
                {row.label}
              </TableHeader>
              {slots.map((slot) => (
                <TableCell key={slot.id}>{row.format(slot)}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
