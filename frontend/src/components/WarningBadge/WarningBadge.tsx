"use client";

import type { components } from "@/types/generated/api";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { WarningTriangleIcon } from "@/components/Map/icons";
import { Button } from "@/components/ui/Button/Button";
import { vocabulary } from "@/types/generated/vocabulary";
import { cn } from "@/lib/cn";
import { textVariants } from "@/components/ui/Text/Text";

// JMA警報・注意報バッジとWBGT警告が共有する表示コンポーネント。
// 「地図レイヤーではなく警告バッジ」という表現形式を揃えるため、JMA固有の型
// （ActiveWarning）ではなく汎用のitem形にしている。
// levelは4段階。JMAは3段階（advisory/warning/emergency_warning）のみ使い、
// WBGT（環境省の熱中症予防運動指針）は間の"severe_warning"（厳重警戒）も使う
// （4段階のまま素直に表現し、JMAの3段階へ無理に丸め込まない）。

/** **正本はbackend**（`domain/warning_levels.py`）。契約から引く——写すと、階級が
 * 1つ増えたとき片側だけ知っている状態になる。 */
type WarningBadgeLevel = NonNullable<components["schemas"]["ActiveWarning"]["level"]>;

// バッジの出所。同じ段階でも出所ごとに呼び名が違う（backendの宣言が持つ）。
type WarningBadgeSource = keyof typeof vocabulary.warningBadge;

export interface WarningBadgeItem {
  id: string;
  label: string;
  level: WarningBadgeLevel;
  source: WarningBadgeSource;
  /** 補足（付随事項・取得失敗時のトレードオフの注意書き等）。詳細パネル（下記）へ
   * 本文として出す。 */
  title?: string;
}

/** 取得に失敗した警告の出所。`detail`は失敗の文言（429の案内・`[通信エラー]`等）。 */
export interface WarningFetchFailure {
  id: string;
  label: string;
  detail: string;
}

interface WarningBadgeListProps {
  items: WarningBadgeItem[];
  failures?: readonly WarningFetchFailure[];
}

// 段階の並び（軽い→重い）と、出所ごとの呼び名・色は、backendの宣言（domain/warning_display.py）が配る。
const LEVEL_ORDER: readonly WarningBadgeLevel[] = vocabulary.warningBadge.jma.map((entry) => entry.level);

function levelDisplay(item: WarningBadgeItem): { label: string; color: string } {
  return vocabulary.warningBadge[item.source].find((entry) => entry.level === item.level)!;
}

// 複数件のitemsのうち最も警戒度が高いitemを1つ返す（LEVEL_ORDERの並び=警戒度の昇順）。
// サマリーボタンの語彙は出所（source）によって変わるため、レベルだけでなくitem自体を返す。
function highestLevelItem(items: readonly WarningBadgeItem[]): WarningBadgeItem {
  return items.reduce<WarningBadgeItem>(
    (highest, item) => (LEVEL_ORDER.indexOf(item.level) > LEVEL_ORDER.indexOf(highest.level) ? item : highest),
    items[0]!,
  );
}

// 警告バッジは「最も警戒度が高いレベル+件数のサマリーボタン1つを常時1行で表示し、
// タップで全件の詳細（Radix Popover）を開く」形式にしてある。全件表示という安全側の
// 方針自体は変えず（警報の存在に気づけないことを避ける）、ボタンの文言・色だけで
// 「今の最高警戒度」が常に分かり、内訳は開かないと見えないぶん、常時全件表示より
// 一歩踏み込む操作が要るという妥当なトレードオフ。
export default function WarningBadgeList({ items, failures = [] }: WarningBadgeListProps) {
  return (
    <>
      {items.length > 0 && <WarningSummary items={items} />}
      {failures.length > 0 && <WarningFetchFailureMark failures={failures} />}
    </>
  );
}

// 取得に失敗している間だけ出す印。バッジが0件のときに「警告なし」と読ませないためのもので、
// 成功している間は何も出さない。常時は小さな印だけにし、何が取れていないかはタップで開く。
function WarningFetchFailureMark({ failures }: { failures: readonly WarningFetchFailure[] }) {
  const labels = failures.map((failure) => failure.label).join("・");
  return (
    <Popover>
      <PopoverTrigger asChild>
        {/* 警告の配色（白抜き・塗り）と取り違えないよう、塗らずに枠線と前景色だけで描く。 */}
        <Button
          size="xs"
          shape="pill"
          className="bg-transparent"
          aria-label={`${labels}を取得できていません。押すと詳細を表示`}
        >
          <WarningTriangleIcon size={14} />
          <span>未取得</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        layer="header"
        className="max-h-[60vh] max-w-[min(90vw,20rem)] overflow-y-auto"
        side="bottom"
        align="end"
      >
        <p className={cn(textVariants({ variant: "heading" }), "mb-1 text-[length:var(--font-size-sm)]")}>
          {labels}を取得できていません
        </p>
        <p className={cn(textVariants({ variant: "hint" }), "leading-[1.4]")}>出ていてもバッジは表示されません。</p>
        <ul className="mt-1 mb-0 pl-4">
          {failures.map((failure) => (
            <li key={failure.id} className={cn(textVariants({ variant: "hint" }), "leading-[1.4]")}>
              {failure.label}: {failure.detail}
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

function WarningSummary({ items }: { items: WarningBadgeItem[] }) {
  const topItem = highestLevelItem(items);
  const topLabel = levelDisplay(topItem).label;
  const summaryLabel = items.length > 1 ? `${topLabel}${items.length}件` : topLabel;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          size="xs"
          shape="pill"
          className="border-0 font-bold text-white data-[state=open]:text-white"
          style={{ backgroundColor: levelDisplay(topItem).color }}
          aria-label={`気象警報・注意報あり: ${summaryLabel}。押すと詳細を表示`}
        >
          {summaryLabel}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        layer="header"
        className="max-h-[60vh] max-w-[min(90vw,20rem)] overflow-y-auto"
        side="bottom"
        align="end"
      >
        <div role="list" aria-label="気象警報・注意報の詳細" className="flex flex-col gap-2">
          {items.map((item) => (
            <div key={item.id} role="listitem" className="flex flex-col gap-1">
              <span
                className="inline-flex shrink-0 items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[length:var(--font-size-md)] font-bold text-white"
                style={{ backgroundColor: levelDisplay(item).color }}
              >
                {item.label}
              </span>
              {item.title && <p className={cn(textVariants({ variant: "hint" }), "leading-[1.4]")}>{item.title}</p>}
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
