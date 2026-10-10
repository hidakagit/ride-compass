// @vitest-environment node
/**
 * `features/route/routeSplice.ts`——候補どうしが別の道を通る区間を求め、選んだ道へ乗り換えた経路を組む。
 * - `pairedStretches`: 2本のEdge id列が別の道を通る区間を、両側で起点に近い順に対応づける。本数が食い違えば対応づけない
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

import { buildSplicedShape, pairedStretches, stretchAlternativeGroups } from "./routeSplice";

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
  return { id, shape: shape(names) };
}

function groupsFor(base: string, candidates: ReturnType<typeof candidate>[], minSplitLengthKm = 0.1) {
  return stretchAlternativeGroups(shape(base), candidates, minSplitLengthKm);
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

describe("stretchAlternativeGroups", () => {
  it("元の範囲が重なる乗り換え先は1つの組にまとめ、組の範囲は全部を覆う", () => {
    expect(summary(groupsFor("ABCDE", [candidate("c1", "ABQDE"), candidate("c3", "ABCRE")]))).toEqual([
      { stretch: [1, 4], options: ["c1 [1,3)→[1,3) B-Q Q-D", "c3 [2,4)→[2,4) C-R R-E"] },
    ]);
  });

  it("同じ区間を同じ道へ替える乗り換え先は、候補が違っても先の候補の1つだけ。組は元の経路の起点に近い順で、接するだけの範囲は別の組", () => {
    expect(summary(groupsFor("ABCDE", [candidate("c1", "ABQDE"), candidate("c2", "AUBQDE")]))).toEqual([
      { stretch: [0, 1], options: ["c2 [0,1)→[0,2) A-U U-B"] },
      { stretch: [1, 3], options: ["c1 [1,3)→[1,3) B-Q Q-D"] },
    ]);
  });

  it("相手が途中で元と同じ地点を通るなら、どちらの断片も下限以上のときだけそこで割る", () => {
    // A→U→B→R→Eは、元のA→B→C→D→EとBで触れる。A〜Bは約0.91km、B〜Eは約2.73km。
    expect(summary(groupsFor("ABCDE", [candidate("c", "AUBRE")], 0.9))).toEqual([
      { stretch: [0, 1], options: ["c [0,1)→[0,2) A-U U-B"] },
      { stretch: [1, 4], options: ["c [1,4)→[2,4) B-R R-E"] },
    ]);
    expect(summary(groupsFor("ABCDE", [candidate("c", "AUBRE")], 1))).toEqual([
      { stretch: [0, 4], options: ["c [0,4)→[0,4) A-U U-B B-R R-E"] },
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
});

describe("buildSplicedShape", () => {
  const byId = (candidates: ReturnType<typeof candidate>[]) => (id: string) =>
    candidates.find((c) => c.id === id)?.shape;

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
    const next = stretchAlternativeGroups(afterFirst, [second], 0.1);
    const secondOption = next.flatMap((g) => g.options).find((o) => o.edgeIds.includes("D-S"));
    expect(secondOption?.stretch).toEqual({ start: 4, end: 6 });

    const applied = [groupsFor("ABCDEF", [first])[0].options[0], secondOption!];
    expect(buildSplicedShape(shape("ABCDEF"), applied, shapeOf)).toEqual(shape("ABPQDSF"));
  });
});
