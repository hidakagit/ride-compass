/**
 * `RouteForm/PointDetail.tsx`——押した地点の詳しく。探して置いた地点の辺りと、代表の位置にすぎないことを出す。打つ欄は住所・施設の
 * 名前を入れて、地図の真ん中を添えて引き、候補（表示名・施設の辺り・種類・当たった段、施設は地図の真ん中からの直線距離）を欄の下に
 * 並べ、選んだ候補を上げる。打ちかけでも、決まった文字数から、打つのが止まると引く（かな漢字の変換中は引かない）。引いたあとに地図を
 * 動かしても引き直さない。引けないとき・当たらないときはそう出す。
 *
 * ここで見ないもの:
 * - 地点ごとの呼び名・出どころ・名前・地図で置く操作・消す・「現在地に戻す」・上限、候補を選んだあとに打った文字と一覧を消すこと →
 *   `RouteForm/RouteForm.test.tsx`
 * - 周回で経由地・目的地を選んだときのモードの切り替えと、置ける状態を解くこと → `features/route/useGenerationConditions.test.ts`
 * - 置いた地点へ地図を寄せること・地図の上でピンを動かすこと → `e2e/map-runtime.spec.ts`
 * - 打ちかけの語の続きの候補・施設の候補とその並びを返すこと → backend の `tests/test_place_search_route.py`
 *
 * 差し替えたもの: 検索の口の応答（網の層）。
 */
