"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button/Button";
import { Card } from "@/components/ui/Card/Card";
import { listTuningParameters, updateTuningParameter, type TuningParameter } from "@/services/tuningApi";
import styles from "./TuningPanel.module.css";

/** 変えたとき効くまでに何が要るか（backendの`TuningEffect`）。**画面はこの値でまとめる**
 * ——項目の名前で振り分けると、較正値を1つ足したときにここだけが古くなる。
 * 見出しと断りは「効き方」1つにつき1組で、項目が増えても増えない。 */
const EFFECT_GROUPS: { effect: string; heading: string; note?: string }[] = [
  { effect: "immediate", heading: "次のルート生成から効く" },
  {
    effect: "turn_structure",
    heading: "次のルート生成から効く（探索木を組み直す）",
    note: "同じ道路網でも組み直しが入るため、変えた直後の1回だけ生成が遅くなります。",
  },
  {
    effect: "node_attribute_batch",
    heading: "交差点の事前計算をやり直すまで効かない",
    note: "変えても、road_nodesの事前計算バッチを回すまで結果は変わりません（「データ保守」タブ参照）。",
  },
  {
    effect: "restart",
    heading: "backendを入れ替えるまで効かない",
    note: "APIの既定値として起動時に束ねているため、変更はデプロイ後に効きます。",
  },
];

function formatDefault(parameter: TuningParameter): string {
  return `既定 ${parameter.default}${parameter.unit}`;
}

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
    <div className={`${styles.row} ${parameter.overridden ? styles.overridden : ""}`}>
      <span className={styles.label}>{parameter.label}</span>
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
      <span className={styles.default}>{formatDefault(parameter)}</span>
      {parameter.overridden && (
        <Button onClick={() => void commit(null)} disabled={saving}>
          既定へ戻す
        </Button>
      )}
      <p className={styles.description}>{parameter.description}</p>
    </div>
  );
}

/** 走ってみて決める値（`backend/app/domain/tuning.py`の宣言）を、デプロイなしで変える画面。
 *
 * **並べる項目はbackendが宣言から導く**ため、較正値を1つ足してもこの画面は変えなくてよい。
 * 効き方（`effect`）ごとにまとめるのは、変更が別の操作を要する群を利用者から見えるように
 * するため——同じ見た目で並べると「変えたのに効かない」に気づけない。
 */
export default function TuningPanel() {
  const [parameters, setParameters] = useState<TuningParameter[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 開いた時点で取りに行くため、最初から読み込み中で始める（effectの中で同期に
  // setStateすると描画の連鎖を呼ぶ）。
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
  const groups = [
    ...EFFECT_GROUPS,
    { effect: "__other__", heading: "その他" },
  ].map((group) => ({
    ...group,
    rows: (parameters ?? []).filter((p) =>
      group.effect === "__other__" ? !known.has(p.effect) : p.effect === group.effect,
    ),
  }));

  return (
    <Card className={styles.panel}>
      <h2 className={styles.heading}>較正値</h2>
      <p className={styles.lead}>
        走ってみて決める値です。実測ではなく実感に合わせて置いてあり、ここで変えるとデプロイなしで
        次のルート生成から効きます（効き方が違うものは下の見出しで分けています）。
      </p>

      {error && <p className={styles.error}>{error}</p>}

      {parameters === null ? (
        <Button onClick={reload} disabled={loading}>
          {loading ? "読み込み中…" : "読み込む"}
        </Button>
      ) : (
        groups
          .filter((group) => group.rows.length > 0)
          .map((group) => (
            <section className={styles.group} key={group.effect}>
              <h3 className={styles.groupHeading}>{group.heading}</h3>
              {group.note && <p className={styles.groupNote}>{group.note}</p>}
              {group.rows.map((parameter) => (
                <TuningRow
                  // 値が変わったら作り直す。effectで入力欄へ書き戻すと、描画の連鎖を
                  // 呼ぶうえに「入力中の値を外から上書きする」経路ができる。
                  key={`${parameter.id}:${parameter.value}`}
                  parameter={parameter}
                  onSaved={handleSaved}
                  onError={setError}
                />
              ))}
            </section>
          ))
      )}
    </Card>
  );
}
