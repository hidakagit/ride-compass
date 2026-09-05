"use client";

import * as Popover from "@radix-ui/react-popover";
import { useId, useMemo, useState } from "react";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import DynamicLayerTimeSlider from "@/components/DynamicLayerTimeSlider/DynamicLayerTimeSlider";
import { nearestTimeIndex } from "@/components/Map/dynamicWeather";
import { buildDepartureFrames, buildDepartureTimeline } from "./departureTimeline";
import styles from "./RideConditionBar.module.css";

export interface RideConditionBarProps {
  /** 出発時刻（気象レイヤーの表示時刻と同じ共有state）。 */
  departureTime: Date;
  onDepartureTimeChange: (time: Date) => void;
  /** 想定速度（km/h、backend: RouteGenerateRequest.assumed_speed_kmh）。 */
  speedKmh: number;
  onSpeedKmhChange: (speedKmh: number) => void;
}

const MIN_SPEED_KMH = routeGenerateConfig.min_assumed_speed_kmh;
const MAX_SPEED_KMH = routeGenerateConfig.max_assumed_speed_kmh;

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/** 出発時刻の表示ラベル。当日は「9:30」、別日は「9/6 9:30」（ローカル時刻）。 */
export function formatDepartureLabel(time: Date, now: Date = new Date()): string {
  const hm = `${time.getHours()}:${pad2(time.getMinutes())}`;
  const sameDay =
    time.getFullYear() === now.getFullYear() && time.getMonth() === now.getMonth() && time.getDate() === now.getDate();
  return sameDay ? hm : `${time.getMonth() + 1}/${time.getDate()} ${hm}`;
}

/** input[type=datetime-local]のvalue形式（タイムゾーン無しのYYYY-MM-DDTHH:mm、
 * ローカル時刻）。この形式の文字列はnew Date()がローカル時刻として解釈するため、
 * 変換は往路（Date→この形式）だけ用意すればよい。 */
export function toDatetimeLocalValue(time: Date): string {
  return `${time.getFullYear()}-${pad2(time.getMonth() + 1)}-${pad2(time.getDate())}T${pad2(time.getHours())}:${pad2(time.getMinutes())}`;
}

export function clampSpeedKmh(value: number): number {
  if (!Number.isFinite(value)) return routeGenerateConfig.default_assumed_speed_kmh;
  return Math.min(MAX_SPEED_KMH, Math.max(MIN_SPEED_KMH, Math.round(value)));
}

// 地図下部の条件バー。走行条件（出発時刻・想定速度）は評価軸の風（通過予測時刻・風の抵抗）と
// 気象レイヤーの表示時刻の両方が参照する共有stateのため、ルート設定フォームではなく地図上に
// 常時置き、チップをタップしてその場で変えられるようにする。
export default function RideConditionBar({
  departureTime,
  onDepartureTimeChange,
  speedKmh,
  onSpeedKmhChange,
}: RideConditionBarProps) {
  const [speedDraft, setSpeedDraft] = useState<string | null>(null);
  // ドラッグタイムラインの目盛りは開いた瞬間の時刻を基準に生成する（開いたまま長時間放置
  // されても「現在」ボタン・目盛りの基準がずれないよう、開くたびに作り直す）。閉じている間は
  // nullのままにしてPopover.Content自体が非マウントの間の無駄な計算を避ける。
  const [departureAnchor, setDepartureAnchor] = useState<Date | null>(null);
  const departureTimeline = useMemo(
    () => (departureAnchor ? buildDepartureTimeline(departureAnchor) : []),
    [departureAnchor]
  );
  const departureFrames = useMemo(() => buildDepartureFrames(departureTimeline), [departureTimeline]);
  const speedInputId = useId();
  const departureInputId = useId();
  const departureLabel = formatDepartureLabel(departureTime);

  function commitSpeedDraft() {
    if (speedDraft == null) return;
    onSpeedKmhChange(clampSpeedKmh(Number(speedDraft)));
    setSpeedDraft(null);
  }

  return (
    <div className={styles.bar} role="group" aria-label="走行条件">
      <Popover.Root onOpenChange={(open) => setDepartureAnchor(open ? new Date() : null)}>
        <Popover.Trigger asChild>
          <button type="button" className={styles.chip} aria-label={`出発時刻: ${departureLabel}（タップで変更）`}>
            <span className={styles.chipKey}>出発</span>
            <span className={styles.chipValue}>{departureLabel}</span>
            <span aria-hidden="true" className={styles.chipCaret}>
              ▾
            </span>
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            className={styles.timelinePopover}
            side="top"
            align="start"
            sideOffset={8}
            collisionPadding={8}
          >
            <input
              id={departureInputId}
              type="datetime-local"
              aria-label="出発日時を直接指定"
              value={toDatetimeLocalValue(departureTime)}
              onChange={(e) => {
                const next = new Date(e.target.value);
                if (!Number.isNaN(next.getTime())) onDepartureTimeChange(next);
              }}
              className={`${styles.input} ${styles.directInput}`}
            />
            {departureAnchor && (
              <DynamicLayerTimeSlider
                frames={departureFrames}
                index={nearestTimeIndex(departureTimeline, departureTime)}
                onIndexChange={(index) => {
                  const time = departureTimeline[index];
                  if (time) onDepartureTimeChange(time);
                }}
                currentIndex={nearestTimeIndex(departureTimeline, departureAnchor)}
                onNow={() => onDepartureTimeChange(new Date())}
                loading={false}
                loadingLabel=""
                error={null}
                ariaLabel="出発時刻"
              />
            )}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>

      <Popover.Root onOpenChange={(open) => !open && commitSpeedDraft()}>
        <Popover.Trigger asChild>
          <button type="button" className={styles.chip} aria-label={`想定速度: ${speedKmh} km/h（タップで変更）`}>
            <span className={styles.chipValue}>{speedKmh}</span>
            <span className={styles.chipKey}>km/h</span>
            <span aria-hidden="true" className={styles.chipCaret}>
              ▾
            </span>
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content className={styles.popover} side="top" align="end" sideOffset={8} collisionPadding={8}>
            <label className={styles.field} htmlFor={speedInputId}>
              <span className={styles.fieldLabel}>想定速度（km/h）</span>
            </label>
            <div className={styles.speedRow}>
              <input
                type="range"
                aria-label="想定速度スライダー"
                min={MIN_SPEED_KMH}
                max={MAX_SPEED_KMH}
                step={1}
                value={speedKmh}
                onChange={(e) => onSpeedKmhChange(clampSpeedKmh(Number(e.target.value)))}
                className={styles.slider}
              />
              <input
                id={speedInputId}
                type="number"
                inputMode="numeric"
                min={MIN_SPEED_KMH}
                max={MAX_SPEED_KMH}
                step={1}
                value={speedDraft ?? String(speedKmh)}
                onChange={(e) => setSpeedDraft(e.target.value)}
                onBlur={commitSpeedDraft}
                onFocus={(e) => e.currentTarget.select()}
                className={styles.input}
              />
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
