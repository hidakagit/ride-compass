import styles from "./WarningBadge.module.css";

// JMA警報・注意報バッジ（改善計画T205）とWBGT警告（T174、未着手）が共有する表示コンポーネント。
// 「地図レイヤーではなく警告バッジ」という表現形式を両タスクで揃えるため、JMA固有の型
// （ActiveWarning）ではなく汎用のitem形にしている（levelの3段階もJMA固有ではなく
// 「注意報・警報・特別警報級」相当の一般的な警戒度として扱える）。

export type WarningBadgeLevel = "advisory" | "warning" | "emergency_warning";

export interface WarningBadgeItem {
  id: string;
  label: string;
  level: WarningBadgeLevel;
  /** ホバー/長押しで見せる補足（付随事項・取得失敗時のトレードオフの注意書き等）。 */
  title?: string;
}

interface WarningBadgeListProps {
  items: WarningBadgeItem[];
}

// 警報・注意報が無い場合は何も表示しない（改善計画T205完了条件）。取得失敗時も
// 呼び出し元がitemsを空配列にすることで同じ「何も出ない」状態に倒れる
// （安全側ではないトレードオフだが、T174と共有する既定の方針）。
export default function WarningBadgeList({ items }: WarningBadgeListProps) {
  if (items.length === 0) return null;

  return (
    <div className={styles.row} role="list" aria-label="気象警報・注意報">
      {items.map((item) => (
        <span key={item.id} role="listitem" className={`${styles.badge} ${styles[item.level]}`} title={item.title}>
          {item.label}
        </span>
      ))}
    </div>
  );
}
