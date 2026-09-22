import type { Feature, FeatureCollection, LineString } from "geojson";
import type { ExpressionSpecification, FilterSpecification, GeoJSONSource, LayerSpecification } from "maplibre-gl";

import type { MapScene, MapSceneLayer, MapSceneSource } from "./mapScene";

/** [経度, 緯度] の並び（GeoJSON の座標の規約）。 */
export type RoutePoint = readonly [number, number];
export type RoutePath = readonly RoutePoint[];

/**
 * 地物へ載せる値。色分け式・絞り込み・押したときの読み戻しがここから読む。
 * 中身は呼び出し側が決める——何で塗るかは軸カタログが決めるため、ここは運ぶだけ。
 */
export type RouteFeatureProperties = Readonly<Record<string, unknown>>;

export type RouteArrowIcons = {
  /** 進行方向の矢印の絵。周回の向きで絵が変わるため候補ごとに持つ。 */
  readonly iconImage: string; // 仕様に無い: 綴りは呼び出し側が決める
  /** 矢印の下へ敷く縁の絵。主層と同じ位置に、少し大きい絵を置く。 */
  readonly haloIconImage: string; // 仕様に無い: 綴りは呼び出し側が決める
};

export type RouteCandidateShape = {
  /** 押された候補を呼び出し側が見分けるための値。地物のプロパティへそのまま載る。 */
  readonly routeId: string;
  readonly path: RoutePath;
  /** 省略すると矢印を描かない（向きの概念を持たない候補がある）。 */
  readonly arrows?: RouteArrowIcons;
};

/** 座標列と、その地物へ載せる値だけを持つ形。 */
export type RoutePathShape = {
  readonly path: RoutePath;
  readonly properties?: RouteFeatureProperties;
};

export type ComparisonSlotShape = {
  readonly slotId: string;
  readonly path: RoutePath;
  /**
   * 比較表と地図で同じスロットが同じ色に見えるよう、色は呼び出し側が決める
   * （スロットの色は比較表が割り当てる）。
   */
  readonly color: string;
};

export type RouteColoring = {
  /**
   * 区間の色。段の切り方・配色・単位はすべて軸カタログ由来のため、
   * 出来上がった式のまま受け取る（軸ごとの判断をここへ持たない）。
   */
  readonly lineColor: string | ExpressionSpecification;
  /**
   * 凡例で隠した段を落とす絞り込み。色分け線・縁取り・当たり判定の3枚へ同じものを当てる
   * ——縁だけが残る／見えていない区間が押せる、のどちらも地図に無いものが効いている状態に
   * なる。省略は「隠した段が無い」。
   */
  readonly hiddenBandFilter?: FilterSpecification;
};

/**
 * 見た目の値のうち、仕様が性質だけを言っていて具体値を決めていないもの。
 * 呼び出し側が1箇所で決める。
 */
export type RouteSceneStyle = {
  /** 未選択候補の参考線の色。レンズの配色に依存しない。 */
  readonly candidateColor: string;
  readonly candidateWidthPx: number;
  /**
   * 見た目を持たない当たり判定の太さ。細い参考線・帯を指で押せるようにするため、
   * 見た目の線より太くする。
   */
  readonly hitWidthPx: number;
  /** 選択中候補のハロー（薄い縁）。どれを選んでいるかを線の背後から示す。 */
  readonly selectedHaloColor: string;
  readonly selectedHaloWidthPx: number;
  readonly selectedHaloOpacity: number;
  /**
   * 縁取りの色。レンズ配色にも背景にも依存しない一定の暗色にする——線と同系色の面レイヤー
   * （災害・降水・標高図等）が背景に来ても輪郭が残るようにするため。比較スロット・
   * 合成ルートの縁取りも同じ色を使う。
   */
  readonly casingColor: string;
  /** 比較相手と別の道を通る区間の帯。 */
  readonly spliceBandColor: string;
  readonly spliceBandWidthPx: number;
  readonly spliceBandOpacity: number;
  /** 編集中の合成ルートの線。 */
  readonly compositeColor: string;
  readonly compositeWidthPx: number;
  readonly compositeCasingWidthPx: number;
  /** 比較スロットの線。色はスロットごとに違うため、ここは太さだけを決める。 */
  readonly comparisonSlotWidthPx: number;
  readonly comparisonSlotCasingWidthPx: number;
  /** 矢印を置く間隔。絵そのものの大きさは絵の側が持つ。 */
  readonly arrowSpacingPx: number;
};

