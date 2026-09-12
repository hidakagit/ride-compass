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


/** 表示中の候補の区間と、それに対応する相手側の区間の組。 */
export interface PairedStretch {
  displayed: RouteStretch;
  target: RouteStretch;
}

/**
 * 2本が別々の道を通る区間を、表示中の側と相手側で対応づけて返す。
 *
 * 表示中の候補が共有ノードXで分かれてYで戻るなら、相手もXからYまでを別の道で進む——
 * その間の相手のEdgeは定義上どれも表示中の候補に無いため、区間は同じ本数・同じ順で
 * 現れる。本数が食い違ったら対応づけを諦める（片側だけ描くと、地図上の帯と実際に
 * 差し替わる道がずれる）。
 */
export function pairedStretches(
  displayed: readonly string[],
  target: readonly string[],
): PairedStretch[] {
  const onDisplayed = differingStretches(displayed, target);
  const onTarget = differingStretches(target, displayed);
  if (onDisplayed.length !== onTarget.length) return [];
  return onDisplayed.map((stretch, index) => ({ displayed: stretch, target: onTarget[index] }));
}


/** 並び順の判定に使う最小限の候補の形。 */
interface OrderableCandidate {
  overall_difficulty: number | null;
  is_shortest_distance: boolean;
}

/**
 * 合成した候補を、生成候補と同じ並び順の規約へ乗せて差し込む。
 *
 * 規約はbackendが候補一覧を返すときのもの（route_generator.py:
 * `overall_difficulty`昇順［小数1桁］、算出不能は末尾、距離だけで選んだ最短経路だけは
 * 先頭固定）。**合成も素の結果と区別しない**ため、末尾へ足さず同じ位置づけで並べる。
 *
 * backendは合成結果を1件しか返さず他候補を知らないため、差し込む位置はここで決めるしかない
 * ——規約が2箇所にある状態なので、片方を変えたらもう片方も変える。
 * `max_routes`による切り詰めはしない（上限は「生成が何本探すか」の指定で、利用者が
 * 作った組み合わせを押し出す理由が無い）。
 */
export function insertByDifficulty<T extends OrderableCandidate>(routes: readonly T[], spliced: T): T[] {
  const rank = (route: OrderableCandidate) =>
    route.overall_difficulty === null ? Number.POSITIVE_INFINITY : Math.round(route.overall_difficulty * 10) / 10;
  const splicedRank = rank(spliced);
  // 先頭固定の最短経路は難易度順の外にあるため、その後ろから位置を探す
  const pinned = routes.length > 0 && routes[0].is_shortest_distance ? 1 : 0;
  let at = routes.length;
  for (let index = pinned; index < routes.length; index += 1) {
    if (rank(routes[index]) > splicedRank) {
      at = index;
      break;
    }
  }
  return [...routes.slice(0, at), spliced, ...routes.slice(at)];
}
