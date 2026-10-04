"use client";

import { useCallback, useMemo, useRef, useState, type ComponentProps } from "react";

import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { CLIENT_TUNING_IDS, clientTuningValue } from "@/lib/axisCatalog";
import { buildGenerateRequest, type GenerationInput } from "@/features/route/generationRequest";
import { generateRoutes } from "@/features/route/routeApi";
import {
  buildSplicedShape,
  stretchAlternativeGroups,
  stretchCoordinateRange,
  type StretchAlternative,
} from "@/features/route/routeSplice";
import type RouteSplicePanel from "@/features/route/RouteSplicePanel/RouteSplicePanel";
import type { RouteCandidate } from "@/types/route";

/** 区間の乗り換えの進み方。 */
type SpliceTask = { status: "idle"; error: string | null } | { status: "previewing" } | { status: "applying" };
const SPLICE_IDLE: SpliceTask = { status: "idle", error: null };

/** 失敗の文言だけを消す（処理中なら何もしない）。 */
const withoutError = (task: SpliceTask): SpliceTask => (task.status === "idle" ? SPLICE_IDLE : task);

/** 区間の乗り換えの編集1回ぶん。 */
interface SpliceSession {
  /** 編集を始めたときの候補を作った生成。作り直す・消すと、この編集は効かなくなる（候補のidは作り直しでも
   * 同じ値が振られうるため、idだけでは別の候補を指したまま残る）。 */
  basis: GenerationInput;
  /** 編集の元にした候補。 */
  routeId: string;
  /** 適用した乗り換えを積み上げる。各要素の範囲は「適用した時点の経路」に対する位置のため、
   * 途中だけを外すことはできない（戻せるのは直前の1手）。 */
  applied: StretchAlternative[];
  /** 「差分を見る」で評価した結果。組み合わせをキーに覚え、選び直して戻ったときに投げ直さない
   * （生成APIには回数の上限がある）。 */
  previews: Record<string, RouteCandidate>;
  /** 評価と適用は同時に走らない。失敗は押した場所（編集パネル）に出す。 */
  task: SpliceTask;
}
const NO_ALTERNATIVES: StretchAlternative[] = [];

function spliceFailureMessage(error: unknown): string {
  return error instanceof Error ? error.message : "組み合わせたルートの評価に失敗しました";
}

/** 1グループが持てる選択肢の数。`spliceFeatureIndex`がこの位取りで位置を1つの数へ畳むため、超えると隣の
 *  グループの選択肢として黙って引き戻される。実際には届かないが、届いたとき黙って壊れないよう弾く。 */
const SPLICE_OPTIONS_PER_GROUP = 100;

/** 乗り換え候補の帯のid。グループの位置と選択肢の位置を1つの数にして、地図のタップから
 *  どの選択肢かを引き戻せるようにする。 */
const spliceFeatureIndex = (groupIndex: number, optionIndex: number) => {
  if (optionIndex >= SPLICE_OPTIONS_PER_GROUP) {
    throw new Error(`乗り換えの選択肢が1グループ${SPLICE_OPTIONS_PER_GROUP}件の上限を超えた（index=${optionIndex}）`);
  }
  return groupIndex * SPLICE_OPTIONS_PER_GROUP + optionIndex;
};

interface SpliceSessionInputs {
  /** 候補の一覧（編集の元と乗り換え先はここから引く）。 */
  routes: RouteCandidate[];
  /** 表示中の候補を作った生成の入力。合成した経路も同じ条件で評価する（同じ並びへ入るため、条件が違うと
   * 比べられない値で順位が決まる）。変わると（作り直す・消す）編集は終わる。 */
  generatedInput: GenerationInput | null;
  /** 候補を選んでいるか。 */
  hasSelectedRoute: boolean;
  /** 「作成」を押して評価を始める直前に呼ぶ。 */
  onApplyStart: () => void;
  /** 作った経路と元にした候補。作った経路が既にある候補と同じ道なら、作らずにその候補のidだけを渡す。 */
  onApplied: (result: { created: RouteCandidate; originId: string } | { existingRouteId: string }) => void;
}

/** 地図へ渡す乗り換えの値（`MapView`の同名のprops）。 */
interface SpliceMapProps {
  /** 乗り換え先の帯（相手側の形）。indexは地図のタップから選択肢を引き戻す。 */
  spliceStretches: { index: number; coordinates: GeoJSON.Position[] }[];
  /** いま作っているルート（編集していなければnull）。 */
  splicedRoute: readonly GeoJSON.Position[] | null;
  onSpliceStretchSelect: (index: number) => void;
}

export interface SpliceSessionView {
  /** 編集の元の候補。編集していなければnull。あれば「ルート結果」の同じ場所が編集面になる。 */
  editingRoute: RouteCandidate | null;
  /** 表示中の候補から編集を始められるか（入口を出すか）。 */
  canStart: boolean;
  /** 候補を元に編集を始める（空から始まる）。 */
  start: (routeId: string) => void;
  map: SpliceMapProps;
  /** 編集面（`RouteSplicePanel`）へ渡す値。編集していなければnull。 */
  panel: ComponentProps<typeof RouteSplicePanel> | null;
}

