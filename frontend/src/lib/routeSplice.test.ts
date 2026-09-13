// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  differingStretches,
  insertByDifficulty,
  pairedStretches,
  spliceEdgeIds,
  spliceEdgeIdsFromAlternatives,
  splitPairedStretch,
  stretchAlternativeGroups,
  stretchCoordinateRange,
  targetStretchEdgeIds,
} from "./routeSplice";

describe("differingStretches", () => {
  it("同じ道だけを通る2本には区間が無い", () => {
    expect(differingStretches(["a", "b", "c"], ["a", "b", "c"])).toEqual([]);
  });

  it("相手が通らないEdgeの連なりを1区間にする", () => {
    expect(differingStretches(["a", "b", "c"], ["a", "x", "c"])).toEqual([{ start: 1, end: 2 }]);
  });

  it("合流してまた分かれるときは区間を分ける", () => {
    const displayed = ["a", "b", "c", "d", "e"];
    const target = ["a", "p", "c", "q", "e"];

    expect(differingStretches(displayed, target)).toEqual([
      { start: 1, end: 2 },
      { start: 3, end: 4 },
    ]);
  });

  it("末尾まで分かれたままの区間も閉じる", () => {
    expect(differingStretches(["a", "b", "c"], ["a"])).toEqual([{ start: 1, end: 3 }]);
  });

  it("先頭から分かれる区間も拾う", () => {
    expect(differingStretches(["a", "b"], ["x", "b"])).toEqual([{ start: 0, end: 1 }]);
  });
});

describe("targetStretchEdgeIds", () => {
  it("区間の両端の共有Edgeを目印に相手側を切り出す", () => {
    const displayed = ["a", "b", "c"];
    const target = ["a", "x", "y", "c"];

    expect(targetStretchEdgeIds(displayed, target, { start: 1, end: 2 })).toEqual(["x", "y"]);
  });

  it("先頭から分かれる区間は相手の先頭から切り出す", () => {
    expect(targetStretchEdgeIds(["a", "b"], ["x", "y", "b"], { start: 0, end: 1 })).toEqual(["x", "y"]);
  });

  it("末尾まで分かれる区間は相手の末尾まで切り出す", () => {
    expect(targetStretchEdgeIds(["a", "b"], ["a", "x", "y"], { start: 1, end: 2 })).toEqual(["x", "y"]);
  });
});

describe("spliceEdgeIds", () => {
  it("区間を選ばなければ表示中の経路のまま", () => {
    expect(spliceEdgeIds(["a", "b", "c"], ["a", "x", "c"], [])).toEqual(["a", "b", "c"]);
  });

  it("1区間だけ差し替える", () => {
    expect(spliceEdgeIds(["a", "b", "c"], ["a", "x", "y", "c"], [{ start: 1, end: 2 }])).toEqual([
      "a",
      "x",
      "y",
      "c",
    ]);
  });

  it("複数の区間を差し替えても位置がずれない", () => {
    // 前から差し替えると、後ろの区間の位置がずれて別のEdgeを置き換えてしまう
    const displayed = ["a", "b", "c", "d", "e"];
    const target = ["a", "p", "q", "c", "r", "e"];

    const spliced = spliceEdgeIds(displayed, target, [
      { start: 1, end: 2 },
      { start: 3, end: 4 },
    ]);

    expect(spliced).toEqual(["a", "p", "q", "c", "r", "e"]);
  });

  it("すべての区間を差し替えると相手の経路になる", () => {
    const displayed = ["a", "b", "c", "d", "e"];
    const target = ["a", "p", "c", "q", "e"];

    expect(spliceEdgeIds(displayed, target, differingStretches(displayed, target))).toEqual(target);
  });
});

describe("stretchCoordinateRange", () => {
  it("Edgeの境界点の位置から座標の範囲を出す", () => {
    // Edge 3本、各Edgeが2点で境界を共有 → 座標は4点、境界は[0,1,2,3]
    expect(stretchCoordinateRange([0, 1, 2, 3], { start: 1, end: 2 })).toEqual({ start: 1, end: 2 });
  });

  it("対応が取れないときは描かない", () => {
    // 境界点の件数がEdge数と合っていない（backendとフロントで食い違っている）
    expect(stretchCoordinateRange([0, 1], { start: 1, end: 3 })).toBeNull();
    expect(stretchCoordinateRange([], { start: 0, end: 1 })).toBeNull();
    // 境界点が前後している（backendが返した対応が壊れている）
    expect(stretchCoordinateRange([5, 3], { start: 0, end: 1 })).toBeNull();
  });
});

