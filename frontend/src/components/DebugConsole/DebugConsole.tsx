"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard";
import { useDebugEnabled, useDebugLogEntries } from "@/hooks/useDebugLog";
import { CopyIcon } from "@/components/ui/icons/icons";
import { clearDebugLog, type DebugLogLevel } from "@/lib/debugLog";
import FloatingPanel from "@/components/FloatingPanel/FloatingPanel";
import { Button } from "@/components/ui/Button/Button";
import { Select } from "@/components/ui/Input/Input";
import { LogLine } from "@/components/ui/LogLine/LogLine";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

interface DebugConsoleProps {
  /** パネルの開閉（デバッグモードのON/OFFとは別。記録はモードがONなら常に続く）。 */
  open: boolean;
  onClose: () => void;
}

// 「この段階以上だけ出す」の下限で絞る。
const LEVEL_ORDER: readonly DebugLogLevel[] = ["info", "warn", "error"];

/** デバッグモードのときだけ地図の上に浮かべる、地図の出来事とAPI呼び出しのログ。 */
export default function DebugConsole({ open, onClose }: DebugConsoleProps) {
  const enabled = useDebugEnabled();
  const entries = useDebugLogEntries();
  const listRef = useRef<HTMLDivElement>(null);
  const [minLevel, setMinLevel] = useState<DebugLogLevel>("info");
  const { copied, error: copyError, copy } = useCopyToClipboard();

  const visibleEntries = useMemo(
    () => entries.filter((entry) => LEVEL_ORDER.indexOf(entry.level) >= LEVEL_ORDER.indexOf(minLevel)),
    [entries, minLevel],
  );

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [visibleEntries]);

  // コピーするのは絞り込んで画面に出ている行だけ（絞って見つけた数行を渡せるように）。
  const visibleEntriesText = useMemo(
    () =>
      visibleEntries
        .map((entry) => {
          const detail = entry.detail == null ? "" : ` ${JSON.stringify(entry.detail)}`;
          return `${entry.time} [${entry.category}] ${entry.message}${detail}`;
        })
        .join("\n"),
    [visibleEntries],
  );

  if (!enabled) return null;

  return (
    <FloatingPanel
      open={open}
      onClose={onClose}
      title={`デバッグログ[${visibleEntries.length}/${entries.length}件]`}
      topRem={4.25}
      widthRem={22}
      maxHeightPx={420}
      headerButtons={
        <>
          <Select
            value={minLevel}
            onChange={(e) => setMinLevel(e.target.value as DebugLogLevel)}
            className="px-1 py-0.5 text-[length:var(--font-size-xs)]"
            aria-label="表示するログレベルの下限"
          >
            <option value="info">すべて</option>
            <option value="warn">警告以上</option>
            <option value="error">エラーのみ</option>
          </Select>
          <Button
            size="xs"
            onClick={() => copy(visibleEntriesText)}
            disabled={visibleEntries.length === 0}
            aria-label={copied ? "表示中のログをコピーしました" : "表示中のログをコピー"}
            title={copied ? "コピーしました" : "表示中のログをコピー"}
          >
            <CopyIcon size={14} />
          </Button>
          <Button size="xs" onClick={clearDebugLog}>
            クリア
          </Button>
        </>
      }
    >
      {copyError !== null && <p className={cn(textVariants({ variant: "error" }), "mb-1")}>{copyError}</p>}
      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-2 py-1 [overflow-wrap:anywhere]">
        {entries.length === 0 && (
          <p className={textVariants({ variant: "hint" })}>
            イベント待機中...[地図を操作するかAPIを呼び出してください]
          </p>
        )}
        {entries.length > 0 && visibleEntries.length === 0 && (
          <p className={textVariants({ variant: "hint" })}>
            条件に一致するログがありません[フィルタを「すべて」に戻すと{entries.length}件表示されます]
          </p>
        )}
        {visibleEntries.map((entry) => (
          <LogLine
            key={entry.id}
            tone={entry.level === "error" ? "error" : entry.level === "warn" ? "warning" : "normal"}
            data-level={entry.level}
          >
            <span className="text-[var(--color-muted)]">{entry.time}</span>{" "}
            <span className="text-[var(--color-accent)]">[{entry.category}]</span> <span>{entry.message}</span>
            {entry.detail != null && <span className="text-[var(--color-muted)]"> {JSON.stringify(entry.detail)}</span>}
          </LogLine>
        ))}
      </div>
    </FloatingPanel>
  );
}
