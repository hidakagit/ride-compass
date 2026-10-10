"use client";

import { Popover, PopoverContent, PopoverTrigger, POPOVER_COLLISION_PADDING_PX } from "@/components/ui/Popover/Popover";
import { useState, useSyncExternalStore, type ComponentProps, type ReactNode } from "react";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { clampSpeedKmh, departureLabelParts, MAX_SPEED_KMH, MIN_SPEED_KMH } from "@/features/conditions/rideConditions";

import DynamicLayerTimeSlider from "@/features/conditions/DynamicLayerTimeSlider/DynamicLayerTimeSlider";
import { nearestTimeIndex, parseJstLocalValue, toJstLocalValue } from "@/lib/time";
import { ClockIcon, SpeedGaugeIcon } from "@/components/ui/icons/icons";
import { buildDepartureFrames, buildDepartureTimeline } from "./departureTimeline";
import { Button } from "@/components/ui/Button/Button";
import { NumberInput } from "@/components/ui/NumberInput/NumberInput";
import { Input } from "@/components/ui/Input/Input";
import { textVariants } from "@/components/ui/Text/Text";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { CLIENT_TUNING_IDS, clientTuningValue, type AxisCatalog } from "@/lib/axisCatalog";
import { axisNamesUsing } from "@/lib/catalogAxis";

/** 区間ごとに速度を変える条件の名前（backendの走行モデルが宣言する並び）。 */
const SPEED_CONDITIONS = routeGenerateConfig.segment_speed_conditions.join("・");

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

/** 想定速度の説明に出す走行モデルの標準値（管理画面の較正値）。1つでも引けなければ`null`——
 * 引けない間は標準値の文を出さない（較正したのとは別の数を出さない）。 */
function riderDefaultsOf(catalog: AxisCatalog) {
  const massKg = clientTuningValue(catalog, CLIENT_TUNING_IDS.massKg);
  const cdaM2 = clientTuningValue(catalog, CLIENT_TUNING_IDS.cdaM2);
  const maxDescentKmh = clientTuningValue(catalog, CLIENT_TUNING_IDS.maxDescentKmh);
  const walkingKmh = clientTuningValue(catalog, CLIENT_TUNING_IDS.walkingKmh);
  if (massKg === undefined || cdaM2 === undefined || maxDescentKmh === undefined || walkingKmh === undefined) {
    return null;
  }
  return { massKg, cdaM2, maxDescentKmh, walkingKmh };
}

/** 列のアイコンボタン。アイコンの下へ現在値を出し、読み上げ（aria-label）・ホバー（title）は同じ名前から作る。
 * `PopoverTrigger asChild`が開閉の props と ref をここへ渡すので、受けたものはそのままボタンへ通す。 */
function ConditionTrigger({
  name,
  icon,
  children,
  ...buttonProps
}: { name: string; icon: ReactNode } & ComponentProps<typeof Button>) {
  return (
    <Button
      {...buttonProps}
      variant="mapCtrl"
      size="mapCtrl"
      className="h-auto min-h-[var(--map-ctrl-button-size)] flex-col gap-px py-[3px]"
      aria-label={`${name}（タップで変更）`}
      title={name}
    >
      {icon}
      <span className="flex flex-col items-center text-[10px] leading-[1.1] font-semibold whitespace-nowrap">
        {children}
      </span>
    </Button>
  );
}

/** 出発時刻のドラッグタイムライン。目盛りは描き始めた（ポップオーバーを開いた）時刻を基準に一度だけ作る——開いたまま
 * 長時間放置されても「現在」ボタン・目盛りの基準がずれないよう、開くたびに作り直す。 */
function DepartureRuler({
  departureTime,
  onDepartureTimeChange,
  onDepartureNow,
}: Pick<RideConditionBarProps, "departureTime" | "onDepartureTimeChange" | "onDepartureNow">) {
  const [{ timeline, frames, nowIndex }] = useState(() => {
    const anchor = new Date();
    const timeline = buildDepartureTimeline(anchor);
    return { timeline, frames: buildDepartureFrames(timeline), nowIndex: nearestTimeIndex(timeline, anchor) };
  });
  return (
    <DynamicLayerTimeSlider
      frames={frames}
      index={nearestTimeIndex(timeline, departureTime)}
      // 「今」の目盛りを選んだら、その時刻に固定せず「今」への追従へ戻す——固定すると、
      // 放置するうちに過去になり、予報のレイヤーの範囲から外れて表示が消える。
      onIndexChange={(index) => (index === nowIndex ? onDepartureNow() : onDepartureTimeChange(timeline[index]))}
      currentIndex={nowIndex}
      onNow={onDepartureNow}
      ariaLabel="出発時刻"
    />
  );
}

