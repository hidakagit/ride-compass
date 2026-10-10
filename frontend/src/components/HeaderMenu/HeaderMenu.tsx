"use client";

import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { Button } from "@/components/ui/Button/Button";
import { DialogContent, DialogRoot } from "@/components/ui/Dialog/Dialog";
import { HelpIcon, LogIcon, MenuIcon, RedrawMapIcon, VersionIcon } from "@/components/ui/icons/icons";
import { textVariants } from "@/components/ui/Text/Text";
import { Toggle } from "@/components/ui/Toggle/Toggle";
import { getQueryClient } from "@/lib/queryClient";
import { getFrontendVersion } from "@/services/versionApi";

interface HeaderMenuProps {
  /** デバッグログ項目自体の表示可否（デバッグモードのON/OFFは/adminで切り替える）。 */
  debugEnabled: boolean;
  debugConsoleOpen: boolean;
  onToggleDebugConsole: () => void;
  /** 説明を見る状態に入る（次に押した部品の使い方を出す）。 */
  onStartUsageGuide: () => void;
  /** 押した人の地図だけを描き直す（ページを読み込み直すと生成したルートが消える）。 */
  onRedrawMap: () => void;
}

// ヘッダーの狭い幅に個別のボタンを並べず、常時出すのは1個のメニューアイコンにして、項目は押して開く中に置く。
export default function HeaderMenu({
  debugEnabled,
  debugConsoleOpen,
  onToggleDebugConsole,
  onStartUsageGuide,
  onRedrawMap,
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
            usage="使い方の説明・地図の描き直しなどを開きます。"
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
          <Button
            variant="menu"
            size="sm"
            usage="地図の表示が欠けたときに、地図だけを描き直します。作ったルートは消えません。"
            onClick={() => {
              onRedrawMap();
              setOpen(false);
            }}
          >
            <RedrawMapIcon size={15} />
            地図の表示を再描画
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
            usage="本番で今動いている版を出します。"
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

  return (
    <DialogContent title="バージョン">
      {error && <p className={textVariants({ variant: "error" })}>{error.message}</p>}
      {!data && !error && <p className={textVariants({ variant: "hint" })}>読み込み中…</p>}
      {data &&
        (data.commit === null ? (
          <p className={textVariants({ variant: "hint" })}>手元で動いている版です（本番の版ではありません）。</p>
        ) : (
          <p className={textVariants({ variant: "body" })}>
            版 <span className={textVariants({ variant: "code" })}>{data.commit.slice(0, SHORT_COMMIT_LENGTH)}</span>
          </p>
        ))}
    </DialogContent>
  );
}
