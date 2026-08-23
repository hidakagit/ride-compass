"use client";

import * as Popover from "@radix-ui/react-popover";
import styles from "./WarningBadge.module.css";

// JMA警報・注意報バッジ（改善計画T205）とWBGT警告（T174）が共有する表示コンポーネント。
// 「地図レイヤーではなく警告バッジ」という表現形式を両タスクで揃えるため、JMA固有の型
// （ActiveWarning）ではなく汎用のitem形にしている。
// levelは4段階。JMA（T205）は3段階（advisory/warning/emergency_warning）のみ使い、
// WBGT（T174、環境省の熱中症予防運動指針）は間の"severe_warning"（厳重警戒）も使う
// （4段階のまま素直に表現し、JMAの3段階へ無理に丸め込まない）。

export type WarningBadgeLevel = "advisory" | "warning" | "severe_warning" | "emergency_warning";

export interface WarningBadgeItem {
  id: string;
  label: string;
  level: WarningBadgeLevel;
  /** 補足（付随事項・取得失敗時のトレードオフの注意書き等）。以前はホバー/長押しの
   * title属性でのみ見せていたが、詳細パネル（下記）が新設されたためそちらへ本文として出す。 */
  title?: string;
}

interface WarningBadgeListProps {
  items: WarningBadgeItem[];
}

const LEVEL_ORDER: readonly WarningBadgeLevel[] = ["advisory", "warning", "severe_warning", "emergency_warning"];

const LEVEL_SUMMARY_LABEL: Record<WarningBadgeLevel, string> = {
  advisory: "注意報",
  warning: "警報",
  severe_warning: "厳重警戒",
  emergency_warning: "特別警報",
};

// 複数件のitemsのうち最も警戒度が高いレベルを1つ返す（LEVEL_ORDERの並び=警戒度の昇順）。
function highestLevel(items: readonly WarningBadgeItem[]): WarningBadgeLevel {
  return items.reduce<WarningBadgeLevel>(
    (highest, item) => (LEVEL_ORDER.indexOf(item.level) > LEVEL_ORDER.indexOf(highest) ? item.level : highest),
    items[0]!.level,
  );
}

// UI改善（2026-08-24、ユーザー指示「メニュー上の天候・警告バッジは一行に収まるように。
// 警告バッジは注意報・警報級があるかどうか分かるボタン配置にとどめ、詳細はボタンを押して
// 中身確認とする」）。以前は警報・注意報・WBGT・河川氾濫予報の全件を常時バッジとして
// 並べており（安全性に関わる情報を折りたたまない設計、2026-08-22実機確認の経緯）、
// 常設の天候ヘッダ（page.tsx: .weatherHeader、本来1行設計、T36）が件数によって
// 2行以上に折り返される問題があった。全件表示という安全側の方針自体は変えず
// （警報の存在に気づけないことを避ける）、表示形式を「最も警戒度が高いレベル+件数の
// サマリーボタン1つを常時1行で表示し、タップで全件の詳細（Radix Popover）を開く」へ
// 変更した。ボタンの文言・色だけで「今の最高警戒度」が常に分かり、内訳は開かないと
// 見えないぶん、常時表示だった頃より一歩踏み込む操作が要るという妥当なトレードオフ。
export default function WarningBadgeList({ items }: WarningBadgeListProps) {
  if (items.length === 0) return null;

  const top = highestLevel(items);
  const summaryLabel = items.length > 1 ? `${LEVEL_SUMMARY_LABEL[top]}${items.length}件` : LEVEL_SUMMARY_LABEL[top];

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          className={`${styles.summaryButton} ${styles[top]}`}
          aria-label={`気象警報・注意報あり: ${summaryLabel}。押すと詳細を表示`}
        >
          {summaryLabel}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className={styles.detailPanel} side="bottom" align="end" sideOffset={6}>
          <div role="list" aria-label="気象警報・注意報の詳細" className={styles.detailList}>
            {items.map((item) => (
              <div key={item.id} role="listitem" className={styles.detailItem}>
                <span className={`${styles.badge} ${styles[item.level]}`}>{item.label}</span>
                {item.title && <p className={styles.detailText}>{item.title}</p>}
              </div>
            ))}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