// 地図右上の走行条件アイコン列。走行条件（出発時刻・想定速度）は時刻・速さで値の変わる評価と
// 気象レイヤーの表示時刻の両方が参照する共有stateのため、ルート設定フォームでは
// なく地図上に常時置き、アイコンをタップしてその場で変えられるようにする。TravelBearingControl
// と同じ列の幅のアイコンボタンに揃える（page.tsxがTravelBearingControlの直下へ積む）。
export default function RideConditionBar({
  departureTime,
  onDepartureTimeChange,
  onDepartureNow,
  speedKmh,
  onSpeedKmhChange,
}: RideConditionBarProps) {
  const axisCatalog = useAxisCatalog();
  const riderDefaults = riderDefaultsOf(axisCatalog);
  // 出発時刻で値の変わる評価の名前は軸カタログから引く。無ければ評価に触れない。
  const timeAxes = axisNamesUsing(axisCatalog.axes, "at");
  // 出発時刻の文言は描いた時刻で決まる。ページはビルド時に描かれるので、サーバーとハイドレーションの描画では
  // 出さず、ハイドレーションのあとに出す（出すとビルドの時刻の文言とずれ、ハイドレーションが不一致で失敗する）。
  const hydrated = useSyncExternalStore(
    subscribeNothing,
    () => true,
    () => false,
  );
  const departureLabel = hydrated ? departureLabelParts(departureTime, new Date()) : null;
  const departureName = departureLabel ? `出発時刻: ${departureLabel.join(" ")}` : "出発時刻";
  const speedLabel = `${speedKmh}km/h`;

  return (
    <div
      className="pointer-events-auto flex flex-col gap-[var(--map-ctrl-stack-gap)]"
      role="group"
      aria-label="走行条件"
    >
      <Popover>
        <PopoverTrigger asChild>
          <ConditionTrigger
            name={departureName}
            icon={<ClockIcon />}
            usage={`出発する日時を決めます。地図の気象の表示の時刻と、ルートの${timeAxes ? `${timeAxes}の評価・` : ""}到達予想の時刻に使います。`}
          >
            {/* 別の日は日付も付くため、列の幅に収まるよう日付と時刻を2行に分ける。 */}
            {departureLabel?.map((part) => (
              <span key={part} className="block">
                {part}
              </span>
            ))}
          </ConditionTrigger>
        </PopoverTrigger>
        <PopoverContent
          tone="bare"
          className="flex max-w-[var(--radix-popover-content-available-width)] flex-col items-end gap-1"
          side="bottom"
          align="end"
          collisionPadding={POPOVER_COLLISION_PADDING_PX}
        >
          <Input
            type="datetime-local"
            aria-label="出発日時を直接指定"
            data-usage="出発する日時を、日付と時刻で直に入れます。"
            value={toJstLocalValue(departureTime)}
            onChange={(e) => {
              const next = parseJstLocalValue(e.target.value);
              if (!Number.isNaN(next.getTime())) onDepartureTimeChange(next);
            }}
            className="h-8 tabular-nums"
          />
          <div
            className="contents"
            data-usage="目盛りをなぞって出発時刻を選びます。‹ › で1つずつ動かし、「現在」で今の時刻に合わせ続ける状態へ戻します。"
          >
            <DepartureRuler
              departureTime={departureTime}
              onDepartureTimeChange={onDepartureTimeChange}
              onDepartureNow={onDepartureNow}
            />
          </div>
        </PopoverContent>
      </Popover>

      <Popover>
        <PopoverTrigger asChild>
          <ConditionTrigger
            name={`想定速度: ${speedLabel}`}
            icon={<SpeedGaugeIcon />}
            usage="平地・無風で巡航する速さを決めます。所要時間と、区間ごとの到達予想の時刻に使います。"
          >
            {speedLabel}
          </ConditionTrigger>
        </PopoverTrigger>
        <PopoverContent
          className="flex flex-col gap-2 px-2 py-1.5"
          side="bottom"
          align="end"
          collisionPadding={POPOVER_COLLISION_PADDING_PX}
        >
          <div className="flex items-center gap-2" data-usage="平地・無風で巡航する速さを、つまみか数値で決めます。">
            <input
              type="range"
              aria-label="想定速度スライダー"
              min={MIN_SPEED_KMH}
              max={MAX_SPEED_KMH}
              step={1}
              value={speedKmh}
              onChange={(e) => onSpeedKmhChange(clampSpeedKmh(Number(e.target.value)))}
              className="h-6 min-w-32 flex-1"
            />
            <NumberInput
              commitOn="commit"
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
          <div className="flex items-center gap-1">
            <p className={textVariants({ variant: "hint" })}>平地・無風で巡航する速度</p>
            <InfoPopover triggerAriaLabel="想定速度の説明">
              {/* JSXの改行は半角スペースになるので、文字列として繋ぐ。 */}
              <p>
                {"普段の平均速度[信号待ち・坂を含む]ではなく、平らな道を風の無いときに巡航する速度です。" +
                  `所要時間は、この速度から平地で出している力を逆算し、区間ごとの${SPEED_CONDITIONS}で速度を変えて計算します。`}
              </p>
              {riderDefaults && (
                <p>
                  {`体格・機材は標準値で計算します: 総質量${riderDefaults.massKg}kg[体重＋車体＋装備]・` +
                    `空気抵抗CdA ${riderDefaults.cdaM2}m²[ロードバイクのブラケットポジション]。` +
                    `下りは${riderDefaults.maxDescentKmh}km/hまで[想定速度がそれより速いときは想定速度まで]、登りで${riderDefaults.walkingKmh}km/h以下になる所は押して歩くとみなします。`}
                </p>
              )}
            </InfoPopover>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
