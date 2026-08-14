"use client";

import { useEffect, useRef, useState } from "react";
import { ROAD_FILTER_AXES, type RoadFilterAxisId } from "@/components/Map/roadFilterAxes";
import WidthSwatch from "./WidthSwatch";
import styles from "./RoadFilterDialog.module.css";

type HiddenKeysByMode = Record<RoadFilterAxisId, readonly string[]>;

interface RoadFilterDialogProps {
  open: boolean;
  /** キャンセル・×・背景クリック・Escapeいずれで閉じても呼ばれる（保存はしない） */
  onClose: () => void;
  roadHiddenKeysByMode: HiddenKeysByMode;
  onSave: (hiddenKeysByMode: Record<RoadFilterAxisId, string[]>) => void;
}

function cloneHiddenKeys(source: HiddenKeysByMode): Record<RoadFilterAxisId, string[]> {
  return {
    surface: [...source.surface],
    highway: [...source.highway],
  };
}

// 路面の絞り込み設定（路面の種類×道路の種類、独立2軸のAND絞り込み）をまとめて編集する
// 別ウィンドウ（モーダル）。これまでは地図上の▾で開く小さなパネルにチェックボックスを
// 並べていたが、
// - チェックのたびに即座に地図へ反映されるため、複数条件を組み合わせたい途中経過も
//   毎回描画されてしまい操作しづらい
// - 「今の状態が保存済みなのか作業中なのか」が地図側から分からない
// という声を受け、独立した画面で下書き編集→保存確定という流れに変更した。
// 下書き状態はこのコンポーネント内だけで持ち、保存を押すまで親（page.tsx）の実状態には
// 一切影響しない。
//
// 「色分け」の選択はここには無い（常に地図側で固定の軸=roadFilterAxes.tsの
// ROAD_LINE_COLOR_AXIS_IDの配色を使う）。かつては舗装/未舗装・路面の種類・道路の種類の
// 3モードから1つを選ぶ「色分け」もこの画面にあったが、舗装/未舗装は路面の種類と同じ
// タグの粗い再掲で独立した軸ではなく、また絞り込みで1カテゴリまで狭めた軸を色分けに
// 選べてしまうと単色になり情報量が無くなる、という混乱があったため廃止した。
export default function RoadFilterDialog({ open, onClose, roadHiddenKeysByMode, onSave }: RoadFilterDialogProps) {
  const [draftHidden, setDraftHidden] = useState<Record<RoadFilterAxisId, string[]>>(() =>
    cloneHiddenKeys(roadHiddenKeysByMode),
  );
  const dialogRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // openがfalse→trueに変わった瞬間だけ、保存済みの実状態から下書きを作り直す。
  // roadHiddenKeysByMode自体を依存に含めると、開いている間に親が再レンダーされるたびに
  // 下書き編集中の内容が失われてしまうため、ref経由の最新値参照＋open単独を依存にする
  // ことで「開いた瞬間の値」だけを拾う。
  const latestSavedRef = useRef(roadHiddenKeysByMode);
  useEffect(() => {
    latestSavedRef.current = roadHiddenKeysByMode;
  });
  useEffect(() => {
    if (!open) return;
    setDraftHidden(cloneHiddenKeys(latestSavedRef.current));
    // ダイアログが開いたら見出しへフォーカスし、スクリーンリーダー利用時も
    // 「別ウィンドウに切り替わった」ことが分かるようにする
    headingRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  function toggleDraftKey(axisId: RoadFilterAxisId, key: string) {
    setDraftHidden((prev) => {
      const current = prev[axisId];
      const next = current.includes(key) ? current.filter((k) => k !== key) : [...current, key];
      return { ...prev, [axisId]: next };
    });
  }

  function handleSave() {
    onSave(draftHidden);
    onClose();
  }

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="road-filter-dialog-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>
          {/* tabIndex=-1: クリックでは選択されないがJSからfocus()できるようにするため */}
          <h2 id="road-filter-dialog-title" ref={headingRef} tabIndex={-1} className={styles.title}>
            路面の表示設定
          </h2>
          <button type="button" onClick={onClose} aria-label="閉じる" className={styles.closeButton}>
            ✕
          </button>
        </div>

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
                      <input
                        type="checkbox"
                        checked={visible}
                        onChange={() => toggleDraftKey(axis.id, entry.key)}
                      />
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
        </div>

        <div className={styles.footer}>
          <button type="button" onClick={onClose} className={styles.cancelButton}>
            キャンセル
          </button>
          <button type="button" onClick={handleSave} className={styles.saveButton}>
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