export type RouteSceneState = {
  /** 地図にルートを出すか。false でもレイヤーは残し、表示だけを落とす。 */
  readonly visible: boolean;
  readonly candidates: readonly RouteCandidateShape[];
  readonly selectedRouteId: string | null;
  /** 選択中候補の区間。空の間は選択中候補も参考線のまま出る。 */
  readonly segments: readonly RoutePathShape[];
  readonly coloring: RouteColoring;
  /** 比較相手と別の道を通る区間。 */
  readonly spliceBands: readonly RoutePathShape[];
  /** 編集中の合成ルート。編集していない間は null。 */
  readonly composite: RoutePathShape | null;
  readonly comparisonSlots: readonly ComparisonSlotShape[];
  readonly style: RouteSceneStyle;
};

export const ROUTE_SOURCE_IDS = {
  candidates: "route-candidates",
  selected: "route-selected",
  segments: "route-segments",
  spliceBands: "route-splice-bands",
  composite: "route-composite",
  comparisonSlots: "route-comparison-slots",
} as const;

/**
 * 押したときに拾う対象の名前。**すべてのルートの当たり判定は `route` も名乗る**
 * ——一般道路網向けのポップアップはルートの上では開かない側なので、
 * 当たり判定を1つ足してもその判定を書き換えずに済む。
 */
export const ROUTE_HIT_TARGET = "route";
export const ROUTE_HIT_TARGET_CANDIDATE = "routeCandidate";
export const ROUTE_HIT_TARGET_SEGMENT = "routeSegment";
export const ROUTE_HIT_TARGET_SPLICE_BAND = "routeSpliceBand";

/**
 * 選択中候補の3枚の太さ。縁取りは色分け線より太く、当たり判定はどちらよりも太い
 * ——押せる幅を見た目の太さから独立させるため、当たり判定は透明な別レイヤーにする。
 */
const DETAIL_CASING_WIDTH_PX = 10;
const DETAIL_LINE_WIDTH_PX = 6;
const DETAIL_HIT_WIDTH_PX = 24;

/** 当たり判定は見えてはいけない。 */
const HIT_OPACITY = 0;
const HIT_COLOR = "#000000";

const ARROW_ICON_PROPERTY = "arrowIcon";
const ARROW_HALO_ICON_PROPERTY = "arrowHaloIcon";
const ROUTE_ID_PROPERTY = "routeId";
const SLOT_COLOR_PROPERTY = "color";
const SLOT_ID_PROPERTY = "slotId";

const ARROW_ICON_EXPRESSION: ExpressionSpecification = ["get", ARROW_ICON_PROPERTY];
const ARROW_HALO_ICON_EXPRESSION: ExpressionSpecification = ["get", ARROW_HALO_ICON_PROPERTY];
const SLOT_COLOR_EXPRESSION: ExpressionSpecification = ["get", SLOT_COLOR_PROPERTY];

type RouteLayerOptions = {
  readonly hitTargets?: readonly string[];
  readonly filter?: FilterSpecification;
};

/** レイヤー1枚ぶんの中身。id は宣言側が役割から決めるため、ここへは渡ってくる。 */
type RouteLayerBody = RouteLayerOptions & { readonly spec: LayerSpecification };

type RouteLayerDeclaration<R extends string = string> = {
  readonly role: R;
  readonly build: (state: RouteSceneState, id: string) => RouteLayerBody;
};

function declareLayer<R extends string>(
  role: R,
  build: (state: RouteSceneState, id: string) => RouteLayerBody,
): RouteLayerDeclaration<R> {
  return { role, build };
}

/**
 * ルートのレイヤー宣言。**1件が「重なりの位置」と「作り方」の両方を持つ**ため、
 * 1枚足すのはこの配列への1件追加で済み、順序だけが別の場所へ残ることがない。
 * 並びは背面から前面。
 *
 * 前後を決めているもの:
 * - ハローは候補の線より背面。前へ出すと薄い暗色が線へかぶり、レンズの配色が濁る。
 * - 比較スロットは候補の参考線より前面、選択中候補の区間より背面。参考線に埋もれると
 *   比較にならず、区間より前へ出るといま見ている候補を隠す。
 * - 選択中候補は「縁取り→色分け線→当たり判定線→矢印ハロー→矢印」の順。
 * - **当たり判定どうしの前後は、重なった場所で押したときにどちらが勝つかを決める**
 *   ——帯の当たり判定は区間の当たり判定より前面に置く。そうしないと、区間の当たり判定が
 *   ルート全体を覆うため帯が一度も押せない。
 */
