// @vitest-environment node
import { describe, expect, it } from "vitest";

import { buildSplicedShape, insertByDifficulty, stretchAlternativeGroups, stretchCoordinateRange } from "./routeSplice";

// 区間の切り出しは`stretchAlternativeGroups`の入口からしか使わない。見ているのは
// 「2本の差をどう区間へ割るか」で、途中段階ではなく入口の結果として確かめる。
describe("stretchAlternativeGroups（区間の切り出し）", () => {
  const groupsOf = (base: readonly string[], edgeIds: readonly string[]) =>
    stretchAlternativeGroups(base, [{ id: "c1", edgeIds }], { minSplitLengthKm: 0 });

  it("同じ道だけを通る2本には区間が無い", () => {
    expect(groupsOf(["a", "b", "c"], ["a", "b", "c"])).toEqual([]);
  });

  it("相手が通らないEdgeの連なりを1区間にする", () => {
    const groups = groupsOf(["a", "b", "c"], ["a", "x", "c"]);

    expect(groups).toHaveLength(1);
    expect(groups[0].stretch).toEqual({ start: 1, end: 2 });
    expect(groups[0].options[0].edgeIds).toEqual(["x"]);
  });

  it("合流してまた分かれるときは区間を分ける", () => {
    const groups = groupsOf(["a", "b", "c", "d", "e"], ["a", "p", "c", "q", "e"]);

    expect(groups.map((group) => group.stretch)).toEqual([
      { start: 1, end: 2 },
      { start: 3, end: 4 },
    ]);
  });

  it("末尾まで分かれたままの区間も閉じる", () => {
    const groups = groupsOf(["a", "b", "c"], ["a", "x", "y"]);

    expect(groups).toHaveLength(1);
    expect(groups[0].stretch).toEqual({ start: 1, end: 3 });
    expect(groups[0].options[0].edgeIds).toEqual(["x", "y"]);
  });

  it("先頭から分かれる区間も拾う", () => {
    const groups = groupsOf(["a", "b"], ["x", "b"]);

    expect(groups).toHaveLength(1);
    expect(groups[0].stretch).toEqual({ start: 0, end: 1 });
  });

  it("表示中の区間と相手側の区間を同じ順で対応づける", () => {
    const groups = groupsOf(["a", "b", "c", "d", "e"], ["a", "p", "q", "c", "r", "e"]);

    expect(groups.map((group) => group.options[0].stretch)).toEqual([
      { start: 1, end: 2 },
      { start: 3, end: 4 },
    ]);
    expect(groups.map((group) => group.options[0].targetStretch)).toEqual([
      { start: 1, end: 3 },
      { start: 4, end: 5 },
    ]);
  });

  it("本数が食い違ったら対応づけを諦める（片側だけ描くと、帯と実際に差し替わる道がずれる）", () => {
    expect(groupsOf(["a", "b"], ["a"])).toEqual([]);
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

describe("insertByDifficulty", () => {
  const route = (overall: number | null, fastest = false) => ({
    overall_difficulty: overall,
    is_fastest: fastest,
  });

  it("難易度順の正しい位置へ差し込む", () => {
    const routes = [route(20), route(30), route(40)];

    expect(insertByDifficulty(routes, route(35)).map((r) => r.overall_difficulty)).toEqual([20, 30, 35, 40]);
  });

  it("最も易しければ先頭へ", () => {
    expect(insertByDifficulty([route(20), route(30)], route(10)).map((r) => r.overall_difficulty)).toEqual([
      10, 20, 30,
    ]);
  });

  it("先頭固定の基準線は追い越さない", () => {
    // 基準線は難易度順の外にある。追い越すと基準として読めなくなる
    const routes = [route(50, true), route(20), route(30)];

    expect(insertByDifficulty(routes, route(10)).map((r) => r.overall_difficulty)).toEqual([50, 10, 20, 30]);
  });

  it("算出不能（null）の候補より前に入る", () => {
    expect(insertByDifficulty([route(20), route(null)], route(30)).map((r) => r.overall_difficulty)).toEqual([
      20,
      30,
      null,
    ]);
  });

  it("算出不能な合成結果は末尾へ", () => {
    expect(insertByDifficulty([route(20), route(30)], route(null)).map((r) => r.overall_difficulty)).toEqual([
      20,
      30,
      null,
    ]);
  });

  it("小数1桁で比較する（backendの規約と同じ）", () => {
    // 20.04と20.0は同点扱い。安定な差し込みで既存候補の後ろへ置く
    expect(insertByDifficulty([route(20.0), route(21.0)], route(20.04)).map((r) => r.overall_difficulty)).toEqual([
      20.0, 20.04, 21.0,
    ]);
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
    const groups = stretchAlternativeGroups(
      base,
      [
        { id: "c1", edgeIds: ["s", "b1", "m", "a3", "e"] },
        { id: "c2", edgeIds: ["s", "a1", "a2", "m", "c3", "e"] },
      ],
      { minSplitLengthKm: 0 },
    );

    expect(groups).toHaveLength(2);
    expect(groups[0].stretch).toEqual({ start: 1, end: 3 });
    expect(groups[0].options.map((o) => o.candidateId)).toEqual(["c1"]);
    expect(groups[0].options[0].edgeIds).toEqual(["b1"]);
    expect(groups[1].stretch).toEqual({ start: 4, end: 5 });
    expect(groups[1].options.map((o) => o.candidateId)).toEqual(["c2"]);
  });

  it("同じ区間の別の道は同じグループへ入り、選べる代替として並ぶ", () => {
    const groups = stretchAlternativeGroups(
      base,
      [
        { id: "c1", edgeIds: ["s", "b1", "m", "a3", "e"] },
        { id: "c2", edgeIds: ["s", "x1", "x2", "m", "a3", "e"] },
      ],
      { minSplitLengthKm: 0 },
    );

    expect(groups).toHaveLength(1);
    expect(groups[0].options.map((o) => o.candidateId)).toEqual(["c1", "c2"]);
    expect(groups[0].options.map((o) => o.edgeIds)).toEqual([["b1"], ["x1", "x2"]]);
  });

  it("同じ区間を同じ道へ差し替える代替は1つにまとめる", () => {
    const groups = stretchAlternativeGroups(
      base,
      [
        { id: "c1", edgeIds: ["s", "b1", "m", "a3", "e"] },
        { id: "c2", edgeIds: ["s", "b1", "m", "a3", "e"] },
      ],
      { minSplitLengthKm: 0 },
    );

    expect(groups).toHaveLength(1);
    expect(groups[0].options).toHaveLength(1);
  });

  it("重なる範囲の代替は同じグループへ入れる（両方差し替えると経路が壊れるため）", () => {
    const groups = stretchAlternativeGroups(
      ["s", "a1", "a2", "a3", "e"],
      [
        { id: "c1", edgeIds: ["s", "b1", "a3", "e"] },
        { id: "c2", edgeIds: ["s", "a1", "c1", "e"] },
      ],
      { minSplitLengthKm: 0 },
    );

    expect(groups).toHaveLength(1);
    expect(groups[0].stretch).toEqual({ start: 1, end: 4 });
    expect(groups[0].options).toHaveLength(2);
  });
});

// 2本が同じノードで交差・接触していても、そこで同じEdgeを通っていなければEdge idの一致では
// 分からない。交差した地点は乗り換えられる場所なので、そこで割ると区間ごとに別の候補を選べる
// （docs/records/tasks/T838.md）。
describe("stretchAlternativeGroups（共有地点での割り）", () => {
  // 南北に約1kmごとの直線。元と相手は1.0km地点と2.0km地点で同じ座標を通る。
  const at = (index: number): GeoJSON.Position => [139.7, 35.7 + index * 0.009];
  const detour = (index: number): GeoJSON.Position => [139.705, 35.7 + index * 0.009];
  const base = {
    coordinates: [at(0), at(1), at(2), at(3)],
    edgePointOffsets: [0, 1, 2, 3],
    nodeIds: ["n0", "n1", "n2", "n3"],
  };
  const target = {
    // 途中は別の道（経度が違う）だが、1.0km地点・2.0km地点では元と同じ座標を通る。
    coordinates: [at(0), at(1), detour(1.5), at(2), at(3)],
    edgePointOffsets: [0, 1, 3, 4],
    // 途中は別の道でも、通るNodeは元と同じn0・n1・n2・n3。
    nodeIds: ["n0", "n1", "n2", "n3"],
  };
  const groupsOf = (minSplitLengthKm: number, shape = target) =>
    stretchAlternativeGroups(["e0", "e1", "e2"], [{ id: "c1", edgeIds: ["x0", "x1", "x2"], shape }], {
      baseShape: base,
      minSplitLengthKm,
    });

  it("両方が通る地点で区間を割る", () => {
    expect(groupsOf(0.2).map((group) => group.stretch)).toEqual([
      { start: 0, end: 1 },
      { start: 1, end: 2 },
      { start: 2, end: 3 },
    ]);
  });

  it("下限より短い断片は作らない", () => {
    expect(groupsOf(1.5).map((group) => group.stretch)).toEqual([{ start: 0, end: 3 }]);
  });

  it("同じ地点を通らなければ割らない", () => {
    const apart = {
      coordinates: [at(0), detour(1), detour(2), at(3)],
      edgePointOffsets: [0, 1, 2, 3],
      nodeIds: ["n0", "d1", "d2", "n3"],
    };

    expect(groupsOf(0.2, apart).map((group) => group.stretch)).toEqual([{ start: 0, end: 3 }]);
  });

  it("座標を持たない候補では割らない（グループの作りは従来どおり）", () => {
    const groups = stretchAlternativeGroups(["s", "a1", "a2", "e"], [{ id: "c1", edgeIds: ["s", "b1", "b2", "e"] }], {
      minSplitLengthKm: 0,
    });

    expect(groups).toHaveLength(1);
    expect(groups[0].stretch).toEqual({ start: 1, end: 3 });
  });

  it("割れた区間ごとに別の候補を選べる", () => {
    const groups = stretchAlternativeGroups(
      ["e0", "e1", "e2"],
      [
        { id: "c1", edgeIds: ["x0", "x1", "x2"], shape: target },
        { id: "c2", edgeIds: ["y0", "y1", "y2"], shape: base },
      ],
      { baseShape: base, minSplitLengthKm: 0.2 },
    );

    expect(groups).toHaveLength(3);
    expect(groups[0].options.map((option) => option.candidateId)).toEqual(["c1", "c2"]);
  });
});

describe("stretchAlternativeGroups の折り返し除外", () => {
  const p2 = (lat: number): GeoJSON.Position => [139.7, lat];
  const base = {
    coordinates: [p2(35.7), p2(35.71), p2(35.72), p2(35.73)],
    edgePointOffsets: [0, 1, 2, 3],
    nodeIds: ["n0", "n1", "n2", "n3"],
  };

  it("差し替えた先が元の別の地点へ戻る代替は出さない", () => {
    // 相手はn0→n1の区間を、元が後で通るn2を経由して進む＝当てるとn2を2度通る。
    const foldback = {
      coordinates: [p2(35.7), p2(35.72), p2(35.71)],
      edgePointOffsets: [0, 1, 2],
      nodeIds: ["n0", "n2", "n1"],
    };
    const groups = stretchAlternativeGroups(
      ["e0", "e1", "e2"],
      [{ id: "c1", edgeIds: ["f0", "f1", "e2"], shape: foldback }],
      { baseShape: base, minSplitLengthKm: 0.2 },
    );

    expect(groups).toEqual([]);
  });

  it("元と触れない別の道なら、これまでどおり選択肢になる", () => {
    const apart = {
      coordinates: [p2(35.7), [139.71, 35.705] as GeoJSON.Position, p2(35.72), p2(35.73)],
      edgePointOffsets: [0, 1, 2, 3],
      nodeIds: ["n0", "x1", "n2", "n3"],
    };
    const groups = stretchAlternativeGroups(
      ["e0", "e1", "e2"],
      [{ id: "c1", edgeIds: ["g0", "g1", "e2"], shape: apart }],
      { baseShape: base, minSplitLengthKm: 0.2 },
    );

    expect(groups).toHaveLength(1);
    expect(groups[0].options[0].edgeIds).toEqual(["g0", "g1"]);
  });
});

// 乗り換えた後も「いまの組み合わせ」を元に次の区間を計算するため、合成中のルートの形
// （Edge列＋座標＋Edge境界）をフロントで組む（docs/records/tasks/T843.md）。
describe("buildSplicedShape", () => {
  const p = (lat: number): GeoJSON.Position => [139.7, lat];
  const base = {
    edgeIds: ["e0", "e1", "e2"],
    coordinates: [p(35.7), p(35.71), p(35.72), p(35.73)],
    edgePointOffsets: [0, 1, 2, 3],
    nodeIds: ["n0", "n1", "n2", "n3"],
  };
  // 真ん中のEdgeだけ、2点を経由する別の道へ差し替える候補
  const detour = {
    coordinates: [p(35.7), p(35.71), [139.71, 35.715] as GeoJSON.Position, p(35.72), p(35.73)],
    edgePointOffsets: [0, 1, 2, 3, 4],
    nodeIds: ["n0", "n1", "x1", "n2", "n3"],
  };

  it("差し替えた先の座標とEdge境界をつなぎ直す", () => {
    const shaped = buildSplicedShape(
      base,
      [
        {
          candidateId: "d",
          stretch: { start: 1, end: 2 },
          targetStretch: { start: 1, end: 3 },
          edgeIds: ["d1", "d2"],
        },
      ],
      () => detour,
    );

    expect(shaped.edgeIds).toEqual(["e0", "d1", "d2", "e2"]);
    // 継ぎ目の点は重複させない（元の3点＋差し替えで増えた1点）
    expect(shaped.coordinates).toHaveLength(5);
    expect(shaped.edgePointOffsets).toEqual([0, 1, 2, 3, 4]);
    // 境界の座標が実際に道の分かれ目と合っている
    expect(shaped.coordinates[shaped.edgePointOffsets[1]]).toEqual(p(35.71));
    expect(shaped.coordinates[shaped.edgePointOffsets[3]]).toEqual(p(35.72));
  });

  it("適用を積み重ねられる（2手目は1手目の結果に対する位置で指す）", () => {
    const first = buildSplicedShape(
      base,
      [{ candidateId: "d", stretch: { start: 1, end: 2 }, targetStretch: { start: 1, end: 3 }, edgeIds: ["d1", "d2"] }],
      () => detour,
    );
    const second = buildSplicedShape(
      first,
      [{ candidateId: "d", stretch: { start: 3, end: 4 }, targetStretch: { start: 3, end: 4 }, edgeIds: ["d3"] }],
      () => detour,
    );

    expect(second.edgeIds).toEqual(["e0", "d1", "d2", "d3"]);
    expect(second.edgePointOffsets).toHaveLength(second.edgeIds.length + 1);
  });

  it("座標を持たない候補でも、Edge列は差し替わる（区間の割り直しはできないだけ）", () => {
    const flat = { edgeIds: ["e0", "e1", "e2"], coordinates: [], edgePointOffsets: [], nodeIds: [] };
    const shaped = buildSplicedShape(
      flat,
      [{ candidateId: "d", stretch: { start: 1, end: 2 }, targetStretch: { start: 0, end: 1 }, edgeIds: ["d1"] }],
      () => ({ coordinates: [], edgePointOffsets: [], nodeIds: [] }),
    );

    expect(shaped.edgeIds).toEqual(["e0", "d1", "e2"]);
  });

  it("形を持たない候補は飛ばす（元のまま返る）", () => {
    const shaped = buildSplicedShape(
      base,
      [{ candidateId: "none", stretch: { start: 1, end: 2 }, targetStretch: { start: 0, end: 1 }, edgeIds: ["x"] }],
      () => undefined,
    );

    expect(shaped).toEqual(base);
  });
});
