// @vitest-environment node
/**
 * `features/route/routeSplice.ts`——候補どうしが別の道を通る区間を求め、選んだ道へ乗り換えた経路を組む。
 * - `pairedStretches`: 2本のEdge id列が別の道を通る区間を、両側で起点に近い順に対応づける。本数が食い違えば対応づけない
 * - `stretchCoordinateRange`: Edgeの範囲が座標列のどこにあたるか
 * - `stretchAlternativeGroups`: 元の経路の区間ごとに、全候補から乗り換え先の道を集める。2本が同じ地点を通る所では、
 *   どちらの断片も下限の長さ以上のときだけ区間を割る。一度通った地点へ戻る道は出さず、同じ区間を同じ道へ替える
 *   ものは1つにまとめ、元の範囲が重なるものを同じ組にする
 * - `buildSplicedShape`: 選んだ乗り換えを順に当てた経路の形（Edge id・座標・Edgeの境界・Node id）
 *
 * 経路はbackendの契約どおりの形を`testing/routeFixtures.ts: routeThrough`で地点の並びから組む。
 *
 * ここで見ないもの:
 * - 区間を割る下限を軸カタログから引くこと・乗り換え先を地図の帯にすること・選んだ道を積むこと → `useSpliceSession.test.ts`
 * - 編集で作ったルートの元との差 → `routeEditDiff.test.ts`
 */
import { describe, expect, it } from "vitest";

import { routeThrough, type Places } from "@/testing/routeFixtures";

import { buildSplicedShape, pairedStretches, stretchAlternativeGroups, stretchCoordinateRange } from "./routeSplice";

// 東西に並ぶ元の道（A〜F）と、その北（P〜S）・南（U〜W）の地点。隣どうしは東西に約0.91km。
const PLACES: Places = {
  A: [139.0, 35.0],
  B: [139.01, 35.0],
  C: [139.02, 35.0],
  D: [139.03, 35.0],
  E: [139.04, 35.0],
  F: [139.05, 35.0],
  P: [139.01, 35.01],
  Q: [139.02, 35.01],
  R: [139.03, 35.01],
  S: [139.04, 35.01],
  U: [139.01, 34.99],
  W: [139.03, 34.99],
};

/** 地点の並びから、乗り換えの関数が受け取る形を組む。 */
function shape(names: string) {
  const route = routeThrough(PLACES, [...names]);
  return {
    edgeIds: route.edge_ids,
    coordinates: route.geometry.coordinates,
    edgePointOffsets: route.edge_point_offsets,
    nodeIds: route.node_ids,
  };
}

function candidate(id: string, names: string) {
  const { edgeIds, ...rest } = shape(names);
  return { id, edgeIds, shape: rest };
}

function groupsFor(base: string, candidates: ReturnType<typeof candidate>[], minSplitLengthKm = 0.1) {
  const baseShape = shape(base);
  return stretchAlternativeGroups(baseShape.edgeIds, candidates, { baseShape, minSplitLengthKm });
}

/** 組ごとに「元の範囲 → 候補id:乗り換え先のEdge」を並べる。 */
function summary(groups: ReturnType<typeof stretchAlternativeGroups>) {
  return groups.map((group) => ({
    stretch: [group.stretch.start, group.stretch.end],
    options: group.options.map(
      (o) =>
        `${o.candidateId} [${o.stretch.start},${o.stretch.end})→[${o.targetStretch.start},${o.targetStretch.end}) ${o.edgeIds.join(" ")}`,
    ),
  }));
}

describe("pairedStretches", () => {
  it("同じ道を通る2本には、別の道の区間が無い", () => {
    expect(pairedStretches(["a", "b", "c"], ["a", "b", "c"])).toEqual([]);
  });

  it("別の道を通る区間を、両側の範囲（終わりを含まない）で起点に近い順に対応づける", () => {
    expect(pairedStretches(shape("ABCDEF").edgeIds, shape("AUBCDWF").edgeIds)).toEqual([
      { displayed: { start: 0, end: 1 }, target: { start: 0, end: 2 } },
      { displayed: { start: 3, end: 5 }, target: { start: 4, end: 6 } },
    ]);
  });

  it("両側の区間の本数が食い違えば、対応づけない", () => {
    expect(pairedStretches(["a", "b", "c", "d", "e"], ["a", "c", "x", "e"])).toEqual([]);
  });
});

