/**
 * `RouteForm/PointDetail.tsx`——押した地点の詳しく。探して置いた地点の辺りと、代表の位置にすぎないことを出す。地図で選んだ地点と
 * 辺りの無い施設には、位置から引いた辺りを出す（探した住所には引かない）。打つ欄は住所・施設の
 * 名前を入れて、地図の真ん中を添えて引き、候補（表示名・施設の辺り・種類・当たった段、施設は地図の真ん中からの直線距離）を欄の下に
 * 並べ、選んだ候補を上げる。打ちかけでも、決まった文字数から、打つのが止まると引く（かな漢字の変換中は引かない）。引いたあとに地図を
 * 動かしても引き直さない。引けないとき・当たらないときはそう出す。打つ欄を押すと保存した地点を出し、打った文字を名前に含むものに
 * 絞り、選んだ地点を上げる。置いた地点を名前を付けて保存し、保存した地点なら保存をやめられる。
 *
 * ここで見ないもの:
 * - 地点ごとの呼び名・出どころ・名前・地図で置く操作・消す・「現在地に戻す」・上限、候補を選んだあとに打った文字と一覧を消すこと →
 *   `RouteForm/RouteForm.test.tsx`
 * - 周回で経由地・目的地を選んだときのモードの切り替えと、置ける状態を解くこと → `features/route/useGenerationConditions.test.ts`
 * - 置いた地点へ地図を寄せること・地図の上でピンを動かすこと → `e2e/map-runtime.spec.ts`
 * - 打ちかけの語の続きの候補・施設の候補とその並びを返すこと、位置の辺りの決め方 → backend の `tests/test_place_search_route.py`
 * - 出発地・経由地・目的地のどの位置を渡すか（現在地を取れていない出発地は渡さない） → `RouteForm/RouteForm.test.tsx`
 *
 * - 保存した地点の一覧の読み方・同じ名前と位置の置き換え → `features/route/savedPlaces.test.ts`
 *
 * 差し替えたもの: 検索の口と辺りの口の応答（網の層）。保存した地点は本物の置き場（この端末の保存）を通す。
 */
import { fireEvent, screen, render, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SavedPlace } from "@/features/route/savedPlaces";
import { useSavedPlaces } from "@/features/route/useSavedPlaces";

import { onBackend } from "@/testing/backendServer";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { Coordinates, PlaceCandidate } from "@/types/route";

import PointDetail from "./PointDetail";

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

beforeEach(() => {
  window.localStorage.clear();
});

/** 前に保存した地点を、この端末の保存へ置く。 */
function storeSavedPlaces(places: SavedPlace[]) {
  window.localStorage.setItem("ridecompass:saved-places", JSON.stringify(places));
}

function WithSavedPlaces(props: Omit<React.ComponentProps<typeof PointDetail>, "savedPlaces">) {
  return <PointDetail {...props} savedPlaces={useSavedPlaces()} />;
}

function renderDetail({
  mapCenter = TOKYO_STATION,
  found = null as PlaceCandidate | null,
  at = null as Coordinates | null,
} = {}) {
  const onChoose = vi.fn();
  const detail = (center: Coordinates) => (
    <WithSavedPlaces
      role="destination"
      title="目的地"
      name={found?.name ?? "未設定"}
      found={found}
      at={at}
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
    ["住所", AZA, `${AZA.name}代表の位置`, true],
  ])("探して置いた%sは、名前に施設の辺りを添え、住所には代表の位置と出す", (_kind, found, text, representative) => {
    // 辺りの口へ問い合わせない（応答を与えていない要求はテストを落とす）。
    renderDetail({ found, at: { latitude: found.latitude, longitude: found.longitude } });

    const detail = screen.getByRole("region", { name: "目的地" });
    expect(detail.textContent).toContain(`目的地${text}`);
    expect(within(detail).queryByText("代表の位置") !== null).toBe(representative);
  });

  it.each([
    ["地図で選んだ地点", null, "目的地未設定"],
    ["辺りの無い施設", { ...FACILITY, area: null }, `目的地${FACILITY.name}`],
  ])("%sには、位置から引いた辺りを出す", async (_kind, found, head) => {
    const sent = onBackend("GET", "/api/place-area", () => Response.json({ area: "台東区浅草二丁目" }));
    renderDetail({ found, at: NEAR_SENSOJI });

    const detail = screen.getByRole("region", { name: "目的地" });
    expect(await within(detail).findByText("台東区浅草二丁目")).toBeDefined();
    expect(detail.textContent).toContain(`${head}台東区浅草二丁目`);
    expect(sent.map(({ query }) => query)).toEqual([sentCenter(NEAR_SENSOJI)]);
  });
});

