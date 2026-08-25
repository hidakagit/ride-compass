// 軸スタジオ（改善計画T340）の値入力UX改善用、材料の「実タグ値→日本語ラベル」対訳表。
//
// 背景: highway/surface/smoothnessはOSMタグの生値でオープンエンドなため、
// AxisComposer.tsxの「値ごとのスコアを設定」欄はタグの生値をユーザーが暗記して手入力する
// 必要があった（2026-08-26ユーザー報告）。GET /api/material-catalog/{material_id}/values
// （backend/app/infrastructure/road_graph_repository.py:
// get_distinct_material_values）でDBに実在する値を動的取得し、既知の値にはここで
// ラベルを付ける。未知の値（新しいOSMタグ値がDBに現れた場合）はラベルを持たないため、
// 呼び出し側（AxisComposer.tsx）がタグ値そのままを表示するフォールバックを持つ。
//
// highway/surfaceは、地図の絞り込みUI（components/Map/roadFilterAxes.ts:
// HIGHWAY_GROUPS/SURFACE_GROUPS）が既に持つ「タグ値→表示グループ」の日本語ラベルを
// そのまま流用する（UI語彙のカタログ集約——同じ語彙を2箇所に手書きしない、CLAUDE.md
// 複雑度平衡の原則）。ただしroadFilterAxesのグルーピングは地図の色分け・線幅という
// 別目的（複数の生タグ値を1つの表示グループへ多対一で束ねる）のため、ここではグループの
// ラベルをそのタグ値の代表ラベルとして流用する形になる（例: asphalt/paved/chipselは
// いずれも「アスファルト」と表示される。軸スタジオの値ごとスコア設定自体はタグ値単位で
// 独立して行える——ラベル表示が同じでも、選択・保存される値（value）は元のタグ生値の
// ままで区別は保たれる）。
//
// smoothnessはOSM wikiの標準7値（+impassable）を直接ここで定義する（対応する表示用
// グルーピングが他に無いため、流用元が無い）。
import { HIGHWAY_GROUPS, SURFACE_GROUPS } from "@/components/Map/roadFilterAxes";

const SMOOTHNESS_LABELS: Readonly<Record<string, string>> = {
  excellent: "非常に良好（ロードバイク推奨）",
  good: "良好",
  intermediate: "普通",
  bad: "悪い",
  very_bad: "かなり悪い",
  horrible: "劣悪",
  very_horrible: "極めて劣悪",
  impassable: "通行不能",
};

function labelsFromGroups(groups: readonly { label: string; values: readonly string[] }[]): Record<string, string> {
  const labels: Record<string, string> = {};
  for (const group of groups) {
    for (const value of group.values) {
      labels[value] = group.label;
    }
  }
  return labels;
}

// 材料id→(タグ値→日本語ラベル)の対訳表。ここに無い材料id・ここにあっても未知のタグ値は
// ラベル無し（呼び出し側がタグ値そのままにフォールバックする）。
export const MATERIAL_VALUE_LABELS: Readonly<Record<string, Readonly<Record<string, string>>>> = {
  highway: labelsFromGroups(HIGHWAY_GROUPS),
  surface: labelsFromGroups(SURFACE_GROUPS),
  smoothness: SMOOTHNESS_LABELS,
};

/** 材料idとタグ生値から日本語ラベルを引く。未登録の材料id・未知のタグ値はvalueそのまま
 * （フォールバック）。 */
export function materialValueLabel(materialId: string, value: string): string {
  return MATERIAL_VALUE_LABELS[materialId]?.[value] ?? value;
}
