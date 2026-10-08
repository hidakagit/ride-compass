/** 地図キャンバスの上に重なるUIで覆われている辺ごとの高さ(px)。 */
export interface RouteFitObscuredPx {
  top?: number;
  bottom?: number;
  left?: number;
  right?: number;
}

type Edge = keyof RouteFitObscuredPx;

export const MAP_OVERLAY_EDGE_ATTRIBUTE = "data-map-overlay-edge";
const TRANSIENT_ATTRIBUTE = "data-map-overlay-transient";

/** 地図の上に重ねる部品へ付ける印。ルートを地図へ収めるとき、この部品が`edge`の辺から覆う幅を余白へ足す。
 * 閉じられる一時の重なり（`transient`）は、地点へ寄せるときだけ避け、ルートを収めるときは数えない——数えると、
 * すぐ閉じる重なりのためにルートがずっと小さく収まる。 */
export function mapOverlayEdge(
  edge: Edge,
  { transient = false }: { transient?: boolean } = {},
): { [MAP_OVERLAY_EDGE_ATTRIBUTE]: Edge; [TRANSIENT_ATTRIBUTE]?: true } {
  return transient
    ? { [MAP_OVERLAY_EDGE_ATTRIBUTE]: edge, [TRANSIENT_ATTRIBUTE]: true }
    : { [MAP_OVERLAY_EDGE_ATTRIBUTE]: edge };
}

/** 印の付いた部品が、地図の各辺から内側へどこまで覆っているか(px)。大きさの無い（隠れている）部品と、
 * `includeTransient`でなければ一時の重なりは数えない。 */
export function measureMapOverlayEdges(
  canvas: DOMRect,
  { includeTransient }: { includeTransient: boolean },
): RouteFitObscuredPx {
  const obscured: RouteFitObscuredPx = {};
  for (const element of document.querySelectorAll(`[${MAP_OVERLAY_EDGE_ATTRIBUTE}]`)) {
    if (!includeTransient && element.hasAttribute(TRANSIENT_ATTRIBUTE)) continue;
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    const depth: Record<Edge, number> = {
      left: rect.right - canvas.left,
      right: canvas.right - rect.left,
      top: rect.bottom - canvas.top,
      bottom: canvas.bottom - rect.top,
    };
    const edge = element.getAttribute(MAP_OVERLAY_EDGE_ATTRIBUTE);
    if (edge !== "left" && edge !== "right" && edge !== "top" && edge !== "bottom") continue;
    obscured[edge] = Math.max(obscured[edge] ?? 0, depth[edge]);
  }
  return obscured;
}
