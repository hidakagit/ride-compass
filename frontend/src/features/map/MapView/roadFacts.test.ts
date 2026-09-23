// @vitest-environment node
// 道をクリックしたときに出す「この道の事実」の組み立て（純関数）。
import { describe, expect, it } from "vitest";
import { roadDisplayName, roadFactRows } from "./roadFacts";

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
    expect(labels).toEqual(["路面", "トンネル"]);
    expect(labels).not.toContain("一方通行");
  });

  it("対訳のある値はラベルへ、無い値は生値のまま出す", () => {
    const rows = roadFactRows({ surface_good: true, smoothness: "未知の値" });
    expect(rows.find((row) => row.label === "路面状態")?.value).toBe("未知の値");
  });
});
