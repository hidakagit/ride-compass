// @vitest-environment node
import { describe, expect, it } from "vitest";

import { buildSplicedShape, insertByDifficulty, stretchAlternativeGroups, stretchCoordinateRange } from "./routeSplice";

// 小さな道の網。地点は南北に約1.1km（緯度0.01度）おき、寄り道の地点は東へずらす。
// 経路は地点の並びで書き、Edgeは隣り合う2地点を結ぶ1本（座標は両端の2点）。
const NODE: Record<string, GeoJSON.Position> = {
  A: [139.7, 35.6],
  B: [139.7, 35.61],
  C: [139.7, 35.62],
  D: [139.7, 35.63],
  E: [139.7, 35.64],
  F: [139.7, 35.65],
  X: [139.71, 35.61],
  Y: [139.71, 35.63],
  Z: [139.72, 35.62],
};

/** 地点の並びから、候補の形（Edge id・Node id・座標・Edgeの始点の位置）を作る。 */
function path(nodes: string) {
  const ids = [...nodes];
  const edgeIds = ids.slice(1).map((to, i) => `${ids[i]}${to}`);
  return {
    edgeIds,
    shape: { coordinates: ids.map((id) => NODE[id]), edgePointOffsets: ids.map((_, i) => i), nodeIds: ids },
  };
}

const noSplit = { minSplitLengthKm: Number.POSITIVE_INFINITY };

describe("stretchCoordinateRange（区間が座標列のどこにあたるか）", () => {
  it("区間の始まりと終わりのEdgeの始点の位置", () => {
    expect(stretchCoordinateRange([0, 3, 5, 9], { start: 1, end: 3 })).toEqual({ start: 3, end: 9 });
  });

  it("対応が取れなければnull（ずれた場所へ帯を描かない）", () => {
    expect(stretchCoordinateRange([0, 3, 5, 9], { start: -1, end: 2 })).toBeNull();
    expect(stretchCoordinateRange([0, 3, 5, 9], { start: 1, end: 4 })).toBeNull();
    expect(stretchCoordinateRange([0, 5, 3], { start: 1, end: 2 })).toBeNull();
    expect(stretchCoordinateRange([], { start: 0, end: 0 })).toBeNull();
  });
});

describe("insertByDifficulty（合成した候補を、生成候補と同じ並びへ差し込む）", () => {
  const candidate = (id: string, overall_difficulty: number | null, is_fastest = false) => ({
    id,
    overall_difficulty,
    is_fastest,
  });
  const ids = (routes: { id: string }[]) => routes.map((route) => route.id);

  it("総合難易度の昇順の位置へ入る。比べる値は小数1桁に丸め、同じ値なら後ろへ入る", () => {
    const routes = [candidate("a", 10), candidate("b", 20), candidate("c", 30)];
    expect(ids(insertByDifficulty(routes, candidate("s", 25)))).toEqual(["a", "b", "s", "c"]);
    expect(ids(insertByDifficulty(routes, candidate("s", 20.04)))).toEqual(["a", "b", "s", "c"]);
    expect(ids(insertByDifficulty(routes, candidate("s", 5)))).toEqual(["s", "a", "b", "c"]);
  });

  it("先頭の基準線（時間最短）の前へは入らない", () => {
    const routes = [candidate("fast", 50, true), candidate("a", 10), candidate("b", 20)];
    expect(ids(insertByDifficulty(routes, candidate("s", 1)))).toEqual(["fast", "s", "a", "b"]);
  });

  it("総合難易度が出せない候補は末尾に並ぶ", () => {
    const routes = [candidate("a", 10), candidate("n", null)];
    expect(ids(insertByDifficulty(routes, candidate("s", 99)))).toEqual(["a", "s", "n"]);
    expect(ids(insertByDifficulty(routes, candidate("s", null)))).toEqual(["a", "n", "s"]);
  });

  it("件数で切り詰めず、元の一覧は書き換えない", () => {
    const routes = [candidate("a", 10)];
    expect(insertByDifficulty([], candidate("s", 1))).toHaveLength(1);
    expect(insertByDifficulty(routes, candidate("s", 20))).toHaveLength(2);
    expect(ids(routes)).toEqual(["a"]);
  });
});

