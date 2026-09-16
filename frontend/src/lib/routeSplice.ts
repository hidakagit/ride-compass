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
import { cumulativeDistancesKm } from "@/lib/geoDistance";

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
export function differingStretches(displayed: readonly string[], target: readonly string[]): RouteStretch[] {
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
export function pairedStretches(displayed: readonly string[], target: readonly string[]): PairedStretch[] {
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
  /** Edge iの始点のNode id（末尾に終点を持つ）。backendの`node_ids`。 */
  nodeIds: readonly string[];
}

/** これより短くなる割り方はしない（km）。細かく割るほど選択肢が増え、1区間=1行のUIが縦に伸びる。 */
export const MIN_SPLIT_STRETCH_KM = 0.2;

/** `edgeIndex`のEdgeが始まるNode id。持っていなければundefined。 */
function boundaryNode(shape: RouteGeometryShape, edgeIndex: number): string | undefined {
  return shape.nodeIds[edgeIndex];
}

/**
 * 1つの区間を、**元と相手が同じ地点を通る所**で細かく割る。
 *
 * `differingStretches`はEdge idの一致だけで「同じ道」を判定するため、2本が同じノードで
 * 交差・接触していても、そこで同じEdgeを通っていなければ1本の長い区間になる。交差した
 * ノードは乗り換えられる地点なので、そこで割ると区間ごとに別の候補を選べる。
 *
 * 割る位置は両側ともEdgeの境界に限る（Edgeの途中で差し替えた列はbackendで連結が成立しない）。
 * `minLengthKm`より短い断片は作らない。同じ地点かはbackendが返すNode id（`node_ids`）で
 * 判定する——グラフが持つ同一性をそのまま使う。
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
    const node = boundaryNode(base, index);
    if (node !== undefined) sharedOnBase.set(node, index);
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
    const node = boundaryNode(target, index);
    if (node === undefined) continue;
    const onBase = sharedOnBase.get(node);
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
}

/** 重なり合う代替をまとめた1つの選択単位。グループ内は排他、グループ間は独立。 */
export interface StretchGroup {
  /** グループが覆う元ルート側の範囲（各代替の和）。 */
  stretch: RouteStretch;
  options: StretchAlternative[];
}

/**
 * この乗り換えを当てると、経路が同じ地点を2度通る形（折り返し）になるか。
 *
 * 乗り換えは共有地点でしか起きないため、差し替えた先の道が元の経路の**別の場所**へ触れると、
 * つながってはいるが一度通った地点へ戻る列ができる。backendは連結性しか見ないため
 * （そういう列も走れはするので「経路として成立しない」わけではない）、**選択肢として
 * 出さない側**で止める——この画面で折り返しを選びたい場面が無い。
 *
 * 見るのは差し替えで新しく入る内側のNodeだけ。両端は元と共有する地点で、差し替えで
 * 消える内側のNodeとぶつかっても折り返しにはならない。
 */
function createsRevisit(
  baseNodeIds: readonly string[],
  baseNodeSet: ReadonlySet<string>,
  targetNodeIds: readonly string[],
  stretch: RouteStretch,
  targetStretch: RouteStretch,
): boolean {
  const removed = new Set(baseNodeIds.slice(stretch.start + 1, stretch.end));
  const inserted = new Set<string>();
  for (let index = targetStretch.start + 1; index < targetStretch.end; index += 1) {
    const node = targetNodeIds[index];
    if (node === undefined) continue;
    if (inserted.has(node)) return true;
    if (baseNodeSet.has(node) && !removed.has(node)) return true;
    inserted.add(node);
  }
  return false;
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
  // 折り返しの判定に使う元ルートのNode集合。候補ごとに作り直さない。
  const baseNodeSet = new Set(baseShape?.nodeIds ?? []);
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
      if (
        baseShape &&
        candidate.shape &&
        createsRevisit(baseShape.nodeIds, baseNodeSet, candidate.shape.nodeIds, pair.displayed, pair.target)
      ) {
        continue;
      }
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

  return groups;
}

/** 乗り換えを適用した後の経路の形。次に選べる区間の計算と、地図の描画が同じものを見る。 */
export interface SplicedRouteShape extends RouteGeometryShape {
  edgeIds: string[];
}

/**
 * 元ルートへ、選んだ乗り換えを順に適用した経路の**形**（Edge id列＋座標＋Edge境界）を組む。
 *
 * 次に選べる区間は「いまの組み合わせ」との差として求めるため、合成の途中でも元ルートと同じ
 * 形の材料が要る。backendへ問い合わせずに組めるのは、各候補の座標とEdge境界が手元にあり、
 * 乗り換えが共有地点でしか起きないため——継ぎ目の座標は両者で同じ点になる。
 *
 * `applied`は適用した順に渡す。各要素の範囲は**その時点の形**に対する位置のため、順に
 * 積み上げる（後から前の要素だけを外すことはできない。UIは直前の1手だけ戻せる）。
 */
export function buildSplicedShape(
  base: SplicedRouteShape,
  applied: readonly StretchAlternative[],
  shapeOf: (candidateId: string) => RouteGeometryShape | undefined,
): SplicedRouteShape {
  let current = base;
  for (const alternative of applied) {
    const targetShape = shapeOf(alternative.candidateId);
    if (!targetShape) continue;
    const from = targetShape.edgePointOffsets[alternative.targetStretch.start];
    const to = targetShape.edgePointOffsets[alternative.targetStretch.end];
    const head = current.edgePointOffsets[alternative.stretch.start];
    const tail = current.edgePointOffsets[alternative.stretch.end];
    const edgeIds = [
      ...current.edgeIds.slice(0, alternative.stretch.start),
      ...alternative.edgeIds,
      ...current.edgeIds.slice(alternative.stretch.end),
    ];
    // Node idもEdge idと同じ位置で継ぐ。継ぎ目のNodeは両者で同じ（共有地点でしか
    // 乗り換えないため）なので、相手側は差し替える区間の始点だけを取り、終点は
    // こちら側の続きが持つ。
    const nodeIds = [
      ...current.nodeIds.slice(0, alternative.stretch.start),
      ...targetShape.nodeIds.slice(alternative.targetStretch.start, alternative.targetStretch.end),
      ...current.nodeIds.slice(alternative.stretch.end),
    ];
    // 座標やEdge境界を持たない候補（古い応答・Edge情報だけのエンジン）では、経路の
    // つなぎ替えだけを行う。区間の割り直しはできなくなるが、差し替え自体は成立する。
    if (from === undefined || to === undefined || head === undefined || tail === undefined) {
      current = { ...current, edgeIds, nodeIds };
      continue;
    }
    // 継ぎ目の点は両者で同じ座標のため、後ろ側の先頭を落として重複させない。
    const coordinates = [
      ...current.coordinates.slice(0, head),
      ...targetShape.coordinates.slice(from, to + 1),
      ...current.coordinates.slice(tail + 1),
    ];
    const inserted = to - from;
    const removed = tail - head;
    const shift = inserted - removed;
    const edgePointOffsets = [
      ...current.edgePointOffsets.slice(0, alternative.stretch.start),
      ...targetShape.edgePointOffsets
        .slice(alternative.targetStretch.start, alternative.targetStretch.end)
        .map((offset) => offset - from + head),
      ...current.edgePointOffsets.slice(alternative.stretch.end).map((offset) => offset + shift),
    ];
    current = { edgeIds, coordinates, edgePointOffsets, nodeIds };
  }
  return current;
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
    path = [
      ...path.slice(0, alternative.stretch.start),
      ...alternative.edgeIds,
      ...path.slice(alternative.stretch.end),
    ];
  }
  return path;
}
