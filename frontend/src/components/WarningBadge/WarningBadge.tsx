"use client";

import * as Popover from "@radix-ui/react-popover";
import styles from "./WarningBadge.module.css";

// JMA警報・注意報バッジとWBGT警告が共有する表示コンポーネント。
// 「地図レイヤーではなく警告バッジ」という表現形式を揃えるため、JMA固有の型
// （ActiveWarning）ではなく汎用のitem形にしている。
// levelは4段階。JMAは3段階（advisory/warning/emergency_warning）のみ使い、
// WBGT（環境省の熱中症予防運動指針）は間の"severe_warning"（厳重警戒）も使う
// （4段階のまま素直に表現し、JMAの3段階へ無理に丸め込まない）。

export type WarningBadgeLevel = "advisory" | "warning" | "severe_warning" | "emergency_warning";

// バッジの出所。同じlevelキーでも出所ごとに正式な日本語表現が異なる
// （例: level="warning"はJMA/氾濫予報では「警報」だが、WBGT（環境省の熱中症予防運動指針）
// では「警戒」——「警報」は気象庁が発表する公式警報を指す別の意味の言葉のため、
// WBGTの文脈で使うと誤解を招く）。サマリーボタンの表示語を出所別に切り替えるために持つ。
export type WarningBadgeSource = "jma" | "wbgt" | "flood";

export interface WarningBadgeItem {
  id: string;
  label: string;
  level: WarningBadgeLevel;
  source: WarningBadgeSource;
  /** 補足（付随事項・取得失敗時のトレードオフの注意書き等）。詳細パネル（下記）へ
   * 本文として出す。 */
  title?: string;
}

interface WarningBadgeListProps {
  items: WarningBadgeItem[];
}

const LEVEL_ORDER: readonly WarningBadgeLevel[] = ["advisory", "warning", "severe_warning", "emergency_warning"];

// サマリーボタンに出す短い日本語表現。出所ごとの正式な語彙に合わせる
// （JMA: 気象庁の警報・注意報の呼称そのもの。WBGT: domain/wbgt.py:
// _LEVEL_THRESHOLDSの表示名と一致させる。flood: domain/flood_forecast.py:
// LEVEL_SUFFIXESと一致させる。JMAはsevere_warningを発表しないため実際には
// 到達しないが、Record型を満たすため値だけ埋めてある）。
const LEVEL_SUMMARY_LABEL: Record<WarningBadgeSource, Record<WarningBadgeLevel, string>> = {
  jma: { advisory: "注意報", warning: "警報", severe_warning: "厳重警戒", emergency_warning: "特別警報" },
  wbgt: { advisory: "注意", warning: "警戒", severe_warning: "厳重警戒", emergency_warning: "危険" },
  flood: { advisory: "氾濫注意報", warning: "氾濫警報", severe_warning: "氾濫危険警報", emergency_warning: "氾濫特別警報" },
};

// 色もLEVEL_SUMMARY_LABELと同じ理由でsource別に分ける。JMA（気象庁の公式警報）と
// flood（河川管理者の公式氾濫警報、氾濫注意報→氾濫警報→…→氾濫特別警報という同じ4段階の
// 公式警報語彙を持つ）は「公式警報」として同じ配色（.advisory〜.emergency_warning）を
// 共有してよいが、WBGT（環境省の熱中症予防運動指針、気象庁の警報とは無関係の別基準）は
// 見た目からして別物と分かるよう専用の配色（.wbgt_advisory〜.wbgt_emergency_warning、
// 緑→黄→橙→赤の熱中症指数らしい配色でJMA/floodのどの色とも重複しない）を持つ。
function levelColorClassName(item: WarningBadgeItem): string {
  return item.source === "wbgt" ? `wbgt_${item.level}` : item.level;
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
export default function WarningBadgeList({ items }: WarningBadgeListProps) {
  if (items.length === 0) return null;

  const topItem = highestLevelItem(items);
  const topLabel = LEVEL_SUMMARY_LABEL[topItem.source][topItem.level];
  const summaryLabel = items.length > 1 ? `${topLabel}${items.length}件` : topLabel;

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          className={`${styles.summaryButton} ${styles[levelColorClassName(topItem)]}`}
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
                <span className={`${styles.badge} ${styles[levelColorClassName(item)]}`}>{item.label}</span>
                {item.title && <p className={styles.detailText}>{item.title}</p>}
              </div>
            ))}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
