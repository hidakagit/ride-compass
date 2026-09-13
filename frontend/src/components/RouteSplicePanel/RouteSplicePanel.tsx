"use client";

import ErrorText from "@/components/ErrorText/ErrorText";
import InfoPopover from "@/components/Map/InfoPopover";
import { NewRouteIcon, RouteDiffIcon } from "@/components/Map/icons";
import type { RouteCandidate } from "@/types/route";
import styles from "./RouteSplicePanel.module.css";

/** 区間1つぶんの選択肢（page.tsxが候補の名前まで組み立てて渡す）。 */
export interface SpliceGroupView {
  /** 区間の見出し（「3.6〜39.8km」）。 */
  label: string;
  /** その区間で選べる道。`key`はpage.tsxが持つ代替の識別子、`hint`はどの候補の道か。 */
  options: { key: string; label: string; hint?: string }[];
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
  /** 「差分を見る」で評価した結果（元ルートとの差）。まだ見ていなければnull。 */
  diff: { distanceDeltaKm: number; difficultyDelta: number | null } | null;
  /** 差分の評価を待っている間はtrue。 */
  previewing: boolean;
  /** 選んだ組み合わせを評価して差分を出す。 */
  onPreview: () => void;
  onApply: () => void;
  /** 合成した経路の評価を待っている間はtrue。 */
  applying: boolean;
  /** 合成に失敗した理由。押した場所から見えないと「押しても何も起きない」になる。 */
  error: string | null;
  /** 編集をやめて候補の一覧へ戻る。 */
  onCancel: () => void;
}

/** 差は「増えた／減った」が一目で分かる形にする（0は「変わらない」と書く）。 */
function formatDelta(value: number, unit: string, digits: number): string {
  const rounded = Number(value.toFixed(digits));
  if (rounded === 0) return "変わらない";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(digits)}${unit}`;
}

export default function RouteSplicePanel({
  displayed,
  groups,
  onChoose,
  diff,
  previewing,
  onPreview,
  onApply,
  applying,
  error,
  onCancel,
}: RouteSplicePanelProps) {
  // edge_idsを返さないエンジン・古い候補では区間を出せない（backendが空で返す）。
  const unavailable = displayed.edge_ids.length === 0;
  const chosenCount = groups.filter((group) => group.chosenKey !== null).length;
  const busy = previewing || applying;
  const actionable = !unavailable && groups.length > 0;

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
          元のルートのうち、他の候補が別の道を通る区間だけを選んで取り込めます。区間は元ルートの
          何km地点かで示し、選べる道はその区間が何km長く（短く）なるかで示します。地図のオレンジの
          帯が同じ区間で、タップしても選べます。天秤は選んだ組み合わせの差を先に見るボタン、
          その隣は新しい候補として作るボタンです。
        </InfoPopover>
        {/* 操作は「ルート結果」ヘッダーの保存・GPX・削除と同じアイコン枠へ揃える
            （文言のボタンを並べるとパネル1つぶんの高さを操作だけで使う）。 */}
        {actionable && (
          <div className={styles.headingActions}>
            <button
              type="button"
              className={styles.actionIcon}
              onClick={onPreview}
              disabled={chosenCount === 0 || busy}
              aria-busy={previewing}
              aria-label="差分を見る"
              title="差分を見る"
            >
              <RouteDiffIcon size={18} />
            </button>
            <button
              type="button"
              className={styles.actionIcon}
              onClick={onApply}
              disabled={chosenCount === 0 || busy}
              aria-busy={applying}
              aria-label="新しいルートを作る"
              title="新しいルートを作る"
            >
              <NewRouteIcon size={18} />
            </button>
          </div>
        )}
      </div>

      {/* 編集の元（1本に固定）と、その元との差を同じ行に置く。どちらも同じ判断材料で、
          離して置くと1行ぶん余計に高さを使う。 */}
      <p className={styles.base}>
        <span>
          {displayed.direction_label} {displayed.distance_km.toFixed(1)}km
        </span>
        {busy ? (
          <span className={styles.progress}>{previewing ? "計算中…" : "評価中…"}</span>
        ) : (
          diff && (
            <span className={styles.diff}>
              {formatDelta(diff.distanceDeltaKm, "km", 1)}
              {diff.difficultyDelta !== null && <> ・ 難易度 {formatDelta(diff.difficultyDelta, "", 0)}</>}
            </span>
          )
        )}
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
                      aria-label={option.hint ? `${option.label}（${option.hint}）` : option.label}
                      title={option.hint}
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
        </>
      )}
    </section>
  );
}
