/** 候補ルートの区間の乗り換え（docs/tasks/T621.md）。
 *
 * 2つの候補が別々の道を通る区間を、経路のEdge id列（`RouteCandidate.edge_ids`）の
 * 集合演算で求める。**経路の同一性の判定だけを行い、軸の計算式は持たない**
 * （docs/design-principles.md 構造仕様1）——差し替えた経路の評価はbackendが
 * 既存候補と同じ経路で行う。
 *
 * `segments`は約500m単位へ畳まれておりEdgeの境目と一致しないため、ここでは使えない。
 *
 * 区間を細かく割るときだけ座標（`geometry.coordinates`と`edge_point_offsets`）も読む
 * ——2本が交差・接触する地点はEdge idの一致では分からないため（`splitPairedStretch`）。
 */
import { cumulativeDistancesKm, polylineLengthKm } from "@/lib/geoDistance";


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
  is_fastest: boolean;
}

/**
 * 合成した候補を、生成候補と同じ並び順の規約へ乗せて差し込む。
 *
 * 規約はbackendが候補一覧を返すときのもの（route_generator.py:
 * `overall_difficulty`昇順［小数1桁］、算出不能は末尾、基準線（時間最短）だけは
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
  // 先頭固定の基準線は難易度順の外にあるため、その後ろから位置を探す
  const pinned = routes.length > 0 && routes[0].is_fastest ? 1 : 0;
  let at = routes.length;
  for (let index = pinned; index < routes.length; index += 1) {
    if (rank(routes[index]) > splicedRank) {
      at = index;
      break;
    }
  }
  return [...routes.slice(0, at), spliced, ...routes.slice(at)];
}

/** 区間を割るために要る経路の形（`RouteCandidate`の一部。lib側は候補の型に依存しない）。 */
export interface RouteGeometryShape {
  coordinates: readonly GeoJSON.Position[];
  /** Edge iの始点が`coordinates`の何番目か（末尾に終点を持つ）。backendの`edge_point_offsets`。 */
  edgePointOffsets: readonly number[];
}

/** これより短くなる割り方はしない（km）。細かく割るほど選択肢が増え、1区間=1行のUIが縦に伸びる。 */
export const MIN_SPLIT_STRETCH_KM = 0.2;

const pointKey = (point: GeoJSON.Position) => `${point[0]},${point[1]}`;

/** `edgeIndex`のEdgeが始まる座標。境界が無ければundefined。 */
function boundaryPoint(shape: RouteGeometryShape, edgeIndex: number): GeoJSON.Position | undefined {
  const offset = shape.edgePointOffsets[edgeIndex];
  return offset === undefined ? undefined : shape.coordinates[offset];
}

/**
 * 1つの区間を、**元と相手が同じ地点を通る所**で細かく割る。
 *
 * `differingStretches`はEdge idの一致だけで「同じ道」を判定するため、2本が同じノードで
 * 交差・接触していても、そこで同じEdgeを通っていなければ1本の長い区間になる。交差した
 * ノードは乗り換えられる地点なので、そこで割ると区間ごとに別の候補を選べる。
 *
 * 割る位置は両側ともEdgeの境界に限る（Edgeの途中で差し替えた列はbackendで連結が成立しない）。
 * `minLengthKm`より短い断片は作らない。座標はどちらも同じグラフのノード由来のため、
 * 一致は座標の完全一致で判定する。
 */
