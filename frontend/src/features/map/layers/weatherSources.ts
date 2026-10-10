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

/** 自前の格子を読む段を持つソースか。 */
export function readsGrid(source: WeatherSource): boolean {
  return source.stages.some((stage) => stage.origin === "grid");
}

/** 段のコマ。配信元の段は時刻一覧から読んだコマ、格子の段は格子の時刻の値
 * （描くときの格子はズーム依存の詳細格子になりうるため、コマを作った格子の点そのものは指さない。
 * `windLayer.ts: gridAtTime`）。 */
export type StageFrameRef = { stage: number; frame: JmaFrame } | { stage: number; time: string };

/** 配信元の段のコマを、共有タイムラインのコマにする。 */
export function jmaStageFrames(stage: number, frames: readonly JmaFrame[]): DynamicWeatherFrame<StageFrameRef>[] {
  return frames.map((frame) => ({ time: parseValidtime(frame.validtime), ref: { stage, frame } }));
}

/** 格子の段のコマ。1回の取得の時刻の列は全点で共通なので、先頭の点（最後に届いた応答の点）だけを見る。
 * 格子の時刻は日本時間の壁時計の値。`now`が属する1時間より前のコマは出さない（格子は取ってから時間が経つと先頭が
 * 過去になる）。「属する1時間」は最も近い時刻ではなく`now`以下で最も新しい時刻——最も近い時刻だと、正時を少し
 * 過ぎただけで今の1時間が消える。 */
export function gridStageFrames(
  stage: number,
  grid: readonly WindGridPoint[],
  now: Date,
): DynamicWeatherFrame<StageFrameRef>[] {
  const frames = (grid[0]?.times ?? []).map((time) => ({ time: parseJstLocalValue(time), ref: { stage, time } }));
  const current = frames.findLastIndex((frame) => frame.time.getTime() <= now.getTime());
  return frames.slice(Math.max(current, 0));
}

/** 段のコマを1本の時系列へつなぐ。各段は前の段の最後のコマより後の時刻だけを継ぐ——近い時刻は
 * 精度の高い前の段が持ち、二重に出さない。ある段が空（取れていない等）なら、次の段がその前の
 * 段の直後から継ぐ。backendのプリウォームも同じつなぎ方で段ごとに温めるフレームを選ぶ
 * （`domain/weather_elements.py: stage_first_frames`）。各段が最初に描くコマが同じになることは、backendが出す
 * 表（生成物`jma-expectations.json`）をテストが通して確かめる。 */
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
      ? observationIndexForTime(frames, at, rule.windowMinutes * MINUTE_MS)
      : frameIndexForTime(frames, at);
  return index === null ? undefined : frames[index];
}
