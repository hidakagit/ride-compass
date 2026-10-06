"use client";

import { useState } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { setResearchEnabled } from "@/lib/researchMode";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { Button } from "@/components/ui/Button/Button";
import { HelpIcon, LogIcon, MenuIcon } from "@/components/ui/icons/icons";
import { Toggle } from "@/components/ui/Toggle/Toggle";
import { toggleVariants } from "@/components/ui/Toggle/Toggle";

interface HeaderMenuProps {
  /** デバッグログ項目自体の表示可否（デバッグモードのON/OFFは/adminで切り替える、
   * 既存の`debugEnabled`条件をそのまま引き継ぐ）。 */
  debugEnabled: boolean;
  debugConsoleOpen: boolean;
  onToggleDebugConsole: () => void;
  /** 説明を見る状態に入る（次に押した部品の使い方を出す）。 */
  onStartUsageGuide: () => void;
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
export default function HeaderMenu({
  debugEnabled,
  debugConsoleOpen,
  onToggleDebugConsole,
  onStartUsageGuide,
}: HeaderMenuProps) {
  const researchEnabled = useResearchEnabled();
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          aria-label="メニュー"
          className="shrink-0"
          usage="使い方の説明・研究モードの切り替えを開きます。"
        >
          <MenuIcon size={15} />
        </Button>
      </PopoverTrigger>
      <PopoverContent layer="header" className="flex min-w-56 flex-col gap-1 p-1.5" side="bottom" align="end">
        {/* メニューを閉じてから入る（開いたままだと、次に押す部品の上にメニューが残る）。 */}
        <Button
          variant="menu"
          size="sm"
          onClick={() => {
            setOpen(false);
            onStartUsageGuide();
          }}
        >
          <HelpIcon size={15} />
          使い方を見る
        </Button>
        <label
          className={toggleVariants({ variant: "menu" })}
          data-usage="作ったルートを実験スロットに残し、候補を見比べる「比較」のタブ・地図への重ね描き・区間の材料の値を出します。"
        >
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
