"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button/Button";
import { Card } from "@/components/ui/Card/Card";
import InfoPopover from "@/components/Map/InfoPopover";
import floatingPopoverStyles from "@/components/ui/floatingPopover.module.css";
import { listTuningParameters, updateTuningParameter, type TuningParameter } from "@/services/tuningApi";
import styles from "./TuningPanel.module.css";

/** 変えたとき効くまでに何が要るか（backendの`TuningEffect`）。**画面はこの値でまとめる**
 * ——項目の名前で振り分けると、較正値を1つ足したときにここだけが古くなる。見出しは
 * 「効き方」1つにつき1本で、項目が増えても増えない。 */
const EFFECT_GROUPS: { effect: string; title: string }[] = [
  { effect: "immediate", title: "次のルート生成から効く" },
  { effect: "turn_structure", title: "次のルート生成から効く（1回だけ遅い）" },
  { effect: "node_attribute_batch", title: "交差点の事前計算をやり直すまで効かない" },
  { effect: "client_reload", title: "画面を読み込み直すと効く" },
];

const OTHER_GROUP = "__other__";

/** 1件ぶんの行。入力中の値は親がまとめて持ち、この行は表示だけを担う
 * （保存はDBへの書き込みのため、押した時にまとめて送る）。 */
function TuningRow({
  parameter,
  draft,
  edited,
  onChange,
}: {
  parameter: TuningParameter;
  draft: string;
  edited: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <li className={styles.row}>
      <span className={parameter.overridden ? styles.markSaved : styles.mark} aria-hidden="true" />
      <InfoPopover
        triggerClassName={styles.infoButton}
        triggerAriaLabel={`${parameter.label}の説明`}
        contentClassName={floatingPopoverStyles.floatingPopover}
        label={parameter.label}
        labelClassName={styles.rowName}
      >
        <p>{parameter.description}</p>
        <p>
          既定 {parameter.default}
          {parameter.unit}（{parameter.minimum}〜{parameter.maximum}）
        </p>
      </InfoPopover>
      <input
        className={edited ? styles.inputEdited : styles.input}
        type="number"
        // 刻みを決めない（既定の1だと転がり抵抗0.005のような値が「刻みに合わない」扱いになる）。
        step="any"
        inputMode="decimal"
        aria-label={parameter.label}
        value={draft}
        min={parameter.minimum}
        max={parameter.maximum}
        onChange={(event) => onChange(event.target.value)}
      />
      <span className={styles.unit}>{parameter.unit}</span>
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
  // 入力中の値（id → 文字列）。触った行だけを持ち、触っていない行はbackendの値を映す。
  const [drafts, setDrafts] = useState<Record<string, string>>({});
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
  const draftOf = (parameter: TuningParameter) => drafts[parameter.id] ?? String(parameter.value);

  // 書き込む対象＝数として読めて、いま効いている値と違う行だけ。
  const edited = rows.filter((parameter) => {
    const draft = drafts[parameter.id];
    if (draft === undefined || draft.trim() === "") return false;
    const parsed = Number(draft);
    return !Number.isNaN(parsed) && parsed !== parameter.value;
  });

  const save = async () => {
    setSaving(true);
    try {
      for (const parameter of edited) {
        const next = Number(drafts[parameter.id]);
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

  // 宣言に無い効き方が来ても落とさない（backendが先に増えてもこの画面は動き続ける）。
  const known = new Set(EFFECT_GROUPS.map((group) => group.effect));
  const groups = [...EFFECT_GROUPS, { effect: OTHER_GROUP, title: "その他" }]
    .map((group) => ({
      ...group,
      rows: rows.filter((p) => (group.effect === OTHER_GROUP ? !known.has(p.effect) : p.effect === group.effect)),
    }))
    .filter((group) => group.rows.length > 0);

  return (
    <Card className={styles.panel}>
      {/* 操作を上端へ置く（他の管理パネルと同じ並び）。一覧が縦に長いため、タブを開いた
          時点で「変えたらここで保存する」が目に入る位置に要る。 */}
      <div className={styles.controls}>
        <span className={styles.headingRow}>
          <h2 className={styles.heading}>較正値</h2>
          <InfoPopover
            triggerClassName={styles.infoButton}
            triggerAriaLabel="較正値の説明"
            contentClassName={floatingPopoverStyles.floatingPopover}
          >
            <p>走ってみて決める値です。変えて保存すると、デプロイなしで効きます。</p>
            <p>●はDBへ保存済みの行です。既定と同じ値にして保存すると消えます。</p>
          </InfoPopover>
        </span>
        {parameters && (
          <Button variant="primary" onClick={() => void save()} disabled={saving || edited.length === 0}>
            {saving ? "保存中…" : "DBへ保存"}
          </Button>
        )}
        {edited.length > 0 && <span className={styles.note}>{edited.length}件が未保存</span>}
        {loading && <span className={styles.note}>読み込み中…</span>}
      </div>

      {error && (
        <p className={styles.error}>
          {error}
          {parameters === null && (
            <Button className={styles.retry} size="sm" onClick={() => setReloadToken((token) => token + 1)}>
              読み込み直す
            </Button>
          )}
        </p>
      )}

      {groups.map((group) => (
        <div key={group.effect}>
          <p className={styles.groupTitle}>{group.title}</p>
          <ul className={styles.rows}>
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
