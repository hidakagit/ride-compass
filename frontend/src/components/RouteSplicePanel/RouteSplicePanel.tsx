"use client";

import ErrorText from "@/components/ErrorText/ErrorText";
import InfoPopover from "@/components/Map/InfoPopover";
import type { RouteCandidate } from "@/types/route";
import styles from "./RouteSplicePanel.module.css";

/** 区間1つぶんの選択肢（page.tsxが候補の名前まで組み立てて渡す）。 */
export interface SpliceGroupView {
  /** 区間の見出し（「1本目の区間」）。 */
  label: string;
  /** その区間で選べる道。`key`はpage.tsxが持つ代替の識別子。 */
  options: { key: string; label: string }[];
  /** いま選んでいる道。nullなら元のまま。 */
  chosenKey: string | null;
}

interface RouteSplicePanelProps {
  /** 編集の元。1本に固定で、候補を選び直しても変わらない。 */
  displayed: RouteCandidate;
  /** 区間ごとの選択肢。区間を主語にして、その区間の代替を候補横断で並べる。 */
  groups: SpliceGroupView[];
  /** 区間の道を選ぶ（同じものをもう一度選ぶと元のままへ戻る）。 */
  onChoose: (groupIndex: number, optionKey: string | null) => void;
  onApply: () => void;
  /** 合成した経路の評価を待っている間はtrue。 */
  applying: boolean;
  /** 合成に失敗した理由。押した場所から見えないと「押しても何も起きない」になる。 */
  error: string | null;
  /** 編集をやめて候補の一覧へ戻る。 */
  onCancel: () => void;
}

export default function RouteSplicePanel({
  displayed,
  groups,
  onChoose,
  onApply,
  applying,
  error,
  onCancel,
}: RouteSplicePanelProps) {
  // edge_idsを返さないエンジン・古い候補では区間を出せない（backendが空で返す）。
  const unavailable = displayed.edge_ids.length === 0;
  const chosenCount = groups.filter((group) => group.chosenKey !== null).length;

  return (
    <section className={styles.panel} aria-labelledby="splice-heading">
      <div className={styles.headingRow}>
        <button type="button" className={styles.back} aria-label="編集をやめて候補へ戻る" onClick={onCancel}>
          ‹
        </button>
        <h3 className={styles.heading} id="splice-heading">
          区間の乗り換え
        </h3>
        {/* 使い方は画面へ書かずここへ置く（設計原則「冗長なものは削る」）。 */}
        <InfoPopover
          triggerClassName={styles.headingInfo}
          triggerAriaLabel="区間の乗り換えの説明"
          contentClassName={styles.headingInfoPopover}
        >
          元のルートのうち、他の候補が別の道を通る区間だけを選んで取り込めます。地図のオレンジの
          帯がその区間で、タップしても選べます。
        </InfoPopover>
      </div>

      {/* 編集の元は1本に固定。候補を選び直しても変わらない。 */}
      <p className={styles.base}>
        元: {displayed.direction_label}（{displayed.distance_km.toFixed(1)}km）
      </p>

      {unavailable ? (
        <p className={styles.note}>この候補は経路のEdge情報を持たないため、区間を出せません。</p>
      ) : groups.length === 0 ? (
        <p className={styles.note}>他の候補と別の道を通る区間がありません。</p>
      ) : (
        <>
          <ul className={styles.rows}>
            {groups.map((group, groupIndex) => (
              <li key={group.label} className={styles.groupRow}>
                <span className={styles.where}>{group.label}</span>
                <div className={styles.options}>
                  <button
                    type="button"
                    className={group.chosenKey === null ? styles.optionOn : styles.option}
                    aria-pressed={group.chosenKey === null}
                    onClick={() => onChoose(groupIndex, null)}
                  >
                    元のまま
                  </button>
                  {group.options.map((option) => (
                    <button
                      key={option.key}
                      type="button"
                      className={group.chosenKey === option.key ? styles.optionOn : styles.option}
                      aria-pressed={group.chosenKey === option.key}
                      onClick={() => onChoose(groupIndex, option.key)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </li>
            ))}
          </ul>
          {error && <ErrorText>{error}</ErrorText>}
          <div className={styles.actions}>
            <button type="button" onClick={onApply} disabled={chosenCount === 0 || applying}>
              {applying ? "評価中…" : "新しいルートを作る"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
