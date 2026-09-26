// 動的気象の名前付きソースと、その時系列。何を・どこから・どう読み・選んだ時刻にどのコマを描くかは
// 源泉の宣言（`mapDisplay.weatherElements`、backendの`domain/weather_elements.py`）が持ち、ここは
// 宣言をソースごとに束ねて、段をつなぎ、規則に従ってコマを選ぶ。要素を名指さない——源泉へ要素を
// 1件足せば、ここを変えずにソースが1つ増える。

import { mapDisplay } from "@/types/generated/mapDisplay";
import {
  frameIndexForTime,
  isWithinFutureWindow,
  observationIndexForTime,
  type DynamicWeatherFrame,
  type DynamicWeatherLayerId,
} from "@/features/map/layers/dynamicWeather";
import { parseValidtime, type JmaDelivery, type JmaFrame } from "@/features/map/layers/jmaDelivery";
import { parseJstLocalValue } from "@/lib/time";
import type { WindGridPoint } from "@/types/weather";

type DeclaredElement = (typeof mapDisplay.weatherElements)[number];

/** 選んだ時刻に対して描くコマの規則（源泉の宣言）。 */
export type FrameRule = DeclaredElement["frameRule"];

/** 自前のMSM格子から描く段が読む値。 */
export type GridValue = NonNullable<DeclaredElement["gridValue"]>;

/** 時刻の段1つ。配信元から取る段と、自前の格子から描く段がある。 */
type WeatherStage =
  | { origin: "jma"; kind: DeclaredElement["kind"]; delivery: JmaDelivery }
  | { origin: "grid"; kind: DeclaredElement["kind"]; value: GridValue };

/** 名前付きソース1つ。同じ名前を名乗る要素の段を、宣言の順（近い時刻から）に持つ。 */
export interface WeatherSource {
  group: DynamicWeatherLayerId;
  source: string;
  label: string;
  frameRule: FrameRule;
  stages: readonly WeatherStage[];
}

function stagesOf(element: DeclaredElement): WeatherStage[] {
  if (element.jmaElements.length > 0) {
    return element.jmaElements.map((delivery) => ({ origin: "jma", kind: element.kind, delivery }));
  }
  // 配信元から取らない要素は必ず読む格子の値を持つ（backendのtest_map_display.pyが全要素で確かめる）。
  return [{ origin: "grid", kind: element.kind, value: element.gridValue! }];
}

function buildWeatherSources(): readonly WeatherSource[] {
  const sources = new Map<string, WeatherSource & { stages: WeatherStage[] }>();
  for (const element of mapDisplay.weatherElements) {
    const key = `${element.group}/${element.source}`;
    const existing = sources.get(key);
    if (existing) {
      existing.stages.push(...stagesOf(element));
      continue;
    }
    sources.set(key, {
      group: element.group,
      source: element.source,
      label: element.label,
      frameRule: element.frameRule,
      stages: stagesOf(element),
    });
  }
  return [...sources.values()];
}

/** 名前付きソースの一覧（源泉の宣言の順）。 */
export const WEATHER_SOURCES: readonly WeatherSource[] = buildWeatherSources();

/** 段のコマ。配信元の段は時刻一覧から読んだコマ、格子の段は格子の時刻の位置
 * （描くときの格子はズーム依存の詳細格子になりうるため、コマを作った格子の点そのものは指さない）。 */
export type StageFrameRef = { stage: number; frame: JmaFrame } | { stage: number; index: number };

/** 配信元の段のコマを、共有タイムラインのコマにする。 */
export function jmaStageFrames(stage: number, frames: readonly JmaFrame[]): DynamicWeatherFrame<StageFrameRef>[] {
  return frames.map((frame) => ({ time: parseValidtime(frame.validtime), ref: { stage, frame } }));
}

/** 格子の段のコマ。全格子点で時刻配列が共通（1回のMSMの読み出しで全点を取る）なので先頭の点だけを見る。
 * 格子の時刻は日本時間の壁時計の値。 */
export function gridStageFrames(stage: number, grid: readonly WindGridPoint[]): DynamicWeatherFrame<StageFrameRef>[] {
  return (grid[0]?.times ?? []).map((time, index) => ({ time: parseJstLocalValue(time), ref: { stage, index } }));
}

/** 段のコマを1本の時系列へつなぐ。各段は前の段の最後のコマより後の時刻だけを継ぐ——近い時刻は
 * 精度の高い前の段が持ち、二重に出さない。ある段が空（取れていない等）なら、次の段がその前の
 * 段の直後から継ぐ。backendのプリウォームも同じつなぎ方で段ごとに温めるフレームを選ぶ
 * （`domain/weather_elements.py: stage_first_frames`）。 */
export function sourceTimeline(
  stages: readonly (readonly DynamicWeatherFrame<StageFrameRef>[])[],
): DynamicWeatherFrame<StageFrameRef>[] {
  const timeline: DynamicWeatherFrame<StageFrameRef>[] = [];
  let lastMs = -Infinity;
  for (const frames of stages) {
    let stageLastMs = lastMs;
    for (const frame of frames) {
      const ms = frame.time.getTime();
      if (ms <= lastMs) continue;
      timeline.push(frame);
      stageLastMs = Math.max(stageLastMs, ms);
    }
    lastMs = stageLastMs;
  }
  return timeline;
}

const MINUTE_MS = 60 * 1000;

/** 選んだ時刻`at`に描くコマ。描かないならundefined。 */
export function selectFrame<T>(
  rule: FrameRule,
  frames: readonly DynamicWeatherFrame<T>[],
  at: Date,
  now: Date,
): DynamicWeatherFrame<T> | undefined {
  if (rule.kind === "current") {
    if (rule.windowMinutes !== null && !isWithinFutureWindow(at, now, rule.windowMinutes * MINUTE_MS)) return undefined;
    return frames[0];
  }
  const index =
    rule.kind === "latestObservation"
      ? observationIndexForTime(frames, at, (rule.windowMinutes ?? 0) * MINUTE_MS)
      : frameIndexForTime(frames, at);
  return index === null ? undefined : frames[index];
}
