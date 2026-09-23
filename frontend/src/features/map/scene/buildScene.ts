/** 地図に載るもの全部を、1つの scene へ組み立てる。
 *
 * ここが**唯一の組み立て口**。家族ごとに別の経路で地図を触らせないことで、重なり順・
 * 表示・絞り込みが1箇所で決まる（家族を1つ足すのは、下の並びへ1行足すこと）。
 *
 * 受け取るのは**実行時にしか決まらない値だけ**——タイルの配信先と世代・取得した中身・
 * 表示ON/OFF・凡例で隠した行・実行時に増える軸。見た目の値は各グループが持つ。
 */
import type { MapScene } from "./mapScene";
import { composeScene, type SceneGroup } from "./mapSceneGroups";
import { areaRasterGroup, type AreaRasterState } from "@/features/map/scene/groups/areaRasters";
import { axisLineGroup, type AxisLineState } from "@/features/map/scene/groups/axisLines";
import { pointGroup, type PointState } from "@/features/map/scene/groups/points";
import { roadLineGroup, type RoadLineState } from "@/features/map/scene/groups/roadLines";
import { routeGroup, type RouteState } from "@/features/map/scene/groups/routes";
import { weatherGroup, type WeatherState } from "@/features/map/scene/groups/weather";

export type SceneInputs = {
  readonly area: AreaRasterState;
  readonly road: RoadLineState;
  readonly axis: AxisLineState;
  readonly point: PointState;
  readonly weather: WeatherState;
  readonly route: RouteState;
};

/** 家族ごとの状態を、全体の状態から選んで渡す。 */
function selecting<Part>(group: SceneGroup<Part>, select: (inputs: SceneInputs) => Part): SceneGroup<SceneInputs> {
  return { build: (inputs) => group.build(select(inputs)) };
}

const GROUPS: readonly SceneGroup<SceneInputs>[] = [
  selecting(areaRasterGroup, (inputs) => inputs.area),
  selecting(roadLineGroup, (inputs) => inputs.road),
  selecting(axisLineGroup, (inputs) => inputs.axis),
  selecting(pointGroup, (inputs) => inputs.point),
  selecting(weatherGroup, (inputs) => inputs.weather),
  selecting(routeGroup, (inputs) => inputs.route),
];

export function buildMapScene(inputs: SceneInputs): MapScene {
  return composeScene(GROUPS, inputs);
}
