// @vitest-environment node
/**
 * `testing/mapTrace/recordingMap.ts`——地図の代役。本物の `maplibre-gl` へも流す同じ呼び出し（`recordingMap.contract.ts`。
 * 本物の側は `e2e/recording-map.spec.ts`）を代役へ流し、地図に載っているものが本物と同じ期待値になることを見る。
 * 代役が本物とずれると、頼る scene のテストは本物では起きない地図の上で緑になる。
 *
 * ここで見ないもの:
 * - 呼び出しの記録（`trace`）とスタイルの差し替え（代役にだけある観測点。使う側の scene のテストが読む）
 * - 本物が地物の状態の変更を次の描画でまとめて確定すること（代役は描画を持たず、呼ぶたびに確定する。本物では、
 *   同じ描画の間に地物を名指しせずに消したあと状態を置くと、まだ確定していない状態は消えずに残る）
 */
import { describe, expect, it } from "vitest";

import { MAP_CONTRACT, type MapReading } from "./recordingMap.contract";
import { createRecordingMap } from "./recordingMap";

type Callable = Record<string, (...args: readonly unknown[]) => unknown>;

describe("地図の代役は、本物と同じ呼び出しで同じものを載せる", () => {
  it.each(MAP_CONTRACT)("$name", ({ steps, expected }) => {
    const { map, handle } = createRecordingMap();
    for (const { call, args, source } of steps) {
      const target = (source === undefined ? map : map.getSource(source)) as unknown as Callable;
      target[call](...args);
    }

    const reading: MapReading = {
      layers: handle.layerOrder().map((id) => {
        const layer = handle.layer(id)!;
        const names = Object.keys(expected.layers.find((l) => l.id === id)?.paint ?? {});
        return {
          id,
          visibility: layer.visibility,
          paint: Object.fromEntries(names.map((name) => [name, layer.paint[name]])),
          filter: layer.filter,
        };
      }),
      featureStates: expected.featureStates.map((entry) => ({
        ...entry,
        state: { ...handle.featureState(entry.source, String(entry.id)) },
      })),
      sourceData: expected.sourceData.map(({ source }) => ({ source, data: handle.sourceContent(source)?.data })),
    };

    expect(reading).toEqual(expected);
  });
});