describe("stretchAlternativeGroups（区間ごとに、差し替えられる道を全候補から集める）", () => {
  const base = path("ABCDE");

  it("元と別の道を通る区間を、相手側の範囲と差し替え後のEdgeとともに返す", () => {
    const groups = stretchAlternativeGroups(base.edgeIds, [{ id: "t", ...path("ABXDE") }], noSplit);
    expect(groups).toEqual([
      {
        stretch: { start: 1, end: 3 },
        options: [
          {
            candidateId: "t",
            stretch: { start: 1, end: 3 },
            targetStretch: { start: 1, end: 3 },
            edgeIds: ["BX", "XD"],
          },
        ],
      },
    ]);
  });

  it("別の道を通る区間が複数あれば、起点に近い順に1つずつの選択単位になる", () => {
    const groups = stretchAlternativeGroups(path("ABCDEF").edgeIds, [{ id: "t", ...path("AXCDYF") }], noSplit);
    expect(groups.map((group) => group.stretch)).toEqual([
      { start: 0, end: 2 },
      { start: 3, end: 5 },
    ]);
  });

  it("末尾まで分かれたままの区間も1つの区間になる", () => {
    const groups = stretchAlternativeGroups(base.edgeIds, [{ id: "t", ...path("ABCDY") }], noSplit);
    expect(groups.map((group) => group.options.map((option) => option.edgeIds))).toEqual([[["DY"]]]);
    expect(groups[0].stretch).toEqual({ start: 3, end: 4 });
  });

  it("元と同じ道の候補・区間の数が食い違う候補からは、何も出さない", () => {
    expect(stretchAlternativeGroups(base.edgeIds, [{ id: "same", ...path("ABCDE") }], noSplit)).toEqual([]);
    // 元はQQの1か所で分かれるが、相手はBCの前後の2か所で分かれる（Edgeの並びが対応しない）。
    const mismatched = { id: "m", edgeIds: ["AB", "XY", "BC", "ZW", "CD"] };
    expect(stretchAlternativeGroups(["AB", "BC", "QQ", "CD"], [mismatched], noSplit)).toEqual([]);
  });

  it("同じ区間を同じ道へ差し替える代替は、候補が違っても1つにまとめる（先に来た候補を残す）", () => {
    const groups = stretchAlternativeGroups(
      base.edgeIds,
      [
        { id: "t1", ...path("ABXDE") },
        { id: "t2", ...path("ABXDE") },
      ],
      noSplit,
    );
    expect(groups.flatMap((group) => group.options.map((option) => option.candidateId))).toEqual(["t1"]);
  });

  it("元の範囲が重なる代替は同じ選択単位へ入り、選択単位の範囲はそれらの和になる", () => {
    const groups = stretchAlternativeGroups(
      base.edgeIds,
      [
        { id: "t1", ...path("ABXDE") },
        { id: "t2", ...path("ABCYE") },
      ],
      noSplit,
    );
    expect(groups).toHaveLength(1);
    expect(groups[0].stretch).toEqual({ start: 1, end: 4 });
    expect(groups[0].options.map((option) => option.candidateId)).toEqual(["t1", "t2"]);
  });

  describe("形（座標・Node）を持つとき", () => {
    // 元 A→E（真っすぐ）と、相手 A→X→C→Y→E。2本はCで接するが、同じEdgeは通らない。
    const target = { id: "t", ...path("AXCYE") };

    it("2本が同じ地点を通る所で区間を割る。割った両側が下限の距離以上のときだけ", () => {
      const split = stretchAlternativeGroups(base.edgeIds, [target], { baseShape: base.shape, minSplitLengthKm: 1 });
      expect(split.map((group) => group.options.map((option) => option.edgeIds))).toEqual([
        [["AX", "XC"]],
        [["CY", "YE"]],
      ]);

      const tooShort = stretchAlternativeGroups(base.edgeIds, [target], { baseShape: base.shape, minSplitLengthKm: 3 });
      expect(tooShort.map((group) => group.options.map((option) => option.edgeIds))).toEqual([
        [["AX", "XC", "CY", "YE"]],
      ]);
    });

    it("2本が同じ地点を通らなければ割らない", () => {
      const groups = stretchAlternativeGroups(base.edgeIds, [{ id: "t", ...path("ABXDE") }], {
        baseShape: base.shape,
        minSplitLengthKm: 0,
      });
      expect(groups.map((group) => group.options.map((option) => option.edgeIds))).toEqual([[["BX", "XD"]]]);
    });

    it("元か相手の形が無ければ割らない", () => {
      const withoutTargetShape = stretchAlternativeGroups(base.edgeIds, [{ id: "t", edgeIds: target.edgeIds }], {
        baseShape: base.shape,
        minSplitLengthKm: 1,
      });
      const withoutBaseShape = stretchAlternativeGroups(base.edgeIds, [target], { minSplitLengthKm: 1 });
      expect(withoutTargetShape).toHaveLength(1);
      expect(withoutBaseShape).toHaveLength(1);
    });

    it("差し替えても元の別の地点へ触れない代替は出す", () => {
      const groups = stretchAlternativeGroups(base.edgeIds, [{ id: "t", ...path("ABXDE") }], {
        baseShape: base.shape,
        ...noSplit,
      });
      expect(groups).toHaveLength(1);
    });

    it("差し替えると一度通った地点へ戻る形になる代替は出さない", () => {
      // 相手はB→E→Dと進み、元の経路の先（E）へ触れてから戻ってくる。
      const touchesAhead = { id: "touch", ...path("ABEDE") };
      // 相手はB→X→Z→X→Dと、自分の中で同じ地点を2度通る。
      const loopsItself = { id: "loop", ...path("ABXZXDE") };
      for (const candidate of [touchesAhead, loopsItself]) {
        expect(stretchAlternativeGroups(base.edgeIds, [candidate], { baseShape: base.shape, ...noSplit })).toEqual([]);
        // 形が無ければ見分けられず、代替として出る（判定は形があるときだけ）。
        expect(
          stretchAlternativeGroups(base.edgeIds, [{ id: candidate.id, edgeIds: candidate.edgeIds }], noSplit),
        ).not.toEqual([]);
      }
    });
  });
});

