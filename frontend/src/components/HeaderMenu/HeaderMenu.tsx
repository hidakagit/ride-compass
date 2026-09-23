"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { setResearchEnabled } from "@/lib/researchMode";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { Button } from "@/components/ui/Button/Button";
import { LogIcon, MenuIcon } from "@/components/ui/icons/icons";
import { Toggle } from "@/components/ui/Toggle/Toggle";
import { toggleVariants } from "@/components/ui/Toggle/Toggle";

interface HeaderMenuProps {
  /** デバッグログ項目自体の表示可否（デバッグモードのON/OFFは/adminで切り替える、
   * 既存の`debugEnabled`条件をそのまま引き継ぐ）。 */
  debugEnabled: boolean;
  debugConsoleOpen: boolean;
  onToggleDebugConsole: () => void;
}

// ヘッダーの個別ボタンをこれ以上増やさないよう、常時表示は1個のメニューアイコンに
// 集約する（WarningBadgeListと同じ「常時1行のトリガー→タップで詳細」パターンを
// Radix Popoverで踏襲）。
//
// 研究モードON/OFF（実験スロット記録・比較タブ・地図重ね描き・区間の材料値）を、`/admin`を一切
// 経由せずここから直接切り替えられるようにする——`researchEnabled`フラグの実体は
// 素のlocalStorageで、フラグ自体にサーバー側検証は無く、`/`（認証なし）の
// DevToolsコンソールからも直接操作できる。「隠すべき機微な機能ではなく、気軽に
// 試せる比較機能」という位置づけのため、一般利用者向けの正式なON/OFF導線として
// ここへ配置する。
export default function HeaderMenu({ debugEnabled, debugConsoleOpen, onToggleDebugConsole }: HeaderMenuProps) {
  const researchEnabled = useResearchEnabled();

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" aria-label="メニュー" className="shrink-0">
          <MenuIcon size={15} />
        </Button>
      </PopoverTrigger>
      <PopoverContent layer="header" className="flex min-w-56 flex-col gap-1 p-1.5" side="bottom" align="end">
        <label className={toggleVariants({ variant: "menu" })}>
          <Checkbox
            checked={researchEnabled}
            onCheckedChange={setResearchEnabled}
            aria-label="研究モード[実験スロット・比較・材料値]"
          />
          研究モード[実験スロット・比較・材料値]
        </label>
        {debugEnabled && (
          <Toggle variant="menu" onClick={onToggleDebugConsole} pressed={debugConsoleOpen}>
            <LogIcon size={15} />
            {debugConsoleOpen ? "デバッグログを隠す" : "デバッグログを表示"}
          </Toggle>
        )}
      </PopoverContent>
    </Popover>
  );
}