export function splitPairedStretch(
  base: RouteGeometryShape,
  target: RouteGeometryShape,
  pair: PairedStretch,
  minLengthKm: number,
  baseCumulativeKm: readonly number[],
): PairedStretch[] {
  const sharedOnBase = new Map<string, number>();
  for (let index = pair.displayed.start + 1; index < pair.displayed.end; index += 1) {
    const point = boundaryPoint(base, index);
    if (point) sharedOnBase.set(pointKey(point), index);
  }
  if (sharedOnBase.size === 0) return [pair];

  const kmAt = (edgeIndex: number) => {
    const offset = base.edgePointOffsets[edgeIndex];
    return offset === undefined ? undefined : baseCumulativeKm[offset];
  };
  const startKm = kmAt(pair.displayed.start);
  const endKm = kmAt(pair.displayed.end);
  if (startKm === undefined || endKm === undefined) return [pair];

  const splits: PairedStretch[] = [];
  let lastBase = pair.displayed.start;
  let lastTarget = pair.target.start;
  let lastKm = startKm;
  for (let index = pair.target.start + 1; index < pair.target.end; index += 1) {
    const point = boundaryPoint(target, index);
    if (!point) continue;
    const onBase = sharedOnBase.get(pointKey(point));
    if (onBase === undefined || onBase <= lastBase) continue;
    const splitKm = kmAt(onBase);
    if (splitKm === undefined) continue;
    // 手前の断片と、残り全部の両方が下限を満たすときだけ割る（割った結果に下限未満を作らない）。
    if (splitKm - lastKm < minLengthKm || endKm - splitKm < minLengthKm) continue;
    splits.push({
      displayed: { start: lastBase, end: onBase },
      target: { start: lastTarget, end: index },
    });
    lastBase = onBase;
    lastTarget = index;
    lastKm = splitKm;
  }
  if (splits.length === 0) return [pair];
  splits.push({
    displayed: { start: lastBase, end: pair.displayed.end },
    target: { start: lastTarget, end: pair.target.end },
  });
  return splits;
}

/** ある区間を、どの候補のどの道へ差し替えられるか。 */
export interface StretchAlternative {
  /** 差し替え後の道を持つ候補。 */
  candidateId: string;
  /** 元ルート側の範囲（`edge_ids`の`[start, end)`）。 */
  stretch: RouteStretch;
  /** 相手側の範囲（地図へ相手の道を描くために要る）。 */
  targetStretch: RouteStretch;
  /** 差し替え後に通るEdge id列。 */
  edgeIds: string[];
  /** 差し替え後の道の長さ（km）。複数の候補を継いだ代替は1本の候補の座標からは測れないため、
   * 組み立てた側がここへ入れる。1本の候補で足りる代替は未設定（呼び出し側が座標から測る）。 */
  lengthKm?: number;
}

/** 乗り継ぎで作る代替の、乗り換え回数の上限。1回＝2本の道を継ぐ。
 * 上げるほど選択肢が増え、パネルが読めなくなる。 */
export const MAX_CHAINED_SWITCHES = 2;
/** 1区間あたり、乗り継ぎで足す代替の数の上限。 */
export const MAX_CHAINED_OPTIONS = 4;

/** 候補の道を、共有地点で区切った1本ぶん。 */
interface ChainLink {
  candidateId: string;
  fromKey: string;
  toKey: string;
  edgeIds: string[];
  targetStretch: RouteStretch;
}

/**
 * 1つの区間について、**候補どうしが触れる地点で乗り継いだ道**を組み立てる。
 *
 * 区間の両端（元ルート側の分かれ目と合流点）は決まっているが、その間で候補Bの道から
 * 候補Cの道へ移れる地点があるなら、それも1つの選び方になる。移れるのは2本が同じ地点を
 * 通るところだけで、そこは各候補のEdgeの境界として現れる。
 *
 * 何本でも継げると選択肢が指数的に増えるため、乗り換え回数と件数に上限を置く。
 */
