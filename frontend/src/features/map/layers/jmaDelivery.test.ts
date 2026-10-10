// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import jmaExpectations from "@/types/generated/jma-expectations.json";
import { mapDisplay } from "@/types/generated/mapDisplay";

import {
  fetchJmaGeojson,
  fetchJmaTargetTimesFile,
  isJmaTileKind,
  jmaFramesOf,
  JMA_POINT_VALUE_PROPERTY,
  jmaPlaceholderTileUrl,
  jmaTilePayload,
  parseValidtime,
  readJmaTileUrl,
  type JmaDelivery,
} from "./jmaDelivery";

// 配信のオリジンは`@/lib/tileBaseUrl`が決める（`src/lib/tileBaseUrl.test.ts`）。ここでは固定する。
vi.mock("@/lib/tileBaseUrl", () => ({ tileBaseUrl: () => "https://tiles.test" }));
const PROXY = "https://tiles.test/api/jma-tile/";
const DELIVERIES = mapDisplay.weatherElements.flatMap((element): readonly JmaDelivery[] => element.jmaElements);
const isTileElement = (element: (typeof mapDisplay.weatherElements)[number]) =>
  isJmaTileKind(element.kind) && element.jmaElements.length > 0;
const TILE_ELEMENTS = mapDisplay.weatherElements.filter(isTileElement);
const TILE_DELIVERIES = TILE_ELEMENTS.flatMap((element): readonly JmaDelivery[] => element.jmaElements);
const FEATURE_ELEMENT = mapDisplay.weatherElements.find(
  (element) => !isTileElement(element) && element.jmaElements.length > 0,
)!;
const FEATURE_DELIVERY: JmaDelivery = FEATURE_ELEMENT.jmaElements[0]!;
const fileOf = (delivery: JmaDelivery, index = 0) => `${PROXY}${delivery.targetTimesPaths[index]}`;
/** 地図ライブラリがタイル座標を埋めたURL。 */
const tileAt = (template: string, z: number, x: number, y: number) =>
  template.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));

