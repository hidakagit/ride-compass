"use client";

import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { Button } from "@/components/ui/Button/Button";
import { DialogContent, DialogRoot } from "@/components/ui/Dialog/Dialog";
import { HelpIcon, LogIcon, MenuIcon, VersionIcon } from "@/components/ui/icons/icons";
import { textVariants } from "@/components/ui/Text/Text";
import { Toggle } from "@/components/ui/Toggle/Toggle";
import { cn } from "@/lib/cn";
import { getQueryClient } from "@/lib/queryClient";
import { formatJstDateTime } from "@/lib/time";
import { getFrontendVersion } from "@/services/versionApi";

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
export default function HeaderMenu({
  debugEnabled,
  debugConsoleOpen,
  onToggleDebugConsole,
  onStartUsageGuide,
}: HeaderMenuProps) {
  const [open, setOpen] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
  // メニューが閉じきってから入る先（説明を見る状態・バージョンの窓）。
  const afterClose = useRef<"guide" | "version" | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild ref={trigger}>
          <Button
            variant="ghost"
            size="sm"
            aria-label="メニュー"
            className="shrink-0"
            usage="使い方の説明などを開きます。"
          >
            <MenuIcon size={15} />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          layer="header"
          className="flex min-w-56 flex-col gap-1 p-1.5"
          side="bottom"
          align="end"
          // メニューが閉じきり、フォーカスを開くボタンへ戻してから入る。先に入ると、閉じる動きの間に部品を押して出た
          // 説明の面が、あとから戻るフォーカスを外への移りと読んで閉じる（バージョンの窓も、戻るフォーカスに窓の外へ
          // 引かれないよう同じく後に開く）。
          onCloseAutoFocus={(event) => {
            const next = afterClose.current;
            if (next === null) return;
            afterClose.current = null;
            event.preventDefault();
            trigger.current?.focus();
            if (next === "guide") onStartUsageGuide();
            else setVersionOpen(true);
          }}
        >
          {/* メニューを閉じてから入る（開いたままだと、次に押す部品の上にメニューが残る）。 */}
          <Button
            variant="menu"
            size="sm"
            usage="部品を押すと、その部品の使い方が出る状態に入ります。"
            onClick={() => {
              afterClose.current = "guide";
              setOpen(false);
            }}
          >
            <HelpIcon size={15} />
            使い方を見る
          </Button>
          {debugEnabled && (
            <Toggle
              variant="menu"
              onClick={onToggleDebugConsole}
              pressed={debugConsoleOpen}
              usage="開発者向けの記録の窓を出し入れします。"
            >
              <LogIcon size={15} />
              {debugConsoleOpen ? "デバッグログを隠す" : "デバッグログを表示"}
            </Toggle>
          )}
          <Button
            variant="menu"
            size="sm"
            usage="本番で今動いている版と、その版に入っている直近の変更を出します。"
            onClick={() => {
              afterClose.current = "version";
              setOpen(false);
            }}
          >
            <VersionIcon size={15} />
            バージョン表示
          </Button>
        </PopoverContent>
      </Popover>
      <DialogRoot open={versionOpen} onOpenChange={setVersionOpen}>
        {versionOpen && <VersionDialog />}
      </DialogRoot>
    </>
  );
}

// 版はコミットの頭8文字で出す（デプロイの記録・Pull Requestの画面と同じ長さ）。
const SHORT_COMMIT_LENGTH = 8;

function VersionDialog() {
  const { data, error } = useQuery({ queryKey: ["frontend-version"], queryFn: getFrontendVersion }, getQueryClient());
  const [latest] = data?.recent ?? [];

  return (
    <DialogContent title="バージョン">
      {error && <p className={textVariants({ variant: "error" })}>{error.message}</p>}
      {!data && !error && <p className={textVariants({ variant: "hint" })}>読み込み中…</p>}
      {data && (
        <div className={cn(textVariants({ variant: "body" }), "flex flex-col gap-2")}>
          {data.commit === null ? (
            <p className={textVariants({ variant: "hint" })}>手元で動いている版です（本番の版ではありません）。</p>
          ) : (
            <p>
              版 <span className={textVariants({ variant: "code" })}>{data.commit.slice(0, SHORT_COMMIT_LENGTH)}</span>
              {latest && `（${formatJstDateTime(new Date(latest.committed_at))} までのマージ）`}
            </p>
          )}
          {data.recent.length > 0 ? (
            <div>
              <p className={textVariants({ variant: "label" })}>入っている直近の変更</p>
              <ul className="mt-1 flex list-disc flex-col gap-1 pl-5">
                {data.recent.map(({ subject, committed_at }) => (
                  <li key={committed_at + subject}>{subject}</li>
                ))}
              </ul>
            </div>
          ) : (
            data.commit !== null && (
              <p className={textVariants({ variant: "hint" })}>入っている変更の件名は取れませんでした。</p>
            )
          )}
        </div>
      )}
    </DialogContent>
  );
}