describe("buildSplicedShape（選んだ乗り換えを順に当てた経路の形）", () => {
  const base = path("ABCDE");
  const shapes: Record<string, ReturnType<typeof path>["shape"]> = {
    short: path("ABXDE").shape,
    long: path("ABXZYDE").shape,
  };
  const shapeOf = (id: string) => shapes[id];
  const baseShape = { edgeIds: base.edgeIds, ...base.shape };

  /** 形として辻褄が合っているか: 各Edgeの始点の位置の座標が、そのEdgeの始点のNodeの座標。 */
  function expectConsistent(shape: ReturnType<typeof buildSplicedShape>) {
    expect(shape.nodeIds).toHaveLength(shape.edgeIds.length + 1);
    expect(shape.edgePointOffsets).toHaveLength(shape.edgeIds.length + 1);
    shape.nodeIds.forEach((node, i) => expect(shape.coordinates[shape.edgePointOffsets[i]]).toEqual(NODE[node]));
  }

  it("区間を相手の道へ差し替え、継ぎ目の点を重ねずに座標とEdgeの境界をつなぐ", () => {
    const [option] = stretchAlternativeGroups(
      base.edgeIds,
      [{ id: "short", edgeIds: path("ABXDE").edgeIds }],
      noSplit,
    )[0].options;
    const spliced = buildSplicedShape(baseShape, [option], shapeOf);
    expect(spliced.edgeIds).toEqual(["AB", "BX", "XD", "DE"]);
    expect(spliced.nodeIds).toEqual([..."ABXDE"]);
    expect(spliced.coordinates).toEqual([..."ABXDE"].map((id) => NODE[id]));
    expectConsistent(spliced);
  });

  it("差し替えた道のほうが長くても、後ろのEdgeの境界がずれない", () => {
    const [option] = stretchAlternativeGroups(
      base.edgeIds,
      [{ id: "long", edgeIds: path("ABXZYDE").edgeIds }],
      noSplit,
    )[0].options;
    const spliced = buildSplicedShape(baseShape, [option], shapeOf);
    expect(spliced.nodeIds).toEqual([..."ABXZYDE"]);
    expectConsistent(spliced);
  });

  it("乗り換えは順に積み上げる（2手目は1手目を当てた後の形に対する位置）", () => {
    const first = stretchAlternativeGroups(base.edgeIds, [{ id: "short", edgeIds: path("ABXDE").edgeIds }], noSplit)[0]
      .options[0];
    const afterFirst = buildSplicedShape(baseShape, [first], shapeOf);
    const second = stretchAlternativeGroups(
      afterFirst.edgeIds,
      [{ id: "long", edgeIds: path("ABXZYDE").edgeIds }],
      noSplit,
    )[0].options[0];
    const spliced = buildSplicedShape(baseShape, [first, second], shapeOf);
    expect(spliced.nodeIds).toEqual([..."ABXZYDE"]);
    expectConsistent(spliced);
  });

  it("相手の形が引けない乗り換えは飛ばす", () => {
    const option = {
      candidateId: "unknown",
      stretch: { start: 1, end: 3 },
      targetStretch: { start: 1, end: 3 },
      edgeIds: ["BX", "XD"],
    };
    expect(buildSplicedShape(baseShape, [option], shapeOf)).toEqual(baseShape);
  });

  it("Edgeの境界を持たない形では、Edge id とNode id だけをつなぎ替える", () => {
    const option = {
      candidateId: "short",
      stretch: { start: 1, end: 3 },
      targetStretch: { start: 1, end: 3 },
      edgeIds: ["BX", "XD"],
    };
    const noOffsets = { ...baseShape, edgePointOffsets: [] };
    const spliced = buildSplicedShape(noOffsets, [option], shapeOf);
    expect(spliced.edgeIds).toEqual(["AB", "BX", "XD", "DE"]);
    expect(spliced.nodeIds).toEqual([..."ABXDE"]);
    expect(spliced.coordinates).toEqual(baseShape.coordinates);
  });
});