describe("stretchCoordinateRange", () => {
  it("Edgeの範囲を、その形が座標列で始まる位置と終わる位置にする", () => {
    const { edgePointOffsets } = shape("AUB");
    expect(stretchCoordinateRange(edgePointOffsets, { start: 0, end: 2 })).toEqual({ start: 0, end: 4 });
    expect(stretchCoordinateRange(edgePointOffsets, { start: 1, end: 2 })).toEqual({ start: 2, end: 4 });
  });
});

describe("stretchAlternativeGroups", () => {
  it("元の経路が相手と別の道を通る区間ごとに、相手の道を乗り換え先にする", () => {
    expect(summary(groupsFor("ABCDE", [candidate("c1", "ABQDE")]))).toEqual([
      { stretch: [1, 3], options: ["c1 [1,3)→[1,3) B-Q Q-D"] },
    ]);
  });

  it("元のEdge1本だけを替える区間も、乗り換え先にする", () => {
    expect(summary(groupsFor("ABCDE", [candidate("c", "AUBCDE")]))).toEqual([
      { stretch: [0, 1], options: ["c [0,1)→[0,2) A-U U-B"] },
    ]);
  });

  it("区間は元の経路の起点に近い順に並び、範囲の重ならない区間は別の組になる", () => {
    const late = candidate("late", "ABCDSF");
    const early = candidate("early", "APCDEF");
    expect(summary(groupsFor("ABCDEF", [late, early]))).toEqual([
      { stretch: [0, 2], options: ["early [0,2)→[0,2) A-P P-C"] },
      { stretch: [3, 5], options: ["late [3,5)→[3,5) D-S S-F"] },
    ]);
  });

  it("元の範囲が重なる乗り換え先は1つの組にまとめ、組の範囲は全部を覆う", () => {
    expect(summary(groupsFor("ABCDE", [candidate("c1", "ABQDE"), candidate("c3", "ABCRE")]))).toEqual([
      { stretch: [1, 4], options: ["c1 [1,3)→[1,3) B-Q Q-D", "c3 [2,4)→[2,4) C-R R-E"] },
    ]);
  });

  it("同じ区間を同じ道へ替える乗り換え先は、候補が違っても先の候補の1つだけ", () => {
    expect(summary(groupsFor("ABCDE", [candidate("c1", "ABQDE"), candidate("c2", "AUBQDE")]))).toEqual([
      { stretch: [0, 1], options: ["c2 [0,1)→[0,2) A-U U-B"] },
      { stretch: [1, 3], options: ["c1 [1,3)→[1,3) B-Q Q-D"] },
    ]);
  });

  it("相手が途中で元と同じ地点を通るなら、そこで割って別々の乗り換え先にする", () => {
    // A→P→C→W→Eは、元のA→B→C→D→EとCで触れる。A〜CとC〜Eはどちらも約1.82km。
    expect(summary(groupsFor("ABCDE", [candidate("c", "APCWE")], 1.82))).toEqual([
      { stretch: [0, 2], options: ["c [0,2)→[0,2) A-P P-C"] },
      { stretch: [2, 4], options: ["c [2,4)→[2,4) C-W W-E"] },
    ]);
  });

  it("割った断片のどちらかが下限より短くなるなら割らず、元の区間の中の地点を通る道として出す", () => {
    expect(summary(groupsFor("ABCDE", [candidate("c", "APCWE")], 1.83))).toEqual([
      { stretch: [0, 4], options: ["c [0,4)→[0,4) A-P P-C C-W W-E"] },
    ]);
    // A〜Bは約0.91km、B〜Eは約2.73km。
    expect(summary(groupsFor("ABCDE", [candidate("c", "AUBRE")], 1))).toEqual([
      { stretch: [0, 4], options: ["c [0,4)→[0,4) A-U U-B B-R R-E"] },
    ]);
    expect(summary(groupsFor("ABCDE", [candidate("c", "AUBRE")], 0.9))).toEqual([
      { stretch: [0, 1], options: ["c [0,1)→[0,2) A-U U-B"] },
      { stretch: [1, 4], options: ["c [1,4)→[2,4) B-R R-E"] },
    ]);
  });

  it("元の経路を逆向きにたどって触れる地点では割らない", () => {
    // 相手はDに触れたあとBに触れる。Dでは割れるが、Bは割った後ろの断片の中で元の経路へ戻る地点になる。
    expect(summary(groupsFor("ABCDE", [candidate("c", "APDQBUE")]))).toEqual([
      { stretch: [0, 3], options: ["c [0,3)→[0,2) A-P P-D"] },
    ]);
  });

  it("乗り換えると同じ地点を2度通る道は出さない", () => {
    // 相手の道が自分の中でPを2度通る。
    expect(groupsFor("ABC", [candidate("loop", "APQPC")], 10)).toEqual([]);
    // 相手の道が、替える区間の外にある元の地点Aを通る。
    expect(groupsFor("ABCD", [candidate("back", "ABPAUD")], 10)).toEqual([]);
  });

  it("Edgeを持たない候補からは乗り換え先を作らない", () => {
    const empty = { id: "none", edgeIds: [], shape: { coordinates: [], edgePointOffsets: [], nodeIds: [] } };
    expect(groupsFor("ABCDE", [empty])).toEqual([]);
  });
});

