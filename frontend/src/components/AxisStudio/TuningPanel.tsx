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
  { effect: "turn_structure", title: "次のルート生成から効く（探索木を組み直すぶん、直後の1回だけ遅い）" },
  { effect: "node_attribute_batch", title: "交差点の事前計算をやり直すまで効かない" },
  { effect: "restart", title: "backendを入れ替えるまで効かない" },
];

const OTHER_GROUP = "__other__";

/** 1件ぶんの行。入力中は文字列のまま持ち、確定（blur/Enter）で送る——1文字打つたびに
 * 送ると、桁の途中の値が一瞬効いてしまう。 */
function TuningRow({
  parameter,
  onSaved,
  onError,
}: {
  parameter: TuningParameter;
  onSaved: (updated: TuningParameter) => void;
  onError: (message: string) => void;
}) {
  const [draft, setDraft] = useState(String(parameter.value));
  const [saving, setSaving] = useState(false);

  const commit = async (next: number | null) => {
    setSaving(true);
    try {
      onSaved(await updateTuningParameter(parameter.id, next));
    } catch (error) {
      onError(error instanceof Error ? error.message : "更新に失敗しました");
      setDraft(String(parameter.value));
    } finally {
      setSaving(false);
    }
  };

  const commitDraft = () => {
    const parsed = Number(draft);
    if (draft.trim() === "" || Number.isNaN(parsed)) {
      setDraft(String(parameter.value));
      return;
    }
    if (parsed === parameter.value) return;
    void commit(parsed);
  };

  return (
    <li className={styles.row}>
      <span
        className={parameter.overridden ? styles.markOverridden : styles.mark}
        aria-hidden="true"
      />
      <InfoPopover
        triggerClassName={styles.infoButton}
        triggerAriaLabel={`${parameter.label}の説明`}
        contentClassName={floatingPopoverStyles.floatingPopover}
        label={parameter.label}
        labelClassName={styles.rowName}
        side="right"
      >
        <p>{parameter.description}</p>
        <p>
          既定 {parameter.default}
          {parameter.unit}（{parameter.minimum}〜{parameter.maximum}）
        </p>
      </InfoPopover>
      <input
        className={styles.input}
        type="number"
        inputMode="decimal"
        aria-label={parameter.label}
        value={draft}
        min={parameter.minimum}
        max={parameter.maximum}
        disabled={saving}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commitDraft}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
      />
      <span className={styles.unit}>{parameter.unit}</span>
      {parameter.overridden ? (
        <button
          type="button"
          className={styles.reset}
          onClick={() => void commit(null)}
          disabled={saving}
          title={`既定（${parameter.default}${parameter.unit}）へ戻す`}
        >
          ↺<span className={styles.srOnly}>{parameter.label}を既定へ戻す</span>
        </button>
      ) : (
        <span className={styles.resetPlaceholder} aria-hidden="true" />
      )}
    </li>
  );
}

/** 走ってみて決める値（`backend/app/domain/tuning.py`の宣言）を、デプロイなしで変える画面。
 *
 * **並べる項目はbackendが宣言から導く**ため、較正値を1つ足してもこの画面は変えなくてよい。
 * 効き方（`effect`）ごとにまとめるのは、変更が別の操作を要する群を利用者から見えるように
 * するため——同じ見た目で並べると「変えたのに効かない」に気づけない。
 *
 * 1件=1行で、説明と既定値・範囲は(i)の奥へ置く（他の管理パネルと同じ省スペースの作り。
 * 21件が縦に並ぶため、行ごとに説明を敷くと一覧として読めなくなる）。
 */
export default function TuningPanel() {
  const [parameters, setParameters] = useState<TuningParameter[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 開いた時点で取りに行くため、最初から読み込み中で始める。
  const [loading, setLoading] = useState(true);
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

  const reload = () => {
    setLoading(true);
    setError(null);
    setReloadToken((token) => token + 1);
  };

  const handleSaved = (updated: TuningParameter) => {
    setError(null);
    setParameters((prev) => prev?.map((p) => (p.id === updated.id ? updated : p)) ?? prev);
  };

  // 宣言に無い効き方が来ても落とさない（backendが先に増えてもこの画面は動き続ける）。
  const known = new Set(EFFECT_GROUPS.map((group) => group.effect));
  const groups = [...EFFECT_GROUPS, { effect: OTHER_GROUP, title: "その他" }]
    .map((group) => ({
      ...group,
      rows: (parameters ?? []).filter((p) =>
        group.effect === OTHER_GROUP ? !known.has(p.effect) : p.effect === group.effect,
      ),
    }))
    .filter((group) => group.rows.length > 0);

  const overriddenCount = (parameters ?? []).filter((p) => p.overridden).length;

  return (
    <Card className={styles.panel}>
      <div className={styles.controls}>
        <span className={styles.headingRow}>
          <h2 className={styles.heading}>較正値</h2>
          <InfoPopover
            triggerClassName={styles.infoButton}
            triggerAriaLabel="較正値の説明"
            contentClassName={floatingPopoverStyles.floatingPopover}
          >
            <p>
              走ってみて決める値です。実感に合わせて置いたまま較正されていません。ここで変えると
              デプロイなしで効きます（効き方が違うものは見出しで分けています）。
            </p>
            <p>●が付いている行は既定から動かしてあります。↺で戻せます。</p>
          </InfoPopover>
        </span>
        <Button onClick={reload} disabled={loading}>
          {loading ? "読み込み中…" : "読み込み直す"}
        </Button>
        {parameters && <span className={styles.groupTitle}>{overriddenCount}件が既定から変更</span>}
      </div>

      {error && <p className={styles.error}>{error}</p>}

      {groups.map((group) => (
        <div key={group.effect}>
          <p className={styles.groupTitle}>{group.title}</p>
          <ul className={styles.rows}>
            {group.rows.map((parameter) => (
              <TuningRow
                // 値が変わったら作り直す。effectで入力欄へ書き戻すと、描画の連鎖を呼ぶうえに
                // 「入力中の値を外から上書きする」経路ができる。
                key={`${parameter.id}:${parameter.value}`}
                parameter={parameter}
                onSaved={handleSaved}
                onError={setError}
              />
            ))}
          </ul>
        </div>
      ))}
    </Card>
  );
}
