"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { useId, useMemo, useState, useSyncExternalStore } from "react";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { clampSpeedKmh, formatDepartureLabel } from "@/features/conditions/rideConditions";

import DynamicLayerTimeSlider from "@/features/conditions/DynamicLayerTimeSlider/DynamicLayerTimeSlider";
import { nearestTimeIndex, parseJstLocalValue, toJstLocalValue } from "@/lib/time";
import { ClockIcon, SpeedGaugeIcon } from "@/components/ui/icons/icons";
import { buildDepartureFrames, buildDepartureTimeline } from "./departureTimeline";
import { Button } from "@/components/ui/Button/Button";
import { NumberInput } from "@/components/ui/NumberInput/NumberInput";
import { Input } from "@/components/ui/Input/Input";
import { textVariants } from "@/components/ui/Text/Text";

const MIN_SPEED_KMH = routeGenerateConfig.min_assumed_speed_kmh;
const MAX_SPEED_KMH = routeGenerateConfig.max_assumed_speed_kmh;

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

const subscribeNothing = () => () => {};

// 地図右上の走行条件アイコン列。走行条件（出発時刻・想定速度）は評価軸の風（通過予測時刻・
// 風の抵抗）と気象レイヤーの表示時刻の両方が参照する共有stateのため、ルート設定フォームでは
// なく地図上に常時置き、アイコンをタップしてその場で変えられるようにする。TravelBearingControl
// と同じ列の幅のアイコンボタンに揃え、アイコンの下へ現在値を出す。表示・読み上げ
// （aria-label）・ホバー（title）は同じ文字列から作る（page.tsxがTravelBearingControlの直下へ積む）。
export default function RideConditionBar({
  departureTime,
  onDepartureTimeChange,
  onDepartureNow,
  speedKmh,
  onSpeedKmhChange,
}: RideConditionBarProps) {
  // ドラッグタイムラインの目盛りは開いた瞬間の時刻を基準に生成する（開いたまま長時間放置
  // されても「現在」ボタン・目盛りの基準がずれないよう、開くたびに作り直す）。閉じている間は
  // nullのままにしてPopover.Content自体が非マウントの間の無駄な計算を避ける。
  const [departureAnchor, setDepartureAnchor] = useState<Date | null>(null);
  const departureTimeline = useMemo(
    () => (departureAnchor ? buildDepartureTimeline(departureAnchor) : []),
    [departureAnchor],
  );
  const departureFrames = useMemo(() => buildDepartureFrames(departureTimeline), [departureTimeline]);
  const nowIndex = departureAnchor ? nearestTimeIndex(departureTimeline, departureAnchor) : 0;
  const speedInputId = useId();
  const departureInputId = useId();
  // 出発時刻の文言は描いた時刻で決まる。ページはビルド時に描かれるので、サーバーとハイドレーションの描画では
  // 出さず、ハイドレーションのあとに出す（出すとビルドの時刻の文言とずれ、ハイドレーションが不一致で失敗する）。
  const hydrated = useSyncExternalStore(
    subscribeNothing,
    () => true,
    () => false,
  );
  const departureLabel = hydrated ? formatDepartureLabel(departureTime) : null;
  const departureName = departureLabel ? `出発時刻: ${departureLabel}` : "出発時刻";
  const speedLabel = `${speedKmh}km/h`;

  return (
    <div
      className="pointer-events-auto flex flex-col gap-[var(--map-ctrl-stack-gap)]"
      role="group"
      aria-label="走行条件"
    >
      <Popover onOpenChange={(open) => setDepartureAnchor(open ? new Date() : null)}>
        <PopoverTrigger asChild>
          <Button
            variant="mapCtrl"
            size="mapCtrl"
            className="h-auto min-h-[var(--map-ctrl-button-size)] flex-col gap-px py-[3px]"
            aria-label={`${departureName}（タップで変更）`}
            title={departureName}
          >
            <ClockIcon />
            {/* 別の日は「9/24 12:40」になるため、列の幅に収まるよう日付と時刻を2行に分ける。 */}
            <span className="flex flex-col items-center text-[10px] leading-[1.1] font-semibold whitespace-nowrap">
              {departureLabel?.split(" ").map((part) => (
                <span key={part} className="block">
                  {part}
                </span>
              ))}
            </span>
          </Button>
        </PopoverTrigger>
        <PopoverContent
          tone="bare"
          className="flex max-w-[var(--radix-popover-content-available-width)] flex-col items-end gap-1"
          side="bottom"
          align="end"
          sideOffset={6}
          collisionPadding={8}
        >
          <Input
            id={departureInputId}
            type="datetime-local"
            aria-label="出発日時を直接指定"
            value={toJstLocalValue(departureTime)}
            onChange={(e) => {
              const next = parseJstLocalValue(e.target.value);
              if (!Number.isNaN(next.getTime())) onDepartureTimeChange(next);
            }}
            className="h-8 tabular-nums"
          />
          {departureAnchor && (
            <DynamicLayerTimeSlider
              frames={departureFrames}
              index={nearestTimeIndex(departureTimeline, departureTime)}
              // 「今」の目盛りを選んだら、その時刻に固定せず「今」への追従へ戻す——固定すると、
              // 放置するうちに過去になり、予報のレイヤーの範囲から外れて表示が消える。
              onIndexChange={(index) =>
                index === nowIndex ? onDepartureNow() : onDepartureTimeChange(departureTimeline[index])
              }
              currentIndex={nowIndex}
              onNow={onDepartureNow}
              ariaLabel="出発時刻"
            />
          )}
        </PopoverContent>
      </Popover>

      <Popover>
        <PopoverTrigger asChild>
          <Button
            variant="mapCtrl"
            size="mapCtrl"
            className="h-auto min-h-[var(--map-ctrl-button-size)] flex-col gap-px py-[3px]"
            aria-label={`想定速度: ${speedLabel}（タップで変更）`}
            title={`想定速度: ${speedLabel}`}
          >
            <SpeedGaugeIcon />
            <span className="flex flex-col items-center text-[10px] leading-[1.1] font-semibold whitespace-nowrap">
              {speedLabel}
            </span>
          </Button>
        </PopoverTrigger>
        <PopoverContent className="flex flex-col gap-2 px-2 py-1.5" side="bottom" align="end" collisionPadding={8}>
          <div className="flex items-center gap-2">
            <input
              type="range"
              aria-label="想定速度スライダー"
              min={MIN_SPEED_KMH}
              max={MAX_SPEED_KMH}
              step={1}
              value={speedKmh}
              onChange={(e) => onSpeedKmhChange(clampSpeedKmh(Number(e.target.value)))}
              className="min-w-32 flex-1"
            />
            <NumberInput
              commitOn="commit"
              id={speedInputId}
              aria-label="想定速度（km/h）"
              inputMode="numeric"
              min={MIN_SPEED_KMH}
              max={MAX_SPEED_KMH}
              step={1}
              value={speedKmh}
              onValueChange={(next) => onSpeedKmhChange(clampSpeedKmh(next))}
              className="h-8 w-18 tabular-nums"
            />
            <span className={textVariants({ variant: "hint" })}>km/h</span>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