import { fireEvent, screen, render, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { onBackend } from "@/testing/backendServer";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { Coordinates, PlaceCandidate } from "@/types/route";

import PointDetail from "./PointDetail";

const BLOCK: PlaceCandidate = {
  kind: "address",
  level: "block",
  name: "東京都千代田区丸の内一丁目9番",
  area: null,
  latitude: 35.681,
  longitude: 139.767,
};
const AZA: PlaceCandidate = {
  kind: "address",
  level: "aza",
  name: "東京都千代田区丸の内二丁目",
  area: null,
  latitude: 35.679,
  longitude: 139.764,
};
const FACILITY: PlaceCandidate = {
  kind: "facility",
  level: "point",
  name: "浅草寺",
  area: "台東区浅草二丁目",
  latitude: 35.7148,
  longitude: 139.7967,
};

/** 地図の真ん中（東京駅）。浅草寺まで直線で4.6km。 */
const TOKYO_STATION: Coordinates = { latitude: 35.681, longitude: 139.767 };
/** 浅草寺のすぐ南（浅草寺まで直線で0.2km）。 */
const NEAR_SENSOJI: Coordinates = { latitude: 35.713, longitude: 139.7967 };

function renderDetail({ mapCenter = TOKYO_STATION, found = null as PlaceCandidate | null } = {}) {
  const onChoose = vi.fn();
  const detail = (center: Coordinates) => (
    <PointDetail
      role="destination"
      title="目的地"
      name={found?.name ?? "未設定"}
      found={found}
      placed={found !== null}
      armLabel="地図で選ぶ"
      usage=""
      chooseResult=""
      armed={false}
      onArmToggle={() => {}}
      originLocated
      mapCenter={center}
      onChoose={onChoose}
    />
  );
  const { rerender } = render(detail(mapCenter));
  return { onChoose, moveMap: (center: Coordinates) => rerender(detail(center)) };
}

function searchBox() {
  return screen.getByRole("searchbox", { name: "目的地を住所・施設で探す" });
}

/** 引いたときに送った地図の真ん中（クエリの値）。 */
function sentCenter(center: Coordinates) {
  return { latitude: String(center.latitude), longitude: String(center.longitude) };
}

/** 打つのが止まってから引くまでの間を、引かないことを確かめられるだけ待つ。 */
function waitPastLookUpDelay() {
  return new Promise((resolve) => setTimeout(resolve, routeGenerateConfig.place_prediction_delay_seconds * 1000 + 100));
}

async function searchFor(text: string) {
  await userEvent.clear(searchBox());
  await userEvent.type(searchBox(), `${text}{Enter}`);
}

describe("PointDetail 置いた地点", () => {
  it.each([
    ["施設", FACILITY, `${FACILITY.name}${FACILITY.area}`, false],
    ["字・丁目で当たった住所", AZA, `${AZA.name}代表の位置`, true],
    ["街区で当たった住所", BLOCK, BLOCK.name, false],
  ])(
    "探して置いた%sは、名前に施設の辺りを添え、街区より粗い段で当たった住所には代表の位置と出す",
    (_kind, found, text, representative) => {
      renderDetail({ found });

      const detail = screen.getByRole("region", { name: "目的地" });
      expect(detail.textContent).toContain(`目的地${text}`);
      expect(within(detail).queryByText("代表の位置") !== null).toBe(representative);
    },
  );
});

describe("PointDetail 打つ欄", () => {
  it("入れた住所・施設の候補を種類と当たった段（施設は辺りと地図の真ん中からの距離も）つきで並べ、選んだ候補を上げる", async () => {
    const sent = onBackend("GET", "/api/place-search", () => Response.json({ candidates: [BLOCK, AZA, FACILITY] }));
    const { onChoose } = renderDetail();

    await searchFor(" 丸の内 ");

    const list = await screen.findByRole("list", { name: "地点の候補" });
    expect(sent.map((request) => request.query)).toEqual([{ q: "丸の内", ...sentCenter(TOKYO_STATION) }]);
    expect(
      within(list)
        .getAllByRole("button")
        .map((row) => row.textContent),
    ).toEqual([
      `${BLOCK.name}住所街区・地番`,
      `${AZA.name}住所字・丁目`,
      `${FACILITY.name}${FACILITY.area}4.6km施設地点`,
    ]);

    await userEvent.click(within(list).getByRole("button", { name: new RegExp(AZA.name) }));
    expect(onChoose).toHaveBeenCalledExactlyOnceWith(AZA);
  });

  it("打ちかけでも、決まった文字数から、打つのが止まると引く", async () => {
    const sent = onBackend("GET", "/api/place-search", () => Response.json({ candidates: [BLOCK] }));
    renderDetail();
    const enough = "千代田区丸の内".slice(0, routeGenerateConfig.place_prediction_min_length);

    // 空白は数えない。
    await userEvent.type(searchBox(), ` ${enough.slice(0, -1)}`);
    await waitPastLookUpDelay();
    expect(sent).toEqual([]);

    await userEvent.type(searchBox(), enough.slice(-1));
    await screen.findByRole("list", { name: "地点の候補" });
    expect(sent.map((request) => request.query)).toEqual([{ q: enough, ...sentCenter(TOKYO_STATION) }]);
  });

  it("かな漢字の変換中は引かず、確定してから引く", async () => {
    const sent = onBackend("GET", "/api/place-search", () => Response.json({ candidates: [BLOCK] }));
    renderDetail();
    const box = searchBox();

    fireEvent.compositionStart(box);
    fireEvent.input(box, { target: { value: "まるのうち" }, isComposing: true });
    await waitPastLookUpDelay();
    expect(sent).toEqual([]);

    fireEvent.input(box, { target: { value: "丸の内" }, isComposing: true });
    fireEvent.compositionEnd(box);
    await screen.findByRole("list", { name: "地点の候補" });
    expect(sent.map((request) => request.query)).toEqual([{ q: "丸の内", ...sentCenter(TOKYO_STATION) }]);
  });

  it("引いたときの地図の真ん中から並べて距離を出し、引いたあとに地図を動かしても引き直さない", async () => {
    const sent = onBackend("GET", "/api/place-search", () => Response.json({ candidates: [FACILITY] }));
    const { moveMap } = renderDetail();

    moveMap(NEAR_SENSOJI);
    await searchFor("浅草寺");
    const list = await screen.findByRole("list", { name: "地点の候補" });

    moveMap(TOKYO_STATION);
    await waitPastLookUpDelay();
    expect(sent.map((request) => request.query)).toEqual([{ q: "浅草寺", ...sentCenter(NEAR_SENSOJI) }]);
    expect(within(list).getByRole("button")).toHaveTextContent(`${FACILITY.name}${FACILITY.area}0.2km`);
  });

  it("当たらなければそう出し、検索が使えなければ口の文を出す", async () => {
    onBackend("GET", "/api/place-search", () => Response.json({ candidates: [] }));
    renderDetail();

    await searchFor("どこにもない");
    expect(await screen.findByRole("status")).toHaveTextContent("当たる住所・施設がありません。");

    onBackend("GET", "/api/place-search", () =>
      Response.json({ detail: "住所の検索は今は使えません" }, { status: 503 }),
    );
    await searchFor("丸の内");
    expect(await screen.findByRole("alert")).toHaveTextContent("住所の検索は今は使えません");
  });
});
