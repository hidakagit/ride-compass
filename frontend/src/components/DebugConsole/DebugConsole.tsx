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
  /** パネル自体の開閉（デバッグモードのON/OFFとは別。常時占有させたくないため
   * 「設定」内のボタンから開閉する） */
  open: boolean;
  onClose: () => void;
}

// info < warn < error の順で「この段階以上だけ表示」というしきい値フィルタにする
// （個別レベルのON/OFFではなく段階選択にすることで、選択肢を3つの<select>に収める）。
const LEVEL_ORDER: readonly DebugLogLevel[] = ["info", "warn", "error"];

// デバッグモードON時のみ、地図の上に浮かべて表示するイベントログ。
// マップの表示イベント（初期化・タイル/スタイル要求・パン/ズーム）と外部API呼び出し
// （天候/ルート生成/地域レイヤー/基礎地図）を発生順に積む。DebugPanelのトグルと状態を共有する。
// デバッグモードON＝ログの記録自体は常時有効だが、このパネル表示は別途openで制御する
// （常時ONだと画面の目立つ面積を占有し続けるため）。
// バックエンドの集計・commit等の「システム状況」は別パネル（SystemStatusPanel）へ
// 分離してある（ログ本文と情報源・更新頻度が異なる別種の情報を1つのパネルに詰め込むと
// 見づらいため）。
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

  // 画面に出ているものをそのまま貼れる形にする（絞り込みを無視して全件にすると、絞って
  // 見つけた数行を渡したいときに関係ない行まで混ざる）。
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
            <span className="text-[var(--color-accent)]">[{entry.category}]</span>{" "}
            <span className="">{entry.message}</span>
            {entry.detail != null && <span className="text-[var(--color-muted)]"> {JSON.stringify(entry.detail)}</span>}
          </LogLine>
        ))}
      </div>
    </FloatingPanel>
  );
}