export function chainedAlternatives(
  base: RouteGeometryShape,
  stretch: RouteStretch,
  directOptions: readonly StretchAlternative[],
  shapeOf: (candidateId: string) => RouteGeometryShape | undefined,
): StretchAlternative[] {
  if (directOptions.length < 2) return [];
  const startPoint = boundaryPoint(base, stretch.start);
  const endPoint = boundaryPoint(base, stretch.end);
  if (!startPoint || !endPoint) return [];
  const startKey = pointKey(startPoint);
  const endKey = pointKey(endPoint);

  // 候補ごとに、区間内のEdge境界を「地点キー→そのEdge番号」の並びで持つ。
  const boundaries = new Map<string, { key: string; index: number }[]>();
  for (const option of directOptions) {
    const shape = shapeOf(option.candidateId);
    if (!shape) continue;
    const list: { key: string; index: number }[] = [];
    for (let index = option.targetStretch.start; index <= option.targetStretch.end; index += 1) {
      const point = boundaryPoint(shape, index);
      if (point) list.push({ key: pointKey(point), index });
    }
    boundaries.set(option.candidateId, list);
  }

  // 2本以上が通る地点だけが乗り換えられる場所。端点は常に含める。
  const seenAt = new Map<string, Set<string>>();
  for (const [candidateId, list] of boundaries) {
    for (const { key } of list) {
      if (!seenAt.has(key)) seenAt.set(key, new Set());
      seenAt.get(key)!.add(candidateId);
    }
  }
  const junctions = new Set<string>([startKey, endKey]);
  for (const [key, ids] of seenAt) if (ids.size >= 2) junctions.add(key);
  if (junctions.size <= 2) return [];

  // 乗り換え地点どうしを結ぶ、候補ごとの1本道。
  const links: ChainLink[] = [];
  for (const [candidateId, list] of boundaries) {
    const stops = list.filter((item) => junctions.has(item.key));
    for (const [from, to] of stops.map((item, i) => [item, stops[i + 1]] as const).slice(0, -1)) {
      if (!to || to.index <= from.index) continue;
      const shape = shapeOf(candidateId);
      if (!shape) continue;
      links.push({
        candidateId,
        fromKey: from.key,
        toKey: to.key,
        edgeIds: [],
        targetStretch: { start: from.index, end: to.index },
      });
    }
  }
  if (links.length === 0) return [];

  const byFrom = new Map<string, ChainLink[]>();
  for (const link of links) {
    if (!byFrom.has(link.fromKey)) byFrom.set(link.fromKey, []);
    byFrom.get(link.fromKey)!.push(link);
  }

  const chains: ChainLink[][] = [];
  const walk = (at: string, visited: Set<string>, path: ChainLink[]) => {
    if (chains.length >= MAX_CHAINED_OPTIONS * 4) return;
    if (at === endKey) {
      if (path.length > 1) chains.push([...path]);
      return;
    }
    if (path.length > MAX_CHAINED_SWITCHES + 1) return;
    for (const link of byFrom.get(at) ?? []) {
      if (visited.has(link.toKey)) continue;
      visited.add(link.toKey);
      path.push(link);
      walk(link.toKey, visited, path);
      path.pop();
      visited.delete(link.toKey);
    }
  };
  walk(startKey, new Set([startKey]), []);

  const out: StretchAlternative[] = [];
  const seen = new Set<string>();
  for (const chain of chains) {
    // 1本の候補だけで通れる鎖は、直接の代替と同じものなので出さない。
    if (new Set(chain.map((link) => link.candidateId)).size < 2) continue;
    const edgeIds = chain.flatMap((link) => {
      const option = directOptions.find((item) => item.candidateId === link.candidateId);
      if (!option) return [];
      const offset = option.targetStretch.start;
      return option.edgeIds.slice(link.targetStretch.start - offset, link.targetStretch.end - offset);
    });
    if (edgeIds.length === 0) continue;
    const key = edgeIds.join(",");
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      candidateId: chain.map((link) => link.candidateId).join("+"),
      stretch,
      targetStretch: { start: chain[0].targetStretch.start, end: chain[chain.length - 1].targetStretch.end },
      edgeIds,
      lengthKm: chain.reduce((total, link) => {
        const shape = shapeOf(link.candidateId);
        if (!shape) return total;
        const from = shape.edgePointOffsets[link.targetStretch.start];
        const to = shape.edgePointOffsets[link.targetStretch.end];
        if (from === undefined || to === undefined) return total;
        return total + polylineLengthKm(shape.coordinates.slice(from, to + 1));
      }, 0),
    });
    if (out.length >= MAX_CHAINED_OPTIONS) break;
  }
  return out;
}

/** 重なり合う代替をまとめた1つの選択単位。グループ内は排他、グループ間は独立。 */
export interface StretchGroup {
  /** グループが覆う元ルート側の範囲（各代替の和）。 */
  stretch: RouteStretch;
  options: StretchAlternative[];
}

/**
 * 元ルートの区間ごとに、**全候補の中から**差し替えられる道を集める。
 *
 * 相手を1本選んでから区間を選ぶ形だと、どの相手が良い道を持つのかを総当たりで試すことに
 * なる。区間を主語にして、その区間の代替を候補横断で並べる。
 *
 * 元側の範囲が重なる代替は同じグループへ入れる——重なったまま2つとも差し替えると経路が
 * 壊れるため、グループ内からは1つしか選べない。グループどうしは重ならないので、後ろから
 * 順に差し替えれば互いに影響しない（`spliceEdgeIdsFromAlternatives`）。
 */
