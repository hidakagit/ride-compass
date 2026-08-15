"use client";

import { useState } from "react";
import { ROAD_FILTER_AXES, type RoadFilterAxisId } from "@/components/Map/roadFilterAxes";
import WidthSwatch from "./WidthSwatch";
import styles from "./RoadFilterEditor.module.css";

type HiddenKeysByMode = Record<RoadFilterAxisId, readonly string[]>;

function cloneHiddenKeys(source: HiddenKeysByMode): Record<RoadFilterAxisId, string[]> {
  return {
    surface: [...source.surface],
    highway: [...source.highway],
  };
}

function sameKeys(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((key) => b.includes(key));
}

function sameHiddenKeys(a: HiddenKeysByMode, b: HiddenKeysByMode): boolean {
  return ROAD_FILTER_AXES.every((axis) => sameKeys(a[axis.id] ?? [], b[axis.id] ?? []));
}

interface RoadFilterEditorProps {
  savedHiddenKeys: HiddenKeysByMode;
  /** 「適用」で2軸分の下書きがまとめて渡る（適用まで地図には反映しない） */
  onApply: (hiddenKeysByMode: Record<RoadFilterAxisId, string[]>) => void;
}

// 路面の絞り込み設定（路面の種類×道路の種類、独立2軸のAND絞り込み）を編集する
// サイドバー内エディタ。以前は地図上の⚙から開くモーダル（RoadFilterDialog）だったが、
// 「細かな設定はサイドバーへ集約する」UI再構成でここへ移した。
//
// 「下書き→適用」方式は維持する: チェックのたびに即座に地図へ反映すると、複数条件を
// 組み合わせたい途中経過も毎回描画されて操作しづらい、というフィードバックでモーダル化
// した経緯があり、サイドバーに移しても地図は隣に見えているため同じ問題が起きる。
// 下書き状態はこのコンポーネント内だけで持ち、適用を押すまで親（page.tsx）の実状態には
// 一切影響しない（ルート凡例のような単純なチェックは即時反映のままで使い分ける）。
export default function RoadFilterEditor({ savedHiddenKeys, onApply }: RoadFilterEditorProps) {
  const [draftHidden, setDraftHidden] = useState<Record<RoadFilterAxisId, string[]>>(() =>
    cloneHiddenKeys(savedHiddenKeys),
  );

  // savedHiddenKeys（適用済みの実状態）が変わる経路は現状このエディタの「適用」のみで、
  // 適用直後は下書き＝実状態になるため、propsから下書きへの明示的な同期処理は持たない。
  // 将来、別経路（設定の読み込み等）でsavedが変わるようになったら追従処理を足すこと。
  const dirty = !sameHiddenKeys(draftHidden, savedHiddenKeys);

  function toggleDraftKey(axisId: RoadFilterAxisId, key: string) {
    setDraftHidden((prev) => {
      const current = prev[axisId];
      const next = current.includes(key) ? current.filter((k) => k !== key) : [...current, key];
      return { ...prev, [axisId]: next };
    });
  }

  function handleApply() {
    onApply(cloneHiddenKeys(draftHidden));
  }

  function handleDiscard() {
    setDraftHidden(cloneHiddenKeys(savedHiddenKeys));
  }

  const savedFilterCount = ROAD_FILTER_AXES.reduce(
    (sum, axis) => sum + (savedHiddenKeys[axis.id]?.length ?? 0),
    0
  );

  return (
    <details className={styles.editor}>
      {/* <summary>はブラウザ既定でrole=group内のボタン相当として振る舞う。適用中の絞り込みが
          あることは開かなくても分かるようにラベルへ添える */}
      <summary className={styles.editorSummary}>
        絞り込みを編集{savedFilterCount > 0 ? "（適用中）" : ""}
      </summary>

      <div className={styles.body}>
        {/* 「路面の種類からアスファルト、道路の種類から自転車・歩行者道」のように、
            独立した2軸のカテゴリを組み合わせて絞り込める。両軸分のチェックボックスを
            常に全て並べる（一方だけ選ぶ、という排他選択ではない）。 */}
        {ROAD_FILTER_AXES.map((axis) => (
          <section key={axis.id}>
            <p className={styles.sectionLabel}>{axis.label}で絞り込み</p>
            <div className={styles.checkboxList}>
              {axis.legend.map((entry) => {
                const visible = !draftHidden[axis.id].includes(entry.key);
                return (
                  <label key={entry.key} className={styles.checkboxRow}>
                    <input type="checkbox" checked={visible} onChange={() => toggleDraftKey(axis.id, entry.key)} />
                    {/* 太さ(width)を持つ軸（道路の種類）は色が地図に出ないため、色スウォッチではなく
                        実際の太さのプレビューを見せる（WidthSwatch参照）。 */}
                    {entry.width !== undefined ? (
                      <WidthSwatch width={entry.width} dashed={entry.dashed} />
                    ) : (
                      <span className={styles.swatch} style={{ background: entry.color }} />
                    )}
                    {entry.label}
                  </label>
                );
              })}
            </div>
          </section>
        ))}

        <div className={styles.footer}>
          {dirty && <span className={styles.dirtyHint}>未適用の変更があります</span>}
          <button type="button" onClick={handleDiscard} disabled={!dirty} className={styles.discardButton}>
            編集を破棄
          </button>
          <button type="button" onClick={handleApply} disabled={!dirty} className={styles.applyButton}>
            適用
          </button>
        </div>
      </div>
    </details>
  );
}
