// @vitest-environment node
// 道をクリックしたときに出す「この道の事実」の組み立て（純関数）。
import { describe, expect, it } from "vitest";
import materialCatalog from "@/types/generated/material-catalog.json";

import { roadDisplayName, roadFactRows } from "./roadFacts";

/** 項目名は材料カタログの名前（テストでも書き写さない）。 */
const materialOf = (materialId: string) => materialCatalog.find((m) => m.material_id === materialId)!;
const labelOf = (materialId: string) => materialOf(materialId).name;
/** 材料の値のうち、呼び名を持つ最初の1つ（値も呼び名も書き写さない）。 */
const labeledValueOf = (materialId: string): [string, string] =>
  Object.entries(materialOf(materialId).value_labels ?? {}).find(
    (entry): entry is [string, string] => typeof entry[1] === "string",
  )!;

describe("roadDisplayName", () => {
  it.each([
    [{ name: "明治通り", ref: "R305" }, "明治通り[R305]"],
    [{ name: "明治通り" }, "明治通り"],
    [{ ref: "R305" }, "R305"],
  ])("nameとrefの両方があれば1つへ畳み、片方だけでも出す（%o）", (properties, expected) => {
    expect(roadDisplayName(properties)).toBe(expected);
  });
});

describe("roadFactRows", () => {
  it("路面の区分は常に出す（不明も含めて、その道の性質として読めるようにする）", () => {
    const [value, label] = labeledValueOf("surface_class");
    expect(roadFactRows({ surface_class: value })).toEqual([{ label: labelOf("surface_class"), value: label }]);
    expect(roadFactRows({})).toEqual([{ label: labelOf("surface_class"), value: "不明" }]);
  });

  it("該当しない項目は行ごと出さない（「なし」が並ぶと該当する項目が埋もれる）", () => {
    const labels = roadFactRows({ tunnel: true }).map((row) => row.label);
    expect(labels).toEqual([labelOf("surface_class"), labelOf("has_tunnel")]);
  });

  it("値は呼び名で出し、対訳の無い値は生値のまま出す", () => {
    const [value, label] = labeledValueOf("tracktype");
    const rows = roadFactRows({ tracktype: value, smoothness: "未知の値" });
    expect(rows.find((row) => row.label === labelOf("tracktype"))?.value).toBe(label);
    expect(rows.find((row) => row.label === labelOf("smoothness"))?.value).toBe("未知の値");
  });
});
