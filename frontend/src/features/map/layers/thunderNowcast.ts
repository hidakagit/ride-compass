// 気象庁 雷ナウキャスト・竜巻発生確度ナウキャストの時刻一覧と描画ペイロード。
//
// 降水と同じbosai/jmatile/data/nowc/系だが、雷・竜巻はtargetTimes_N3.json 1本に
// 実況〜60分先の予測が同居する（古いbasetimeの行はvalidtime===basetimeの実況のみ、
// 最新basetimeの行だけvalidtime>basetimeの予測が10分刻みで複数並ぶ）。
// 雷（thns）と竜巻（trns）は常に同じエントリへ同居するため、時刻一覧は雷の要素で絞った
// 1本を両方が共有する。
//
// 雷・竜巻は「回避一択」の危険のため評価軸には組み込まず、rasterTile表現（気象庁が
// 生成した画像をそのまま重ねる）のみを持つ警告表示として扱う。

import type { DynamicWeatherRenderPayload } from "@/features/map/layers/dynamicWeather";
import { fetchJmaNowcastFrames, jmaTilePayload, type JmaNowcastFrame } from "@/features/map/layers/jmaNowcastFrames";

/** 雷・竜巻共通の時刻一覧（雷ナウキャストのタイルがあるエントリだけ）。 */
export function fetchThunderNowcastFrames(): Promise<JmaNowcastFrame[]> {
  return fetchJmaNowcastFrames("disaster/thunder", "雷ナウキャスト");
}

export function thunderRenderPayload(frame: JmaNowcastFrame): DynamicWeatherRenderPayload {
  return jmaTilePayload("disaster/thunder", { basetime: frame.basetime, member: "none", validtime: frame.validtime });
}

export function tornadoRenderPayload(frame: JmaNowcastFrame): DynamicWeatherRenderPayload {
  return jmaTilePayload("disaster/tornado", { basetime: frame.basetime, member: "none", validtime: frame.validtime });
}
