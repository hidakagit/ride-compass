// @vitest-environment node
// 道をクリックしたときに出す「この道の事実」の組み立て（純関数）。
import { describe, expect, it } from "vitest";
import materialCatalog from "@/types/generated/material-catalog.json";

import { roadDisplayName, roadFactRows } from "./roadFacts";

/** 項目名は材料カタログの名前（テストでも書き写さない）。 */
const labelOf = (materialId: string) => materialCatalog.find((m) => m.material_id === materialId)!.label;

describe("roadDisplayName", () => {
  it("nameとrefの両方があれば1つへ畳む", () => {
    expect(roadDisplayName({ name: "明治通り", ref: "R305" })).toBe("明治通り[R305]");
  });

  it("片方だけ持つwayでも出す（名前だけの市道・番号だけの国道）", () => {
    expect(roadDisplayName({ name: "明治通り" })).toBe("明治通り");
    expect(roadDisplayName({ ref: "R305" })).toBe("R305");
  });

  it("どちらも無ければnull（空の見出しを作らない）", () => {
    expect(roadDisplayName({ surface_good: true })).toBeNull();
  });
});

describe("roadFactRows", () => {
  it("路面は常に出す（不明も含めて、その道の性質として読めるようにする）", () => {
    expect(roadFactRows({ surface_good: true })).toEqual([{ label: "路面", value: "舗装路" }]);
    expect(roadFactRows({ surface_good: false })[0].value).toBe("未舗装路");
    expect(roadFactRows({})[0].value).toBe("不明");
  });

  it("該当しない項目は行ごと出さない（「なし」が並ぶと該当する項目が埋もれる）", () => {
    const labels = roadFactRows({ surface_good: true, tunnel: true }).map((row) => row.label);
    expect(labels).toEqual(["路面", labelOf("has_tunnel")]);
    expect(labels).not.toContain(labelOf("oneway"));
  });

  it("項目名は材料カタログから引き、対訳の無い値は生値のまま出す", () => {
    const rows = roadFactRows({ surface_good: true, smoothness: "未知の値" });
    expect(rows.find((row) => row.label === labelOf("smoothness"))?.value).toBe("未知の値");
  });
});
