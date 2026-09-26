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
  it("nameとrefの両方があれば1つへ畳む", () => {
    expect(roadDisplayName({ name: "明治通り", ref: "R305" })).toBe("明治通り[R305]");
  });

  it("片方だけ持つwayでも出す（名前だけの市道・番号だけの国道）", () => {
    expect(roadDisplayName({ name: "明治通り" })).toBe("明治通り");
    expect(roadDisplayName({ ref: "R305" })).toBe("R305");
  });

  it("どちらも無ければnull（空の見出しを作らない）", () => {
    expect(roadDisplayName({ surface_class: "paved" })).toBeNull();
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
    expect(labels).not.toContain(labelOf("oneway"));
    expect(labels).not.toContain(labelOf("tracktype"));
  });

  it("等級は値の呼び名で出す", () => {
    const [value, label] = labeledValueOf("tracktype");
    expect(roadFactRows({ tracktype: value }).find((row) => row.label === labelOf("tracktype"))?.value).toBe(label);
  });

  it("項目名は材料カタログから引き、対訳の無い値は生値のまま出す", () => {
    const rows = roadFactRows({ smoothness: "未知の値" });
    expect(rows.find((row) => row.label === labelOf("smoothness"))?.value).toBe("未知の値");
  });
});