/** 時刻一覧のファイルごとの応答。`undefined`のファイルは500を返す。 */
function stubFiles(files: Record<string, unknown>) {
  const fetchMock = vi.fn(async (request: Request) => {
    const body = files[request.url];
    return body === undefined ? new Response(null, { status: 500 }) : Response.json(body);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const row = (basetime: string, validtime: string, elements: string[], member?: string) => ({
  basetime,
  validtime,
  elements,
  ...(member === undefined ? {} : { member }),
});

describe("時刻一覧の読み方", () => {
  // 配信の遅れのずらしは画面だけが持つ（下の「配信の遅れ」）ので、遅れの無い配信要素で当てる。
  it("backendの表（読み方ごとの、別の要素の行が混ざる・実況が無い・中間ランの単発の行等）と同じコマ", () => {
    const rows = jmaExpectations.read_target_times;
    expect(rows.length).toBeGreaterThan(0);
    for (const { scene, reader, element_id, rows: listing, frames } of rows) {
      const delivery = { ...DELIVERIES[0]!, id: element_id, reader, dataDelayMinutes: 0 } as JmaDelivery;
      expect(jmaFramesOf(delivery, listing), `${reader}: ${scene}`).toEqual(frames);
    }
  });
});

describe("配信の遅れ", () => {
  const withDelay = (minutes: number) =>
    ({ ...DELIVERIES.find((each) => each.dataDelayMinutes > 0)!, dataDelayMinutes: minutes }) as JmaDelivery;
  const delivery = withDelay(10);
  const read = (entries: ReturnType<typeof row>[]) => jmaFramesOf(delivery, entries);
  // 時刻一覧は最新の0:10の実況と20分先までを載せ、前のbasetimeは実況の行だけを残す。
  const rows = [
    row("20260924000000", "20260924000000", [delivery.id]),
    row("20260924001000", "20260924001000", [delivery.id]),
    row("20260924001000", "20260924002000", [delivery.id]),
    row("20260924001000", "20260924003000", [delivery.id]),
    row("20260924001500", "20260924001500", ["other"]), // 別の要素の行は最新を決めない
  ];

  it("最新のbasetimeのコマを遅れの幅だけ前のbasetimeで読み、実況はずらした先の実況にする", () => {
    expect(read(rows)).toEqual([
      { basetime: "20260924000000", member: "none", validtime: "20260924000000" },
      { basetime: "20260924000000", member: "none", validtime: "20260924002000" },
      { basetime: "20260924000000", member: "none", validtime: "20260924003000" },
    ]);
  });
});

describe("時刻一覧のファイル", () => {
  it("配列でない応答は形式の誤りとして失敗に数える", async () => {
    const delivery = DELIVERIES[0];
    stubFiles({ [fileOf(delivery)]: {} });
    await expect(fetchJmaTargetTimesFile(delivery.targetTimesPaths[0], "要素")).rejects.toThrow(
      "要素の時刻一覧の形式が想定と異なります",
    );
  });
});

describe("コマのURL", () => {
  const frame = { basetime: "20260924000000", member: "immed", validtime: "20260924010000" };
  const delivery = FEATURE_DELIVERY;

  it("タイルのURLはbackendの表のパスを指し、同じ配信要素・コマ・タイル座標に読み戻せる", () => {
    const rows = jmaExpectations.tile_path;
    expect(rows.length).toBeGreaterThan(0);
    for (const { element_id, frame: tileFrame, z, x, y, path } of rows) {
      const tile = TILE_DELIVERIES.find((delivery) => delivery.id === element_id);
      if (tile === undefined) throw new Error(`タイルで描く配信要素に${element_id}が無い`);
      const { tileUrlTemplate } = jmaTilePayload("rasterTile", tile, tileFrame);
      const url = tileAt(tileUrlTemplate, z, x, y);
      expect(url).toBe(`${PROXY}${path}`);
      expect(readJmaTileUrl(url), element_id).toEqual({
        delivery: tile,
        frame: tileFrame,
        frameUrl: tileUrlTemplate,
        z,
        x,
        y,
      });
    }
  });

  it("源泉のテンプレートに当たらないURLは読み戻さない", () => {
    expect(readJmaTileUrl("https://example.com/tile/5/28/12.png")).toBeNull();
    expect(readJmaTileUrl(jmaPlaceholderTileUrl(FEATURE_ELEMENT))).toBeNull(); // タイルで描かない要素の地物
  });

  it("中身が届く前の仮のURLは、タイルで描く要素の最初の段の実在しない時刻を指す", () => {
    const element = TILE_ELEMENTS.find((each) => each.jmaElements.length > 1)!;
    const ref = readJmaTileUrl(tileAt(jmaPlaceholderTileUrl(element), 4, 14, 6));
    expect(ref?.delivery).toBe(element.jmaElements[0]);
    expect(ref?.frame).toEqual({ basetime: "00000000000000", member: "none", validtime: "00000000000000" });
  });

  it("地物はそのコマの要素配下のGeoJSONを取り、どの地物にも記号の大きさを決める値を足す（元の属性は残す）", async () => {
    const url = `${PROXY}${delivery.urlTemplate}`
      .replace("{basetime}", frame.basetime)
      .replace("{member}", frame.member)
      .replace("{validtime}", frame.validtime);
    stubFiles({
      [url]: {
        type: "FeatureCollection",
        features: [
          { type: "Feature", geometry: { type: "Point", coordinates: [139, 35] }, properties: { type: 1 } },
          { type: "Feature", geometry: { type: "Point", coordinates: [140, 36] }, properties: null },
        ],
      },
    });

    const geojson = await fetchJmaGeojson(delivery, frame, "地点");
    expect(geojson.features.map((feature) => feature.properties)).toEqual([
      { type: 1, [JMA_POINT_VALUE_PROPERTY]: 1 },
      { [JMA_POINT_VALUE_PROPERTY]: 1 },
    ]);
  });
});

describe("コマの時刻", () => {
  it("validtimeは協定世界時の YYYYMMDDHHmmss", () => {
    expect(parseValidtime("20260923153000").toISOString()).toBe("2026-09-23T15:30:00.000Z");
  });
});
