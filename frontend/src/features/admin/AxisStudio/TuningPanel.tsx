"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button/Button";
import { Card } from "@/components/ui/Card/Card";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { listTuningParameters, updateTuningParameter, type TuningParameter } from "@/features/admin/adminApi";
import { NumberInput } from "@/components/ui/NumberInput/NumberInput";
import { textVariants } from "@/components/ui/Text/Text";
import { dotVariants } from "@/components/ui/Dot/Dot";
import { cn } from "@/lib/cn";

/** 1件ぶんの行。入力中の値は親がまとめて持ち、この行は表示だけを担う
 * （保存はDBへの書き込みのため、押した時にまとめて送る）。
 *
 * 説明と既定値・範囲は(i)の奥へ置く——**行ごとに説明を敷くと、縦に並んだ全体を
 * 一覧として読めなくなる**（項目数は運用で増える）。 */
function TuningRow({
  parameter,
  draft,
  edited,
  onChange,
}: {
  parameter: TuningParameter;
  draft: number;
  edited: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <li className="flex items-center gap-2 border-b border-[var(--color-border)] py-1">
      <span
        className={parameter.overridden ? dotVariants({ tone: "accent" }) : dotVariants({ tone: "none" })}
        aria-hidden="true"
      />
      <InfoPopover
        triggerAriaLabel={`${parameter.label}の説明`}
        label={parameter.label}
        labelClassName={cn(textVariants({ variant: "body" }), "min-w-0 flex-auto [overflow-wrap:anywhere]")}
      >
        <p>{parameter.description}</p>
        <p>
          既定 {parameter.default}
          {parameter.unit}（{parameter.minimum}〜{parameter.maximum}）
        </p>
      </InfoPopover>
      <NumberInput
        commitOn="input"
        className={cn(
          "w-18 flex-none px-1 py-0.5 text-[length:var(--font-size-sm)] tabular-nums",
          edited && "border-[var(--color-accent)]",
        )}
        // 刻みを決めない（既定の1だと転がり抵抗0.005のような値が「刻みに合わない」扱いになる）。
        step="any"
        inputMode="decimal"
        aria-label={parameter.label}
        value={draft}
        min={parameter.minimum}
        max={parameter.maximum}
        onValueChange={onChange}
      />
      <span className={cn(textVariants({ variant: "note" }), "min-w-9 flex-none")}>{parameter.unit}</span>
    </li>
  );
}

/** 走ってみて決める値（`backend/app/domain/tuning.py`の宣言）を、デプロイなしで変える画面。
 *
 * **並べる項目はbackendが宣言から導く**ため、較正値を1つ足してもこの画面は変えなくてよい。
 * 効き方（`effect`）ごとにまとめるのは、変更が別の操作を要する群を利用者から見えるように
 * するため——同じ見た目で並べると「変えたのに効かない」に気づけない。
 *
 * 入力は打っただけでは効かせず、「DBへ保存」で送る（どれを書き込むのかが押す前に見えて
 * いないと、桁の途中の値が一瞬効く）。既定と同じ値にして保存すると上書きの行を消すため、
 * DBに残るのは既定から動かしたぶんだけになる。
 */
export default function TuningPanel() {
  const [parameters, setParameters] = useState<TuningParameter[] | null>(null);
  // 入力中の値（id → 値）。触った行だけを持ち、触っていない行はbackendの値を映す。
  const [drafts, setDrafts] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  // 開いた時点で取りに行くため、最初から読み込み中で始める。
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  // 取得はeffectの中で完結させ、**状態を書くのはawaitの後だけ**にする（effectの中で同期に
  // 書くと描画の連鎖を呼ぶ）。読み込み直しは合図（reloadToken）を進めてこのeffectへ戻す。
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const rows = await listTuningParameters();
        if (cancelled) return;
        setParameters(rows);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "較正値の取得に失敗しました");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  const rows = parameters ?? [];
  const draftOf = (parameter: TuningParameter) => drafts[parameter.id] ?? parameter.value;

  // 書き込む対象＝数として読めて、いま効いている値と違う行だけ。
  const edited = rows.filter((parameter) => {
    const draft = drafts[parameter.id];
    return draft !== undefined && draft !== parameter.value;
  });

  const save = async () => {
    setSaving(true);
    try {
      for (const parameter of edited) {
        const next = drafts[parameter.id]!;
        // 既定と同じ値に戻したら上書きを消す（DBに持つのは動かしたぶんだけ）。
        const updated = await updateTuningParameter(parameter.id, next === parameter.default ? null : next);
        setParameters((prev) => prev?.map((p) => (p.id === updated.id ? updated : p)) ?? prev);
        setDrafts((prev) => {
          const rest = { ...prev };
          delete rest[updated.id];
          return rest;
        });
      }
      setError(null);
    } catch (err) {
      // 打った値は消さない（範囲外なら直して押し直せる）。
      setError(err instanceof Error ? err.message : "保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  // 効き方ごとにまとめる。**効き方の一覧も見出しも持たない**——どちらもbackendの宣言
  // （`TuningEffect`）が持ち、APIが値（`effect`）と見出し（`effect_title`）を各項目へ
  // 添えて返す。並び順も返ってきた順のまま使う。効き方を1つ足しても、この画面に
  // 書き足す場所は無い。
  const groups: { effect: string; title: string; rows: TuningParameter[] }[] = [];
  for (const row of rows) {
    const group = groups.find((candidate) => candidate.effect === row.effect);
    if (group) {
      group.rows.push(row);
      continue;
    }
    groups.push({ effect: row.effect, title: row.effect_title, rows: [row] });
  }

  return (
    <Card className="flex flex-col gap-2">
      {/* 操作を上端へ置く（他の管理パネルと同じ並び）。一覧が縦に長いため、タブを開いた
          時点で「変えたらここで保存する」が目に入る位置に要る。 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex items-center gap-1">
          <h2 className={textVariants({ variant: "heading" })}>較正値</h2>
          <InfoPopover triggerAriaLabel="較正値の説明">
            <p>走ってみて決める値です。変えて保存すると、デプロイなしで効きます。</p>
            <p>●はDBへ保存済みの行です。既定と同じ値にして保存すると消えます。</p>
          </InfoPopover>
        </span>
        {parameters && (
          <Button variant="primary" onClick={() => void save()} disabled={saving || edited.length === 0}>
            {saving ? "保存中…" : "DBへ保存"}
          </Button>
        )}
        {edited.length > 0 && <span className={textVariants({ variant: "note" })}>{edited.length}件が未保存</span>}
        {loading && <span className={textVariants({ variant: "note" })}>読み込み中…</span>}
      </div>

      {error && (
        <p className={cn(textVariants({ variant: "error" }), "flex flex-wrap items-center gap-2")}>
          {error}
          {parameters === null && (
            <Button className="flex-none" size="sm" onClick={() => setReloadToken((token) => token + 1)}>
              読み込み直す
            </Button>
          )}
        </p>
      )}

      {groups.map((group) => (
        <div key={group.effect}>
          <p className={cn(textVariants({ variant: "note" }), "mt-2")}>{group.title}</p>
          <ul className="m-0 flex list-none flex-col p-0">
            {group.rows.map((parameter) => (
              <TuningRow
                key={parameter.id}
                parameter={parameter}
                draft={draftOf(parameter)}
                edited={edited.includes(parameter)}
                onChange={(value) => setDrafts((prev) => ({ ...prev, [parameter.id]: value }))}
              />
            ))}
          </ul>
        </div>
      ))}
    </Card>
  );
}