export function stretchAlternativeGroups(
  baseEdgeIds: readonly string[],
  candidates: readonly { id: string; edgeIds: readonly string[]; shape?: RouteGeometryShape }[],
  options: { baseShape?: RouteGeometryShape; minSplitLengthKm?: number } = {},
): StretchGroup[] {
  const alternatives: StretchAlternative[] = [];
  const seen = new Set<string>();
  const baseShape = options.baseShape;
  const minSplitLengthKm = options.minSplitLengthKm ?? MIN_SPLIT_STRETCH_KM;
  // 区間を割るために元ルートの累積距離を1回だけ求める（候補ごとに作り直さない）。
  const baseCumulativeKm = baseShape ? cumulativeDistancesKm(baseShape.coordinates) : [];
  for (const candidate of candidates) {
    const pairs = pairedStretches(baseEdgeIds, candidate.edgeIds).flatMap((pair) =>
      baseShape && candidate.shape
        ? splitPairedStretch(baseShape, candidate.shape, pair, minSplitLengthKm, baseCumulativeKm)
        : [pair],
    );
    for (const pair of pairs) {
      // 差し替え後に通るEdgeは相手側の範囲そのもの。共有Edgeを目印に切り出す
      // （`targetStretchEdgeIds`）と、共有**地点**で割った区間では両端に共有Edgeが無く
      // 切り出せない。
      const edgeIds = candidate.edgeIds.slice(pair.target.start, pair.target.end);
      if (edgeIds.length === 0) continue;
      // 同じ区間を同じ道へ差し替える代替は、候補が違っても選択肢としては同じもの。
      const key = `${pair.displayed.start}-${pair.displayed.end}:${edgeIds.join(",")}`;
      if (seen.has(key)) continue;
      seen.add(key);
      alternatives.push({
        candidateId: candidate.id,
        stretch: pair.displayed,
        targetStretch: pair.target,
        edgeIds,
      });
    }
  }

  const groups: StretchGroup[] = [];
  for (const alternative of [...alternatives].sort((a, b) => a.stretch.start - b.stretch.start)) {
    const last = groups.at(-1);
    if (last && alternative.stretch.start < last.stretch.end) {
      last.stretch = { start: last.stretch.start, end: Math.max(last.stretch.end, alternative.stretch.end) };
      last.options.push(alternative);
    } else {
      groups.push({ stretch: { ...alternative.stretch }, options: [alternative] });
    }
  }

  // 候補どうしが触れる地点で乗り継いだ道も選べるようにする（docs/tasks/T843.md）。
  // 継げるのは元側の範囲が同じ代替どうしだけ——範囲が違うものを継ぐと、どこを差し替えて
  // いるのかが決まらない。
  if (baseShape) {
    const shapeOf = (id: string) => candidates.find((candidate) => candidate.id === id)?.shape;
    for (const group of groups) {
      const bySpan = new Map<string, StretchAlternative[]>();
      for (const option of group.options) {
        const key = `${option.stretch.start}-${option.stretch.end}`;
        if (!bySpan.has(key)) bySpan.set(key, []);
        bySpan.get(key)!.push(option);
      }
      for (const sameSpan of bySpan.values()) {
        group.options.push(...chainedAlternatives(baseShape, sameSpan[0].stretch, sameSpan, shapeOf));
      }
    }
  }
  return groups;
}

/**
 * 選んだ代替を差し替えた経路のEdge id列を組み立てる。
 *
 * 後ろの区間から順に差し替える——先に前を差し替えると、後ろの区間の位置がずれる。
 * 渡す代替は互いに重ならないこと（グループから1つずつ選べば満たされる）。
 */
export function spliceEdgeIdsFromAlternatives(
  baseEdgeIds: readonly string[],
  chosen: readonly StretchAlternative[],
): string[] {
  const ordered = [...chosen].sort((a, b) => b.stretch.start - a.stretch.start);
  let path = [...baseEdgeIds];
  for (const alternative of ordered) {
    path = [...path.slice(0, alternative.stretch.start), ...alternative.edgeIds, ...path.slice(alternative.stretch.end)];
  }
  return path;
}