describe("pairedStretches", () => {
  it("表示中の区間と相手側の区間を同じ順で対応づける", () => {
    const displayed = ["a", "b", "c", "d", "e"];
    const target = ["a", "p", "q", "c", "r", "e"];

    expect(pairedStretches(displayed, target)).toEqual([
      { displayed: { start: 1, end: 2 }, target: { start: 1, end: 3 } },
      { displayed: { start: 3, end: 4 }, target: { start: 4, end: 5 } },
    ]);
  });

  it("同じ道だけを通る2本には組が無い", () => {
    expect(pairedStretches(["a", "b"], ["a", "b"])).toEqual([]);
  });

  it("本数が食い違ったら対応づけを諦める", () => {
    // 片側だけ描くと、地図上の帯と実際に差し替わる道がずれる。
    // 相手が途中で終わる（表示中だけが先へ進む）と、相手側に対応する区間が無い。
    expect(pairedStretches(["a", "b"], ["a"])).toEqual([]);
  });
});

describe("insertByDifficulty", () => {
  const route = (overall: number | null, fastest = false) => ({
    overall_difficulty: overall,
    is_fastest: fastest,
  });

  it("難易度順の正しい位置へ差し込む", () => {
    const routes = [route(20), route(30), route(40)];

    expect(insertByDifficulty(routes, route(35)).map((r) => r.overall_difficulty)).toEqual([
      20, 30, 35, 40,
    ]);
  });

  it("最も易しければ先頭へ", () => {
    expect(
      insertByDifficulty([route(20), route(30)], route(10)).map((r) => r.overall_difficulty),
    ).toEqual([10, 20, 30]);
  });

  it("先頭固定の基準線は追い越さない", () => {
    // 基準線は難易度順の外にある。追い越すと基準として読めなくなる
    const routes = [route(50, true), route(20), route(30)];

    expect(insertByDifficulty(routes, route(10)).map((r) => r.overall_difficulty)).toEqual([
      50, 10, 20, 30,
    ]);
  });

  it("算出不能（null）の候補より前に入る", () => {
    expect(
      insertByDifficulty([route(20), route(null)], route(30)).map((r) => r.overall_difficulty),
    ).toEqual([20, 30, null]);
  });

  it("算出不能な合成結果は末尾へ", () => {
    expect(
      insertByDifficulty([route(20), route(30)], route(null)).map((r) => r.overall_difficulty),
    ).toEqual([20, 30, null]);
  });

  it("小数1桁で比較する（backendの規約と同じ）", () => {
    // 20.04と20.0は同点扱い。安定な差し込みで既存候補の後ろへ置く
    expect(
      insertByDifficulty([route(20.0), route(21.0)], route(20.04)).map((r) => r.overall_difficulty),
    ).toEqual([20.0, 20.04, 21.0]);
  });

  it("候補が1本も無くても差し込める", () => {
    expect(insertByDifficulty([], route(20)).map((r) => r.overall_difficulty)).toEqual([20]);
  });
});

// 区間を主語にして、その区間の代替を候補横断で並べる（相手を1本選んでから区間を選ぶ形だと、
// どの相手が良い道を持つのかを総当たりで試すことになる）。
describe("stretchAlternativeGroups", () => {
  const base = ["s", "a1", "a2", "m", "a3", "e"];

  it("候補ごとの差分を、元の区間ごとにまとめる", () => {
    const groups = stretchAlternativeGroups(base, [
      { id: "c1", edgeIds: ["s", "b1", "m", "a3", "e"] },
      { id: "c2", edgeIds: ["s", "a1", "a2", "m", "c3", "e"] },
    ]);

    expect(groups).toHaveLength(2);
    expect(groups[0].stretch).toEqual({ start: 1, end: 3 });
    expect(groups[0].options.map((o) => o.candidateId)).toEqual(["c1"]);
    expect(groups[0].options[0].edgeIds).toEqual(["b1"]);
    expect(groups[1].stretch).toEqual({ start: 4, end: 5 });
    expect(groups[1].options.map((o) => o.candidateId)).toEqual(["c2"]);
  });

  it("同じ区間の別の道は同じグループへ入り、選べる代替として並ぶ", () => {
    const groups = stretchAlternativeGroups(base, [
      { id: "c1", edgeIds: ["s", "b1", "m", "a3", "e"] },
      { id: "c2", edgeIds: ["s", "x1", "x2", "m", "a3", "e"] },
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].options.map((o) => o.candidateId)).toEqual(["c1", "c2"]);
    expect(groups[0].options.map((o) => o.edgeIds)).toEqual([["b1"], ["x1", "x2"]]);
  });

  it("同じ区間を同じ道へ差し替える代替は1つにまとめる", () => {
    const groups = stretchAlternativeGroups(base, [
      { id: "c1", edgeIds: ["s", "b1", "m", "a3", "e"] },
      { id: "c2", edgeIds: ["s", "b1", "m", "a3", "e"] },
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].options).toHaveLength(1);
  });

  it("重なる範囲の代替は同じグループへ入れる（両方差し替えると経路が壊れるため）", () => {
    const groups = stretchAlternativeGroups(["s", "a1", "a2", "a3", "e"], [
      { id: "c1", edgeIds: ["s", "b1", "a3", "e"] },
      { id: "c2", edgeIds: ["s", "a1", "c1", "e"] },
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].stretch).toEqual({ start: 1, end: 4 });
    expect(groups[0].options).toHaveLength(2);
  });
});