const ROUTE_LAYERS = [
  declareLayer("selectedHalo", (state, id) =>
    lineBody(id, ROUTE_SOURCE_IDS.selected, {
      "line-color": state.style.selectedHaloColor,
      "line-width": state.style.selectedHaloWidthPx,
      "line-opacity": state.style.selectedHaloOpacity,
    }),
  ),
  declareLayer("candidateLine", (state, id) =>
    lineBody(id, ROUTE_SOURCE_IDS.candidates, {
      "line-color": state.style.candidateColor,
      "line-width": state.style.candidateWidthPx,
    }),
  ),
  declareLayer("candidateHit", (state, id) =>
    lineBody(id, ROUTE_SOURCE_IDS.candidates, hitPaint(state), {
      hitTargets: [ROUTE_HIT_TARGET, ROUTE_HIT_TARGET_CANDIDATE],
    }),
  ),
  declareLayer("comparisonSlotCasing", (state, id) =>
    lineBody(id, ROUTE_SOURCE_IDS.comparisonSlots, {
      "line-color": state.style.casingColor,
      "line-width": state.style.comparisonSlotCasingWidthPx,
    }),
  ),
  declareLayer("comparisonSlotLine", (state, id) =>
    lineBody(id, ROUTE_SOURCE_IDS.comparisonSlots, {
      "line-color": SLOT_COLOR_EXPRESSION,
      "line-width": state.style.comparisonSlotWidthPx,
    }),
  ),
  declareLayer("spliceBandLine", (state, id) =>
    lineBody(id, ROUTE_SOURCE_IDS.spliceBands, {
      "line-color": state.style.spliceBandColor,
      "line-width": state.style.spliceBandWidthPx,
      "line-opacity": state.style.spliceBandOpacity,
    }),
  ),
  declareLayer("compositeCasing", (state, id) =>
    lineBody(id, ROUTE_SOURCE_IDS.composite, {
      "line-color": state.style.casingColor,
      "line-width": state.style.compositeCasingWidthPx,
    }),
  ),
  declareLayer("compositeLine", (state, id) =>
    lineBody(id, ROUTE_SOURCE_IDS.composite, {
      "line-color": state.style.compositeColor,
      "line-width": state.style.compositeWidthPx,
    }),
  ),
  declareLayer("detailCasing", (state, id) =>
    lineBody(
      id,
      ROUTE_SOURCE_IDS.segments,
      {
        "line-color": state.style.casingColor,
        "line-width": DETAIL_CASING_WIDTH_PX,
      },
      { filter: state.coloring.hiddenBandFilter },
    ),
  ),
  declareLayer("detailLine", (state, id) =>
    lineBody(
      id,
      ROUTE_SOURCE_IDS.segments,
      {
        "line-color": state.coloring.lineColor,
        "line-width": DETAIL_LINE_WIDTH_PX,
      },
      { filter: state.coloring.hiddenBandFilter },
    ),
  ),
  declareLayer("detailHit", (state, id) =>
    lineBody(
      id,
      ROUTE_SOURCE_IDS.segments,
      { ...hitPaint(state), "line-width": DETAIL_HIT_WIDTH_PX },
      {
        filter: state.coloring.hiddenBandFilter,
        hitTargets: [ROUTE_HIT_TARGET, ROUTE_HIT_TARGET_SEGMENT],
      },
    ),
  ),
  declareLayer("spliceBandHit", (state, id) =>
    lineBody(id, ROUTE_SOURCE_IDS.spliceBands, hitPaint(state), {
      hitTargets: [ROUTE_HIT_TARGET, ROUTE_HIT_TARGET_SPLICE_BAND],
    }),
  ),
  declareLayer("arrowHalo", (state, id) => arrowBody(id, ARROW_HALO_ICON_EXPRESSION, state)),
  declareLayer("arrow", (state, id) => arrowBody(id, ARROW_ICON_EXPRESSION, state)),
];

export type RouteLayerRole = (typeof ROUTE_LAYERS)[number]["role"];

/** レイヤー id は役割から機械的に導く（役割を1つ足せば id も増える）。 */
export function routeSceneLayerId(role: RouteLayerRole): string {
  return `route-${role}`;
}

/**
 * 画面の状態から、ルートが地図に載っているべき姿を組み立てる。地図には触らない
 * （当てるのは `applyMapScene`）。同じ入力からは同じ scene が出る。
 */
