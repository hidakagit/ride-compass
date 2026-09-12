/** 候補ルートの区間の乗り換え（docs/tasks/T621.md）。
 *
 * 2つの候補が別々の道を通る区間を、経路のEdge id列（`RouteCandidate.edge_ids`）の
 * 集合演算で求める。**経路の同一性の判定だけを行い、軸の計算式は持たない**
 * （docs/design-principles.md 構造仕様1）——差し替えた経路の評価はbackendが
 * 既存候補と同じ経路で行う。
 *
 * `segments`は約500m単位へ畳まれておりEdgeの境目と一致しないため、ここでは使えない。
 */

/** 表示中の候補が、比較相手と別の道を通る区間。`edge_ids`における`[start, end)`。 */
export interface RouteStretch {
  start: number;
  end: number;
}

/**
 * `displayed`のうち`target`が通らないEdgeの連続した区間を、起点に近い順に返す。
 *
 * 2本は共有ノードで必ず合流するため、この区間1つを`target`側の道へ差し替えても経路は
 * 成立する。候補はすべて同じ前向き木・後ろ向き木から作られるので、軸に沿った候補どうしなら
 * 区間は1つになる（最短経路だけは別の木から作られるため複数になりうる）。
 */
export function differingStretches(
  displayed: readonly string[],
  target: readonly string[],
): RouteStretch[] {
  const onTarget = new Set(target);
  const stretches: RouteStretch[] = [];
  let start: number | null = null;
  displayed.forEach((edgeId, index) => {
    if (!onTarget.has(edgeId)) {
      if (start === null) start = index;
    } else if (start !== null) {
      stretches.push({ start, end: index });
      start = null;
    }
  });
  if (start !== null) stretches.push({ start, end: displayed.length });
  return stretches;
}

/**
 * `displayed`の`stretch`を`target`側の道へ差し替えたときに通る、`target`のEdge id列。
 *
 * 区間の両端は2本が共有するEdge（または経路の端）なので、そのEdgeを目印に`target`側の
 * 対応する部分を切り出す。
 */
export function targetStretchEdgeIds(
  displayed: readonly string[],
  target: readonly string[],
  stretch: RouteStretch,
): string[] {
  const before = stretch.start > 0 ? displayed[stretch.start - 1] : null;
  const after = stretch.end < displayed.length ? displayed[stretch.end] : null;
  const from = before === null ? 0 : target.indexOf(before) + 1;
  const to = after === null ? target.length : target.indexOf(after);
  if (from <= 0 && before !== null) return [];
  if (to < 0) return [];
  return target.slice(from, Math.max(from, to));
}

/**
 * 選んだ区間を`target`側へ差し替えた経路のEdge id列を組み立てる。
 *
 * 後ろの区間から順に差し替える——先に前を差し替えると、後ろの区間の位置がずれる。
 * 結果はbackendの`spliced_edge_ids`へそのまま渡す（backendがこのグラフで実在・連結・
 * 起点を検証してから評価する）。
 */
export function spliceEdgeIds(
  displayed: readonly string[],
  target: readonly string[],
  selected: readonly RouteStretch[],
): string[] {
  const ordered = [...selected].sort((a, b) => b.start - a.start);
  let path = [...displayed];
  for (const stretch of ordered) {
    path = [
      ...path.slice(0, stretch.start),
      ...targetStretchEdgeIds(displayed, target, stretch),
      ...path.slice(stretch.end),
    ];
  }
  return path;
}

/**
 * `edge_ids`の`[start, end)`が`geometry.coordinates`のどこにあたるかを返す。
 *
 * 隣接Edgeの境界点は重複させずに連結されるため、この対応はbackendが
 * `edge_point_offsets`として返すものだけが持つ（座標列からは復元できない）。
 * 対応が取れないときは`null`——**描かないほうが、ずれた場所へ帯を描くよりよい**。
 */
export function stretchCoordinateRange(
  edgePointOffsets: readonly number[],
  stretch: RouteStretch,
): { start: number; end: number } | null {
  if (stretch.start < 0 || stretch.end >= edgePointOffsets.length) return null;
  const start = edgePointOffsets[stretch.start];
  const end = edgePointOffsets[stretch.end];
  if (start === undefined || end === undefined || end < start) return null;
  return { start, end };
}
