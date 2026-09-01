"use client";

import * as Popover from "@radix-ui/react-popover";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { setResearchEnabled } from "@/lib/researchMode";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { Button } from "@/components/ui/Button/Button";
import { LogIcon, MenuIcon } from "@/components/Map/icons";
import styles from "./HeaderMenu.module.css";

interface HeaderMenuProps {
  /** デバッグログ項目自体の表示可否（デバッグモードのON/OFFは/adminで切り替える、
   * 既存の`debugEnabled`条件をそのまま引き継ぐ）。 */
  debugEnabled: boolean;
  debugConsoleOpen: boolean;
  onToggleDebugConsole: () => void;
}

// 改善計画T519: ヘッダーの個別ボタンをこれ以上増やさないよう、常時表示は1個の
// メニューアイコンに集約する（ユーザー指示2026-09-01。WarningBadgeListと同じ
// 「常時1行のトリガー→タップで詳細」パターンをRadix Popoverで踏襲）。
//
// 研究モードON/OFF（実験スロット記録・比較タブ・地図重ね描き）を、`/admin`を一切
// 経由せずここから直接切り替えられるようにする——従来は`researchEnabled`
// フラグの実体が素のlocalStorageで、有効化する意図されたUIが`/admin`の
// `ResearchPanel`（Basic認証保護下）にしかなかったが、フラグ自体にサーバー側検証は
// 無く、`/`（認証なし）のDevToolsコンソールから直接操作可能だった（T519調査）。
// 「隠すべき機微な機能ではなく、気軽に試せる比較機能」という結論に基づき、一般
// 利用者向けの正式なON/OFF導線としてここへ配置する（`WeightPanel`[評価重み上書き]は
// 引き続き`/admin`限定）。
export default function HeaderMenu({ debugEnabled, debugConsoleOpen, onToggleDebugConsole }: HeaderMenuProps) {
  const researchEnabled = useResearchEnabled();

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <Button variant="ghost" size="sm" aria-label="メニュー" className="shrink-0">
          <MenuIcon size={15} />
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className={styles.menuPanel} side="bottom" align="end" sideOffset={6}>
          <label className={styles.menuItem}>
            <Checkbox
              checked={researchEnabled}
              onCheckedChange={setResearchEnabled}
              aria-label="研究モード[重み調整・実験スロット・比較]"
            />
            研究モード[重み調整・実験スロット・比較]
          </label>
          {debugEnabled && (
            <button
              type="button"
              className={styles.menuItem}
              onClick={onToggleDebugConsole}
              aria-pressed={debugConsoleOpen}
            >
              <LogIcon size={15} />
              {debugConsoleOpen ? "デバッグログを隠す" : "デバッグログを表示"}
            </button>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
