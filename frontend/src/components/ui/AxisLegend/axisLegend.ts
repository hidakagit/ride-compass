// 軸ごとの寄与を色で示す帯グラフと、その下に折り返して並ぶ軸チップ。「重み配分」の設定と、ルート結果・区間詳細の
// 内訳が同じ形を持つ——同じ軸が画面によって違う形に見えると、設定した軸と結果の軸が同じものだと読み取れない。
// 軸の色は軸idではなくstyleで与える（軸は軸スタジオで増減する）。

export const legendChipsClass = "m-0 flex list-none flex-wrap gap-1 p-0";

/** 軸チップ1つ。行の余りを分け合って伸びる（丸いボタンのままだと行末に押せない余白が残る）。押せない軸は薄くする。 */
export const legendChipClass =
  "inline-flex flex-auto items-stretch overflow-hidden rounded-sm bg-[var(--color-surface-2)] data-[checked=false]:opacity-55";

export const legendChipBodyClass =
  "inline-flex w-full items-center gap-1 whitespace-nowrap px-2 py-1 text-[length:var(--font-size-sm)] text-[var(--foreground)]";

/** 帯グラフ。高さは基準距離に対する倍率（features/route/difficultyLoadBar.ts、styleの--load-bar-height-ratio）。長さが総合難易度を
 * 表すため、高さへ距離を与えると塗られた面積が負荷、色ごとの面積が軸別の負荷になる。 */
export const stackBarClass =
  "flex h-[calc(10px*var(--load-bar-height-ratio,1))] overflow-hidden rounded-[5px] bg-[var(--color-surface-2)]";

export const legendIconClass = "inline-flex flex-shrink-0 items-center";