describe("PointDetail 打つ欄", () => {
  it("入れた住所・施設の候補を種類と当たった段（施設は辺りと地図の真ん中からの距離も）つきで並べ、選んだ候補を上げる", async () => {
    const sent = onBackend("GET", "/api/place-search", () => Response.json({ candidates: [AZA, FACILITY] }));
    const { onChoose } = renderDetail();

    await searchFor(" 丸の内 ");

    const list = await screen.findByRole("list", { name: "地点の候補" });
    expect(sent.map((request) => request.query)).toEqual([{ q: "丸の内", ...sentCenter(TOKYO_STATION) }]);
    expect(
      within(list)
        .getAllByRole("button")
        .map((row) => row.textContent),
    ).toEqual([`${AZA.name}住所字・丁目`, `${FACILITY.name}${FACILITY.area}4.6km施設地点`]);

    await userEvent.click(within(list).getByRole("button", { name: new RegExp(AZA.name) }));
    expect(onChoose).toHaveBeenCalledExactlyOnceWith(AZA);
  });

  it("打ちかけでも、決まった文字数から、打つのが止まると引く", async () => {
    const sent = onBackend("GET", "/api/place-search", () => Response.json({ candidates: [AZA] }));
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
    const sent = onBackend("GET", "/api/place-search", () => Response.json({ candidates: [AZA] }));
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
      Response.json({ detail: "対象範囲を読めませんでした" }, { status: 502 }),
    );
    await searchFor("丸の内");
    expect(await screen.findByRole("alert")).toHaveTextContent("対象範囲を読めませんでした");
  });
});

describe("PointDetail 保存した地点", () => {
  const CAFE: SavedPlace = { ...FACILITY, name: "いつものカフェ" };
  const HOME: SavedPlace = { kind: "facility", level: "point", name: "自宅", area: null, ...NEAR_SENSOJI };

  it("打つ欄を押すと保存した地点を出し、打った文字を名前に含むものに絞り、選んだ地点を上げて一覧を閉じる", async () => {
    storeSavedPlaces([CAFE, HOME]);
    const { onChoose } = renderDetail();

    await userEvent.click(searchBox());
    const saved = () => screen.getByRole("list", { name: "保存した地点" });
    expect(
      within(saved())
        .getAllByRole("button")
        .map((row) => row.textContent),
    ).toEqual([`${CAFE.name}${CAFE.area}`, HOME.name]);

    await userEvent.type(searchBox(), "自");
    expect(within(saved()).getAllByRole("button")).toHaveLength(1);
    await userEvent.click(within(saved()).getByRole("button", { name: /自宅/ }));

    expect(onChoose).toHaveBeenCalledExactlyOnceWith(HOME);
    expect(screen.queryByRole("list", { name: "保存した地点" })).toBeNull();
    expect(searchBox()).toHaveValue("");
  });

  it("置いた地点は、探した候補の名前を入れた窓で名前を付けて保存し、保存した地点なら保存をやめられる", async () => {
    renderDetail({ found: FACILITY, at: { latitude: FACILITY.latitude, longitude: FACILITY.longitude } });

    await userEvent.click(screen.getByRole("button", { name: "地点を保存" }));
    const dialog = screen.getByRole("dialog", { name: "地点を保存" });
    const nameInput = within(dialog).getByRole("textbox", { name: "保存する地点の名前" });
    expect(nameInput).toHaveValue(FACILITY.name);
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, CAFE.name);
    await userEvent.click(within(dialog).getByRole("button", { name: "保存" }));

    await userEvent.click(searchBox());
    expect(within(screen.getByRole("list", { name: "保存した地点" })).getByRole("button")).toHaveTextContent(
      `${CAFE.name}${CAFE.area}`,
    );

    await userEvent.click(screen.getByRole("button", { name: `「${CAFE.name}」の保存をやめる` }));
    expect(screen.queryByRole("list", { name: "保存した地点" })).toBeNull();
    expect(screen.getByRole("button", { name: "地点を保存" })).toBeInTheDocument();
  });

  it("置いていない地点は保存できない", () => {
    renderDetail();

    expect(screen.queryByRole("button", { name: "地点を保存" })).toBeNull();
  });
});
