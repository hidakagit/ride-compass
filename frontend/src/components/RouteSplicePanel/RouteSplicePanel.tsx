"use client";

import type { RouteStretch } from "@/lib/routeSplice";
import type { RouteCandidate } from "@/types/route";
import styles from "./RouteSplicePanel.module.css";

interface RouteSplicePanelProps {
  /** 表示中の候補。これを基準に「相手が別の道を通る区間」を出す。 */
  displayed: RouteCandidate;
  /** 比較相手に選べる候補（表示中の候補を除く）。 */
  targets: readonly RouteCandidate[];
  /** 比較相手のid。未選択はnull。 */
  targetId: string | null;
  onSelectTarget: (id: string | null) => void;
  /** 表示中の候補が相手と別の道を通る区間（起点に近い順）。 */
  stretches: readonly RouteStretch[];
  /** 相手の道を選んでいる区間の位置（`stretches`の添字）。 */
  takenIndexes: readonly number[];
  onToggleStretch: (index: number) => void;
  onApply: () => void;
  /** 合成した経路の評価を待っている間はtrue。 */
  applying: boolean;
}

export default function RouteSplicePanel({
  displayed,
  targets,
  targetId,
  onSelectTarget,
  stretches,
  takenIndexes,
  onToggleStretch,
  onApply,
  applying,
}: RouteSplicePanelProps) {
  const taken = new Set(takenIndexes);
  // edge_idsを返さないエンジン・古い候補では区間を出せない（backendが空で返す）。
  const unavailable = displayed.edge_ids.length === 0;

  return (
    <section className={styles.panel} aria-label="区間の乗り換え">
      <div className={styles.head}>
        <label htmlFor="splice-target">比較相手</label>
        <select
          id="splice-target"
          value={targetId ?? ""}
          onChange={(event) => onSelectTarget(event.target.value || null)}
          disabled={unavailable || targets.length === 0}
        >
          <option value="">選択しない</option>
          {targets.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {candidate.direction_label}（{candidate.distance_km.toFixed(1)}km）
            </option>
          ))}
        </select>
      </div>

      {unavailable ? (
        <p className={styles.note}>この候補は経路のEdge情報を持たないため、区間を出せません。</p>
      ) : targetId === null ? (
        <p className={styles.note}>比較相手を選ぶと、相手が別の道を通る区間を地図に出します。</p>
      ) : stretches.length === 0 ? (
        <p className={styles.note}>この2本は同じ道を通ります。</p>
      ) : (
        <>
          <ul className={styles.rows}>
            {stretches.map((stretch, index) => (
              <li key={`${stretch.start}-${stretch.end}`}>
                <button
                  type="button"
                  className={styles.row}
                  aria-pressed={taken.has(index)}
                  onClick={() => onToggleStretch(index)}
                >
                  <span className={styles.tick} aria-hidden="true">
                    ✓
                  </span>
                  <span className={styles.where}>
                    {index + 1}本目の区間
                    <span className={styles.sub}>
                      {stretch.end - stretch.start}区画ぶん
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className={styles.actions}>
            <button type="button" onClick={onApply} disabled={taken.size === 0 || applying}>
              {applying ? "評価中…" : "この組み合わせを候補へ追加"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