describe("buildSplicedShape", () => {
  const byId = (candidates: ReturnType<typeof candidate>[]) => (id: string) =>
    candidates.find((c) => c.id === id)?.shape;

  it("乗り換えを当てなければ、元の経路の形のまま", () => {
    const base = shape("ABCDE");
    expect(buildSplicedShape(base, [], () => undefined)).toEqual(base);
  });

  it("相手と1か所だけ違う経路でその区間を乗り換えると、相手の経路と同じ形になる", () => {
    const c1 = candidate("c1", "ABPQDE");
    const [group] = groupsFor("ABCDE", [c1]);
    expect(buildSplicedShape(shape("ABCDE"), [group.options[0]], byId([c1]))).toEqual(shape("ABPQDE"));
  });

  it("相手の形が引けない乗り換えは当てずに飛ばす", () => {
    const [group] = groupsFor("ABCDE", [candidate("c1", "ABPQDE")]);
    expect(buildSplicedShape(shape("ABCDE"), [group.options[0]], () => undefined)).toEqual(shape("ABCDE"));
  });

  it("乗り換えた後の形から求めた次の乗り換えを順に当てると、両方を通る経路になる", () => {
    const first = candidate("first", "ABPQDEF");
    const second = candidate("second", "ABCDSF");
    const shapeOf = byId([first, second]);
    const afterFirst = buildSplicedShape(shape("ABCDEF"), [groupsFor("ABCDEF", [first])[0].options[0]], shapeOf);
    expect(afterFirst).toEqual(shape("ABPQDEF"));

    // 1つ目でEdgeが1本増えたので、2つ目の範囲は乗り換えた後の形に対する位置で求める。
    const next = stretchAlternativeGroups(afterFirst.edgeIds, [second], {
      baseShape: afterFirst,
      minSplitLengthKm: 0.1,
    });
    const secondOption = next.flatMap((g) => g.options).find((o) => o.edgeIds.includes("D-S"));
    expect(secondOption?.stretch).toEqual({ start: 4, end: 6 });

    const applied = [groupsFor("ABCDEF", [first])[0].options[0], secondOption!];
    expect(buildSplicedShape(shape("ABCDEF"), applied, shapeOf)).toEqual(shape("ABPQDSF"));
  });
});
