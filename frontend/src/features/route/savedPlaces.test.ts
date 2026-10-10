// @vitest-environment node
/**
 * `features/route/savedPlaces.ts`——保存した地点の一覧を読む・一覧への入れ方・打った文字での絞り込み。読むときは、今の画面が
 * 受け付けない件だけを捨ててほかの件を残す。同じ名前か同じ位置で保存すると置き換える。
 *
 * ここで見ないもの:
 * - 一覧をどこに出し、選ぶと何が起きるか → `RouteForm/PointDetail.test.tsx`
 */
import { describe, expect, it } from "vitest";

import { readSavedPlaces, savedPlacesMatching, withSavedPlace, type SavedPlace } from "./savedPlaces";

const CAFE: SavedPlace = {
  kind: "facility",
  level: "point",
  name: "いつものカフェ",
  area: "文京区本駒込二丁目",
  latitude: 35.73,
  longitude: 139.75,
};
const HOME: SavedPlace = {
  kind: "facility",
  level: "point",
  name: "自宅",
  area: null,
  latitude: 35.75,
  longitude: 139.73,
};
// 番地まで当たった住所。
const OFFICE: SavedPlace = {
  kind: "address",
  level: "block",
  name: "東京都文京区本郷七丁目3番",
  area: null,
  latitude: 35.71,
  longitude: 139.76,
};

describe("readSavedPlaces", () => {
  it("今の画面が受け付けない件だけを捨て、ほかの件は残す", () => {
    const raw = JSON.stringify([
      CAFE,
      { ...HOME, name: " " },
      { ...HOME, kind: "station" },
      { ...HOME, level: "building" },
      { ...HOME, latitude: "35.75" },
      { ...HOME, area: 1 },
      null,
      HOME,
      OFFICE,
    ]);

    expect(readSavedPlaces(raw)).toEqual([CAFE, HOME, OFFICE]);
  });

  it.each([
    ["壊れた値", "{"],
    ["一覧でない値", JSON.stringify(CAFE)],
  ])("%sは空の一覧", (_kind, raw) => {
    expect(readSavedPlaces(raw)).toEqual([]);
  });
});

describe("withSavedPlace", () => {
  it("入れた件を先頭に置き、同じ名前・同じ位置の件を置き換える", () => {
    const renamed = { ...CAFE, name: "カフェ" };
    const moved = { ...HOME, latitude: 35.76 };

    expect(withSavedPlace([CAFE, HOME], renamed)).toEqual([renamed, HOME]);
    expect(withSavedPlace([CAFE, HOME], moved)).toEqual([moved, CAFE]);
  });
});

describe("savedPlacesMatching", () => {
  it("打った文字を名前に含むものだけを、前後の空白と大文字・小文字を問わずに残す。空なら全部", () => {
    const shop = { ...CAFE, name: "Bike Shop" };

    expect(savedPlacesMatching([CAFE, HOME, shop], " shop ")).toEqual([shop]);
    expect(savedPlacesMatching([CAFE, HOME, shop], "")).toEqual([CAFE, HOME, shop]);
  });
});
