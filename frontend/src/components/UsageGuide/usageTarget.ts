/** 使い方の文を持たせる印。共有部品は`usage`の値をここへ書き、素の要素は置く箇所でこの属性を直に付ける。 */
const USAGE_ATTRIBUTE = "data-usage";

/** 説明を見る状態の自分の部品（案内・説明の面）に付ける印。ここを押した操作は止めない。 */
export const USAGE_GUIDE_ATTRIBUTE = "data-usage-guide";

/** 説明を見る状態の自分の部品（案内・説明の面）の中か。 */
export function isInUsageGuide(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(`[${USAGE_GUIDE_ATTRIBUTE}]`) !== null;
}

/** 押すと浮きパネルを開く部品の印（`components/ui/Popover/Popover.tsx: PopoverTrigger`が付ける）。 */
export const USAGE_OPENS_ATTRIBUTE = "data-usage-opens";

/** 選ばれていないタブか。Radix のタブは click でなく mousedown で切り替わる。 */
export function isUnselectedTab(element: Element): boolean {
  return element.getAttribute("role") === "tab" && element.getAttribute("aria-selected") === "false";
}

/**
 * 押すと中を展開する、閉じた部品か（`aria-expanded="false"`。浮きパネル・折りたたみ・下部シートのタブ等）か、選ばれていない
 * タブ（押すと中身へ切り替わる）か。浮きパネルのほかの、別の面を開く部品（`aria-haspopup`。消す前の確かめのダイアログ等）は、
 * 開くと画面を塞ぐので除く。
 */
function opensInside(element: Element): boolean {
  if (isUnselectedTab(element)) return true;
  if (element.getAttribute("aria-expanded") !== "false") return false;
  return element.hasAttribute(USAGE_OPENS_ATTRIBUTE) || !element.hasAttribute("aria-haspopup");
}

/** 押して何かが起きる要素。押された要素から最寄りのこれを、説明する部品とみなす。 */
export const USAGE_PART_SELECTOR = [
  "button",
  "a[href]",
  "input",
  "select",
  "textarea",
  "summary",
  "label",
  '[role="button"]',
  '[role="tab"]',
  '[role="radio"]',
  '[role="checkbox"]',
  '[role="switch"]',
  '[role="slider"]',
  '[role="menuitem"]',
  '[role="option"]',
  `[${USAGE_ATTRIBUTE}]`,
].join(",");

export interface UsageTarget {
  element: Element;
  /** 部品の名前（読み上げ名と同じ順で引く）。引けなければnull。 */
  name: string | null;
  /** 部品か、それを囲む部品のうち最も近いものが持つ使い方の文。無ければnull。 */
  usage: string | null;
  /** 押すと中を展開する、閉じた部品か。説明に「中を見る」を出す。 */
  opens: boolean;
}

function textOf(element: Element | null | undefined): string {
  return element?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

function nameOf(element: Element): string | null {
  const label = element.getAttribute("aria-label")?.trim();
  if (label) return label;
  const labelledBy = element.getAttribute("aria-labelledby");
  if (labelledBy) {
    const text = labelledBy
      .split(/\s+/)
      .map((id) => textOf(element.ownerDocument.getElementById(id)))
      .filter(Boolean)
      .join(" ");
    if (text) return text;
  }
  if ("labels" in element && element.labels instanceof NodeList) {
    const text = [...(element.labels as NodeListOf<HTMLLabelElement>)].map(textOf).filter(Boolean).join(" ");
    if (text) return text;
  }
  return textOf(element) || element.getAttribute("title")?.trim() || null;
}

/** 押された要素から、説明する部品を引く。部品の外（地図の余白・本文の文字）ならnull。 */
export function usageTargetOf(pressed: Element): UsageTarget | null {
  let part = pressed.closest(USAGE_PART_SELECTOR);
  if (part === null) return null;
  // ラベルは押すと中の入力が動く。説明するのはその入力。
  if (part instanceof HTMLLabelElement && part.control) part = part.control;
  return {
    element: part,
    name: nameOf(part),
    usage: part.closest(`[${USAGE_ATTRIBUTE}]`)?.getAttribute(USAGE_ATTRIBUTE) ?? null,
    opens: opensInside(part),
  };
}
