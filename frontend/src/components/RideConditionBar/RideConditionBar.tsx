"use client";

import * as Popover from "@radix-ui/react-popover";
import { useId, useMemo, useState } from "react";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { clampSpeedKmh, formatDepartureLabel, toDatetimeLocalValue } from "@/lib/rideConditions";

const MIN_SPEED_KMH = routeGenerateConfig.min_assumed_speed_kmh;
const MAX_SPEED_KMH = routeGenerateConfig.max_assumed_speed_kmh;
import DynamicLayerTimeSlider from "@/components/DynamicLayerTimeSlider/DynamicLayerTimeSlider";
import { nearestTimeIndex } from "@/components/Map/dynamicWeather";
import { ClockIcon, SpeedGaugeIcon } from "@/components/Map/icons";
import { buildDepartureFrames, buildDepartureTimeline } from "./departureTimeline";
import styles from "./RideConditionBar.module.css";

const TRIGGER_ICON_SIZE_PX = 16;

interface RideConditionBarProps {
  /** 出発時刻（気象レイヤーの表示時刻と同じ共有state）。 */
  departureTime: Date;
  onDepartureTimeChange: (time: Date) => void;
  /** 「今」へ戻す。時刻を選ぶのとは別の操作——選んだ時刻はそこへ留まるが、「今」は
   * 時間の経過に追従する状態へ戻すため、`onDepartureTimeChange(new Date())`では代用
   * できない（現在時刻でピン留めされ、実況の更新から取り残される）。 */
  onDepartureNow: () => void;
  /** 想定速度（km/h、backend: RouteGenerateRequest.assumed_speed_kmh）。 */
  speedKmh: number;
  onSpeedKmhChange: (speedKmh: number) => void;
}

// 地図右上の走行条件アイコン列。走行条件（出発時刻・想定速度）は評価軸の風（通過予測時刻・
// 風の抵抗）と気象レイヤーの表示時刻の両方が参照する共有stateのため、ルート設定フォームでは
// なく地図上に常時置き、アイコンをタップしてその場で変えられるようにする。TravelBearingControl
// と同じアイコンボタンの見た目（29px四方）に揃え、値そのものはポップオーバーを開くまで
// 表示しない（page.tsx: .rideConditionColumnがTravelBearingControlの直下へ積む）。
export default function RideConditionBar({
  departureTime,
  onDepartureTimeChange,
  onDepartureNow,
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
    [departureAnchor],
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
          <button type="button" className={styles.trigger} aria-label={`出発時刻: ${departureLabel}（タップで変更）`}>
            <ClockIcon size={TRIGGER_ICON_SIZE_PX} />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            className={styles.timelinePopover}
            side="bottom"
            align="end"
            sideOffset={6}
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
                onNow={onDepartureNow}
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
          <button type="button" className={styles.trigger} aria-label={`想定速度: ${speedKmh} km/h（タップで変更）`}>
            <SpeedGaugeIcon size={TRIGGER_ICON_SIZE_PX} />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content className={styles.popover} side="bottom" align="end" sideOffset={6} collisionPadding={8}>
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
                aria-label="想定速度（km/h）"
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
              <span className={styles.unit}>km/h</span>
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