// 2本が同じノードで交差・接触していても、そこで同じEdgeを通っていなければEdge idの一致では
// 分からない。交差した地点は乗り換えられる場所なので、そこで割ると区間ごとに別の候補を選べる
// （docs/tasks/T838.md）。
describe("splitPairedStretch", () => {
  // 南北に約1kmごとの直線。元と相手は1.0km地点と2.0km地点で同じ座標を通る。
  const at = (index: number): GeoJSON.Position => [139.7, 35.7 + index * 0.009];
  const detour = (index: number): GeoJSON.Position => [139.705, 35.7 + index * 0.009];
  const base = {
    coordinates: [at(0), at(1), at(2), at(3)],
    edgePointOffsets: [0, 1, 2, 3],
  };
  const target = {
    // 途中は別の道（経度が違う）だが、1.0km地点・2.0km地点では元と同じ座標を通る。
    coordinates: [at(0), at(1), detour(1.5), at(2), at(3)],
    edgePointOffsets: [0, 1, 3, 4],
  };
  const cumulative = [0, 1, 2, 3];
  const whole = { displayed: { start: 0, end: 3 }, target: { start: 0, end: 3 } };

  it("両方が通る地点で区間を割る", () => {
    const split = splitPairedStretch(base, target, whole, 0.2, cumulative);

    expect(split).toEqual([
      { displayed: { start: 0, end: 1 }, target: { start: 0, end: 1 } },
      { displayed: { start: 1, end: 2 }, target: { start: 1, end: 2 } },
      { displayed: { start: 2, end: 3 }, target: { start: 2, end: 3 } },
    ]);
  });

  it("下限より短い断片は作らない", () => {
    const split = splitPairedStretch(base, target, whole, 1.5, cumulative);

    expect(split).toEqual([whole]);
  });

  it("同じ地点を通らなければ割らない", () => {
    const apart = {
      coordinates: [at(0), detour(1), detour(2), at(3)],
      edgePointOffsets: [0, 1, 2, 3],
    };

    expect(splitPairedStretch(base, apart, whole, 0.2, cumulative)).toEqual([whole]);
  });

  it("座標を持たない候補では割らない（グループの作りは従来どおり）", () => {
    const groups = stretchAlternativeGroups(["s", "a1", "a2", "e"], [
      { id: "c1", edgeIds: ["s", "b1", "b2", "e"] },
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].stretch).toEqual({ start: 1, end: 3 });
  });

  it("割れた区間は別々のグループになり、区間ごとに別の候補を選べる", () => {
    const baseEdgeIds = ["e0", "e1", "e2"];
    const groups = stretchAlternativeGroups(
      baseEdgeIds,
      [
        { id: "c1", edgeIds: ["x0", "x1", "x2"], shape: target },
        { id: "c2", edgeIds: ["y0", "y1", "y2"], shape: { coordinates: base.coordinates, edgePointOffsets: base.edgePointOffsets } },
      ],
      { baseShape: base, minSplitLengthKm: 0.2 },
    );

    expect(groups).toHaveLength(3);
    expect(groups.map((group) => group.stretch)).toEqual([
      { start: 0, end: 1 },
      { start: 1, end: 2 },
      { start: 2, end: 3 },
    ]);
    // 区間ごとに複数の候補から選べる
    expect(groups[0].options.map((option) => option.candidateId)).toEqual(["c1", "c2"]);
  });
});

describe("spliceEdgeIdsFromAlternatives", () => {
  it("選んだ代替を差し替える（後ろから適用するので位置がずれない）", () => {
    const base = ["s", "a1", "m", "a2", "e"];
    const groups = stretchAlternativeGroups(base, [
      { id: "c1", edgeIds: ["s", "b1", "m", "b2", "e"] },
    ]);
    const chosen = groups.map((group) => group.options[0]);

    expect(spliceEdgeIdsFromAlternatives(base, chosen)).toEqual(["s", "b1", "m", "b2", "e"]);
  });

  it("選ばなければ元のまま", () => {
    const base = ["s", "a1", "e"];
    expect(spliceEdgeIdsFromAlternatives(base, [])).toEqual(base);
  });
});