/**
 * 区間の乗り換え（候補の区間を別の候補の道へ差し替えて新しいルートを作る編集）の状態と操作。
 * 乗り換え先はEdge idの集合の演算だけで求め（軸の計算式は持たない）、組み合わせた経路の評価はbackendが行う。
 */
export function useSpliceSession({
  routes,
  generatedInput,
  hasSelectedRoute,
  onApplyStart,
  onApplied,
}: SpliceSessionInputs): SpliceSessionView {
  const axisCatalog = useAxisCatalog();
  // 始めると空から始まり、抜けると中身ごと消える（前回の編集の残りを次へ持ち込まない）。
  const [session, setSplice] = useState<SpliceSession | null>(null);
  const splice = session !== null && session.basis === generatedInput ? session : null;
  const updateSplice = (next: (current: SpliceSession) => SpliceSession) =>
    setSplice((current) => (current === null ? null : next(current)));
  const editingRouteId = splice?.routeId ?? null;
  const appliedAlternatives = splice?.applied ?? NO_ALTERNATIVES;
  const spliceTask = splice?.task ?? SPLICE_IDLE;
  // 「新しいルートを作る」の実行中。stateと違い同じタスク内ですぐ読めるので、連打の2回目をここで止める。
  const applyingRef = useRef(false);
  const setSpliceTask = (task: SpliceTask) => updateSplice((current) => ({ ...current, task }));

  // 編集中の候補は`routes`から引く——候補が入れ替わったときに編集だけが残ると、地図の地点の編集・候補の選択が
  // 黙って効かないままになる。
  const editingRoute = routes.find((route) => route.id === editingRouteId) ?? null;
  // 以下は地図へ渡す値。描画のたびに作り直すと地図の反映があらゆる再描画で走る（候補1本に数千件のEdge id）。
  const candidateShapes = useMemo(
    () =>
      routes.map((route) => ({
        id: route.id,
        edgeIds: route.edge_ids,
        shape: {
          coordinates: route.geometry.coordinates as GeoJSON.Position[],
          edgePointOffsets: route.edge_point_offsets,
          nodeIds: route.node_ids,
        },
      })),
    [routes],
  );
  // いまの組み合わせ（元＋適用した乗り換え）。次に選べる区間も評価へ送るEdge列もこれを見る（乗り換えた先の道の
  // 分かれ道へそのまま進める）。
  const splicedShape = useMemo(() => {
    if (!editingRoute) return null;
    const shapeOf = (candidateId: string) => candidateShapes.find((item) => item.id === candidateId)?.shape;
    return buildSplicedShape(
      {
        edgeIds: editingRoute.edge_ids,
        coordinates: editingRoute.geometry.coordinates as GeoJSON.Position[],
        edgePointOffsets: editingRoute.edge_point_offsets,
        nodeIds: editingRoute.node_ids,
      },
      appliedAlternatives,
      shapeOf,
    );
  }, [editingRoute, appliedAlternatives, candidateShapes]);
  // 区間を割る下限（km）。**引けないときは乗り換えの候補を作らない**——ここで既定を
  // 作ると、較正したのとは別の切り方（下限なし＝共有地点すべてで割る）で黙って動く。
  const minStretchKm = clientTuningValue(axisCatalog, CLIENT_TUNING_IDS.minStretchKm);
  const spliceGroups = useMemo(
    () =>
      splicedShape && minStretchKm !== undefined
        ? stretchAlternativeGroups(
            splicedShape.edgeIds,
            candidateShapes.filter((item) => item.id !== editingRouteId),
            { baseShape: splicedShape, minSplitLengthKm: minStretchKm },
          )
        : [],
    [splicedShape, candidateShapes, editingRouteId, minStretchKm],
  );
  // 地図の帯は相手側の形（適用した道はいまの経路の一部なので出ない）。
  const spliceStretchFeatures = useMemo(
    () =>
      spliceGroups.flatMap((group, groupIndex) =>
        group.options.flatMap((option, optionIndex) => {
          const target = routes.find((route) => route.id === option.candidateId);
          if (!target) return [];
          const range = stretchCoordinateRange(target.edge_point_offsets, option.targetStretch);
          if (!range) return [];
          const coordinates = (target.geometry.coordinates as GeoJSON.Position[]).slice(range.start, range.end + 1);
          if (coordinates.length < 2) return [];
          return [{ index: spliceFeatureIndex(groupIndex, optionIndex), coordinates }];
        }),
      ),
    [spliceGroups, routes],
  );

  // 適用した順で識別する。同じ位置でも積み上げた経緯が違えば別の経路になるため順番を含める。
  const spliceChoiceKey = appliedAlternatives
    .map((item, index) => `${index}:${item.candidateId}:${item.stretch.start}-${item.stretch.end}`)
    .join("|");
  const splicePreview = splice?.previews[spliceChoiceKey] ?? null;
  // 地図の帯をタップしたら、その道へ乗り換える。
  const handleSpliceStretchSelect = useCallback(
    (index: number) => {
      const option =
        spliceGroups[Math.floor(index / SPLICE_OPTIONS_PER_GROUP)]?.options[index % SPLICE_OPTIONS_PER_GROUP];
      if (!option) return;
      setSplice((current) =>
        current === null
          ? null
          : { ...current, applied: [...current.applied, option], task: withoutError(current.task) },
      );
    },
    [spliceGroups],
  );

  // 選んだ組み合わせをbackendで評価する（frontendは経路を組み立てるだけ）。差分の表示と「作る」で同じものを使い、
  // 評価済みなら投げ直さない。
  async function evaluateSplicedRoute(): Promise<RouteCandidate | null> {
    if (!splice || !editingRoute || appliedAlternatives.length === 0 || !splicedShape) return null;
    const cached = splice.previews[spliceChoiceKey];
    if (cached) return cached;
    // 表示中の候補を作った条件（編集を始めたときの生成の入力）で評価する（いまのフォームだと、生成後に重みを
    // 変えた1本だけ別の条件で並ぶ）。
    const { routes: candidates } = await generateRoutes({
      ...buildGenerateRequest(splice.basis),
      spliced_edge_ids: splicedShape.edgeIds,
    });
    const spliced = candidates[0] ?? null;
    if (spliced)
      updateSplice((current) => ({ ...current, previews: { ...current.previews, [spliceChoiceKey]: spliced } }));
    return spliced;
  }

  // 作る前に、この組み合わせで何が変わるかを見る（評価はbackendでしか出せないので、押したときだけ投げる）。
  async function handlePreviewSplice() {
    if (!editingRoute || appliedAlternatives.length === 0 || spliceTask.status === "previewing") return;
    setSpliceTask({ status: "previewing" });
    try {
      const spliced = await evaluateSplicedRoute();
      setSpliceTask(spliced ? SPLICE_IDLE : { status: "idle", error: "組み合わせたルートを評価できませんでした" });
    } catch (error) {
      setSpliceTask({ status: "idle", error: spliceFailureMessage(error) });
    }
  }

  async function handleApplySplice() {
    // 連打で2本入るのを防ぐ（ボタンを押せなくするのは再描画を待つため、その前の2回目は通る）。
    if (applyingRef.current) return;
    // 前提の確認は印を立てる前に済ませる（立ててから抜けると、印が立ったままこの操作が二度と効かなくなる）。
    if (!editingRoute || appliedAlternatives.length === 0) return;
    applyingRef.current = true;
    setSpliceTask({ status: "applying" });
    onApplyStart();
    try {
      const spliced = await evaluateSplicedRoute();
      if (!spliced) {
        setSpliceTask({ status: "idle", error: "組み合わせたルートを評価できませんでした" });
        return;
      }
      // 全部を1つの候補の道へ乗り換えると、既にある候補そのものになる。そのときは並べずにその候補を選ぶ。
      const sameRoute = routes.find((route) => route.edge_ids.join(",") === spliced.edge_ids.join(","));
      onApplied(sameRoute ? { existingRouteId: sameRoute.id } : { created: spliced, originId: editingRoute.id });
      setSplice(null);
    } catch (error) {
      setSpliceTask({ status: "idle", error: spliceFailureMessage(error) });
    } finally {
      applyingRef.current = false;
    }
  }

  return {
    editingRoute,
    // 編集できるのは目的地のルートだけ（周回は乗り換えると起点へ戻れる保証が無い）。表示中の候補を作った生成で見る
    // （いまのピンで見ると、周回へ切り替えた後も編集が出て、評価の要求が目的地無しで弾かれる）。
    // 区間を割る下限を引けない間（軸カタログが取れていない）も出さない。取れていないことはヘッダーの印が知らせる。
    canStart:
      Boolean(generatedInput?.destination) && routes.length > 1 && hasSelectedRoute && minStretchKm !== undefined,
    start: (routeId) => {
      if (generatedInput) setSplice({ basis: generatedInput, routeId, applied: [], previews: {}, task: SPLICE_IDLE });
    },
    map: {
      spliceStretches: spliceStretchFeatures,
      splicedRoute: splicedShape ? splicedShape.coordinates : null,
      onSpliceStretchSelect: handleSpliceStretchSelect,
    },
    panel:
      editingRoute === null
        ? null
        : {
            displayed: editingRoute,
            onCancel: () => setSplice(null),
            appliedCount: appliedAlternatives.length,
            hasAlternatives: spliceStretchFeatures.length > 0,
            onUndo: () =>
              updateSplice((current) => ({
                ...current,
                applied: current.applied.slice(0, -1),
                task: withoutError(current.task),
              })),
            onReset: () => updateSplice((current) => ({ ...current, applied: [], task: withoutError(current.task) })),
            preview: splicePreview,
            previewing: spliceTask.status === "previewing",
            onPreview: handlePreviewSplice,
            onApply: handleApplySplice,
            axes: axisCatalog.axes,
            axisColors: axisCatalog.axisColors,
            error: spliceTask.status === "idle" ? spliceTask.error : null,
            applying: spliceTask.status === "applying",
          },
  };
}