export function buildRouteScene(state: RouteSceneState): MapScene {
  const selected = selectedCandidate(state);
  // 区間を描いている候補は参考線から外す——同じ線を2本重ねると、上の色分け線の下から
  // 単色の線がはみ出す。
  const detailed = state.segments.length > 0 ? selected : undefined;
  const referenceCandidates = state.candidates.filter((candidate) => candidate !== detailed);

  const sources: readonly MapSceneSource[] = [
    lineSource(
      ROUTE_SOURCE_IDS.candidates,
      referenceCandidates.map((candidate) => lineFeature(candidate.path, { [ROUTE_ID_PROPERTY]: candidate.routeId })),
    ),
    lineSource(ROUTE_SOURCE_IDS.selected, selected === undefined ? [] : [selectedFeature(selected)]),
    lineSource(
      ROUTE_SOURCE_IDS.segments,
      state.segments.map((segment) => lineFeature(segment.path, segment.properties)),
    ),
    lineSource(
      ROUTE_SOURCE_IDS.spliceBands,
      state.spliceBands.map((band) => lineFeature(band.path, band.properties)),
    ),
    lineSource(
      ROUTE_SOURCE_IDS.composite,
      state.composite === null ? [] : [lineFeature(state.composite.path, state.composite.properties)],
    ),
    lineSource(
      ROUTE_SOURCE_IDS.comparisonSlots,
      state.comparisonSlots.map((slot) =>
        lineFeature(slot.path, {
          [SLOT_ID_PROPERTY]: slot.slotId,
          [SLOT_COLOR_PROPERTY]: slot.color,
        }),
      ),
    ),
  ];

  return {
    sources,
    layers: ROUTE_LAYERS.map((declaration) => toSceneLayer(declaration, state)),
  };
}

function toSceneLayer(declaration: RouteLayerDeclaration<RouteLayerRole>, state: RouteSceneState): MapSceneLayer {
  const body = declaration.build(state, routeSceneLayerId(declaration.role));
  return {
    spec: body.spec,
    tier: "route",
    visible: state.visible,
    hitTargets: body.hitTargets ?? [],
    ...(body.filter === undefined ? {} : { filter: body.filter }),
  };
}

function selectedCandidate(state: RouteSceneState): RouteCandidateShape | undefined {
  if (state.selectedRouteId === null) return undefined;
  return state.candidates.find((candidate) => candidate.routeId === state.selectedRouteId);
}

function hitPaint(state: RouteSceneState): Record<string, unknown> {
  return {
    "line-color": HIT_COLOR,
    "line-width": state.style.hitWidthPx,
    "line-opacity": HIT_OPACITY,
  };
}

/**
 * `LayerSpecification` は `type` ごとの合併型のため、paint を外から受け取る形では
 * 合併型として組み立て直せない。
 */
function lineBody(
  id: string,
  source: string,
  paint: Record<string, unknown>,
  options: RouteLayerOptions = {},
): RouteLayerBody {
  return {
    spec: {
      id,
      type: "line",
      source,
      layout: { "line-cap": "round", "line-join": "round" },
      paint,
    } as unknown as LayerSpecification,
    ...options,
  };
}

/**
 * 矢印は衝突判定を無効にする——MapLibre は前面のレイヤーから順に置くため、有効にすると
 * 同じ位置にある2層のうち後ろへ回った側が丸ごと落ち、色分け線と同系色のときに矢印が線へ沈む。
 */
function arrowBody(id: string, iconImage: ExpressionSpecification, state: RouteSceneState): RouteLayerBody {
  return {
    spec: {
      id,
      type: "symbol",
      source: ROUTE_SOURCE_IDS.selected,
      layout: {
        "icon-image": iconImage,
        "symbol-placement": "line",
        "symbol-spacing": state.style.arrowSpacingPx,
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
    } as unknown as LayerSpecification,
  };
}

function selectedFeature(candidate: RouteCandidateShape): Feature<LineString> {
  return lineFeature(candidate.path, {
    [ROUTE_ID_PROPERTY]: candidate.routeId,
    // 矢印を持たない候補ではプロパティごと無く、`["get", ...]` が null を返して絵が出ない。
    ...(candidate.arrows === undefined
      ? {}
      : {
          [ARROW_ICON_PROPERTY]: candidate.arrows.iconImage,
          [ARROW_HALO_ICON_PROPERTY]: candidate.arrows.haloIconImage,
        }),
  });
}

function lineFeature(path: RoutePath, properties: RouteFeatureProperties = {}): Feature<LineString> {
  return {
    type: "Feature",
    geometry: {
      type: "LineString",
      coordinates: path.map(([lng, lat]) => [lng, lat]),
    },
    properties: { ...properties },
  };
}

function lineSource(id: string, features: readonly Feature<LineString>[]): MapSceneSource {
  const data: FeatureCollection<LineString> = {
    type: "FeatureCollection",
    features: [...features],
  };
  return {
    id,
    spec: { type: "geojson" },
    content: {
      spec: { data },
      replace: (source) => {
        (source as GeoJSONSource).setData(data);
      },
    },
  };
}
