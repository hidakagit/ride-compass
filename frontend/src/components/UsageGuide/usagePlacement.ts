/** 説明の面の置き方（Radix Popoverの`side`・`sideOffset`・`alignOffset`。寄せ方は`align="start"`に固定）。 */
export interface UsagePlacement {
  side: "bottom" | "top" | "right" | "left";
  /** 部品の辺から面までの間。 */
  sideOffset: number;
  /** 部品の始まり（左端・上端）から面の始まりまでのずれ。 */
  alignOffset: number;
}

interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** 部品から離して置く位置を探す刻み（px）。 */
const STEP_PX = 8;

function positions(limit: number, size: number, padding: number, near: number[]): number[] {
  const max = limit - padding - size;
  const found = new Set<number>();
  for (let at = padding; at <= max; at += STEP_PX) found.add(at);
  for (const at of near) if (at >= padding && at <= max) found.add(at);
  return [...found];
}

/** 2つの箱の間（縦と横の隙間の大きいほう。どちらかの軸でこれだけ離れている）。 */
function gapBetween(a: Box, b: Box): number {
  const dx = Math.max(a.left - (b.left + b.width), b.left - (a.left + a.width), 0);
  const dy = Math.max(a.top - (b.top + b.height), b.top - (a.top + a.height), 0);
  return Math.max(dx, dy);
}

/** 先の値から順に比べ、小さいほうが先。 */
function isBefore(a: readonly number[], b: readonly number[]): boolean {
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] < b[i];
  return false;
}

function overlaps(a: Box, b: Box): boolean {
  return a.left < b.left + b.width && b.left < a.left + a.width && a.top < b.top + b.height && b.top < a.top + a.height;
}

function placementOf(box: Box, anchor: Box): UsagePlacement {
  if (box.top >= anchor.top + anchor.height) {
    return { side: "bottom", sideOffset: box.top - anchor.top - anchor.height, alignOffset: box.left - anchor.left };
  }
  if (box.top + box.height <= anchor.top) {
    return { side: "top", sideOffset: anchor.top - box.top - box.height, alignOffset: box.left - anchor.left };
  }
  if (box.left >= anchor.left + anchor.width) {
    return { side: "right", sideOffset: box.left - anchor.left - anchor.width, alignOffset: box.top - anchor.top };
  }
  return { side: "left", sideOffset: anchor.left - box.left - box.width, alignOffset: box.top - anchor.top };
}

/**
 * 説明の面を、避けるもの（ほかの部品等）にできるだけ重ねない位置へ出す。面が部品に重なると、次の部品を押すつもりで面に当たる。
 * 画面の端から`padding`の内で、部品から`offset`以上離れた位置のうち、重なるものがいちばん少なく、その中で部品に近いもの
 * （同じ近さなら面の中心が部品の中心に近いもの）を選ぶ。部品の隣で覆わずに済めば隣に、済まなければ離して置く。
 * 画面に置ける位置が無ければ既定（下・中央寄せ。Radixが反対側へ返す）。
 */
export function chooseUsagePlacement(
  anchor: Box,
  panel: { width: number; height: number },
  viewport: { width: number; height: number },
  avoid: readonly Box[],
  offset: number,
  padding: number,
): UsagePlacement {
  const centerX = anchor.left + anchor.width / 2;
  const centerY = anchor.top + anchor.height / 2;
  const xs = positions(viewport.width, panel.width, padding, [
    anchor.left,
    centerX - panel.width / 2,
    anchor.left + anchor.width - panel.width,
    anchor.left + anchor.width + offset,
    anchor.left - offset - panel.width,
  ]);
  const ys = positions(viewport.height, panel.height, padding, [
    anchor.top,
    centerY - panel.height / 2,
    anchor.top + anchor.height - panel.height,
    anchor.top + anchor.height + offset,
    anchor.top - offset - panel.height,
  ]);
  let best: { box: Box; score: [number, number, number] } | null = null;
  for (const top of ys) {
    for (const left of xs) {
      const box = { left, top, ...panel };
      const gap = gapBetween(box, anchor);
      // 部品と枠を覆わない（枠は部品の外へ2px出る）。隣に付けた位置の丸めの誤差は許す。
      if (gap < offset - 0.5) continue;
      const covered = avoid.filter((other) => overlaps(box, other)).length;
      const score: [number, number, number] = [
        covered,
        gap,
        Math.hypot(left + panel.width / 2 - centerX, top + panel.height / 2 - centerY),
      ];
      if (best === null || isBefore(score, best.score)) best = { box, score };
    }
  }
  if (best === null) return { side: "bottom", sideOffset: offset, alignOffset: (anchor.width - panel.width) / 2 };
  return placementOf(best.box, anchor);
}
