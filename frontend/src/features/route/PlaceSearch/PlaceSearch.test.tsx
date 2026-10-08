/**
 * `PlaceSearch/PlaceSearch.tsx`——住所を入れて引き、候補（表示名・種類・当たった段）を並べ、選んだ候補を目的地・出発地・
 * 経由地のどれかとして置く。打ちかけでも、決まった文字数から、打つのが止まると引く（かな漢字の変換中は引かない）。置いたあとは、当たった段が粗ければピンを直すように出す。引けないとき・当たらないときはそう出す。
 * 経由地が上限なら経由地には置けない。地図に重ねて出す一覧と案内は閉じられる。
 *
 * ここで見ないもの:
 * - 周回で経由地・目的地を選んだときのモードの切り替えと、置ける状態を解くこと → `features/route/useGenerationConditions.test.ts`
 * - 置いた地点へ地図を寄せること・地図の上でピンを動かすこと → `e2e/map-runtime.spec.ts`
 * - 打ちかけの語の続きの候補を返すこと → backend の `tests/test_place_search_route.py`
 *
 * 差し替えたもの: 検索の口の応答（網の層）。
 */
import { fireEvent, screen, render, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { onBackend } from "@/testing/backendServer";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { PlaceCandidate } from "@/types/route";

import PlaceSearch from "./PlaceSearch";

const BLOCK: PlaceCandidate = {
  kind: "address",
  level: "block",
  name: "東京都千代田区丸の内一丁目9番",
  latitude: 35.681,
  longitude: 139.767,
};
const AZA: PlaceCandidate = {
  kind: "address",
  level: "aza",
  name: "東京都千代田区丸の内二丁目",
  latitude: 35.679,
  longitude: 139.764,
};

function renderSearch({ waypointsFull = false } = {}) {
  const onPlace = vi.fn();
  render(<PlaceSearch onPlace={onPlace} waypointsFull={waypointsFull} />);
  return { onPlace };
}

/** 打つのが止まってから引くまでの間を、引かないことを確かめられるだけ待つ。 */
function waitPastLookUpDelay() {
  return new Promise((resolve) => setTimeout(resolve, routeGenerateConfig.place_prediction_delay_seconds * 1000 + 100));
}

async function searchFor(text: string) {
  await userEvent.type(screen.getByRole("searchbox", { name: "住所で探す" }), `${text}{Enter}`);
}

describe("PlaceSearch", () => {
  it("入れた住所の候補を種類と当たった段つきで並べ、選んだ役割の地点として置き、段が粗ければピンを直すように出す", async () => {
    const sent = onBackend("GET", "/api/place-search", () => Response.json({ candidates: [BLOCK, AZA] }));
    const { onPlace } = renderSearch();

    await searchFor(" 丸の内 ");

    const list = await screen.findByRole("list", { name: "住所の候補" });
    expect(sent.map((request) => request.query)).toEqual([{ q: "丸の内" }]);
    expect(
      within(list)
        .getAllByRole("button")
        .map((row) => row.textContent),
    ).toEqual([`${BLOCK.name}住所街区・地番`, `${AZA.name}住所字・丁目`]);

    await userEvent.click(within(list).getByRole("button", { name: new RegExp(AZA.name) }));
    await userEvent.click(screen.getByRole("button", { name: "目的地へ" }));

    expect(onPlace).toHaveBeenCalledExactlyOnceWith("destination", {
      latitude: AZA.latitude,
      longitude: AZA.longitude,
    });
    expect(screen.queryByRole("list", { name: "住所の候補" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent(
      `「${AZA.name}」を目的地にしました。当たったのは「字・丁目」までなので、ピンはその範囲の代表の位置です。`,
    );

    // 街区まで当たった地点は、直せることだけを出す。
    await searchFor("1-9");
    await userEvent.click(await screen.findByRole("button", { name: new RegExp(BLOCK.name) }));
    await userEvent.click(screen.getByRole("button", { name: "経由地へ" }));

    expect(onPlace).toHaveBeenLastCalledWith("waypoint", { latitude: BLOCK.latitude, longitude: BLOCK.longitude });
    expect(screen.getByRole("status")).toHaveTextContent(
      `「${BLOCK.name}」を経由地に足しました。地図のピンをつかんで動かすと直せます。`,
    );

    // 案内は地図に重なるので、閉じて地図を空けられる。
    await userEvent.click(screen.getByRole("button", { name: "検索の結果を閉じる" }));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("打ちかけでも、決まった文字数から、打つのが止まると引く", async () => {
    const sent = onBackend("GET", "/api/place-search", () => Response.json({ candidates: [BLOCK] }));
    renderSearch();
    const box = screen.getByRole("searchbox", { name: "住所で探す" });
    const enough = "千代田区丸の内".slice(0, routeGenerateConfig.place_prediction_min_length);

    await userEvent.type(box, enough.slice(0, -1));
    await waitPastLookUpDelay();
    expect(sent).toEqual([]);

    await userEvent.type(box, enough.slice(-1));
    await screen.findByRole("list", { name: "住所の候補" });
    expect(sent.map((request) => request.query)).toEqual([{ q: enough }]);
  });

  it("かな漢字の変換中は引かず、確定してから引く", async () => {
    const sent = onBackend("GET", "/api/place-search", () => Response.json({ candidates: [BLOCK] }));
    renderSearch();
    const box = screen.getByRole("searchbox", { name: "住所で探す" });

    fireEvent.compositionStart(box);
    fireEvent.input(box, { target: { value: "まるのうち" }, isComposing: true });
    await waitPastLookUpDelay();
    expect(sent).toEqual([]);

    fireEvent.input(box, { target: { value: "丸の内" }, isComposing: true });
    fireEvent.compositionEnd(box);
    await screen.findByRole("list", { name: "住所の候補" });
    expect(sent.map((request) => request.query)).toEqual([{ q: "丸の内" }]);
  });

  it("経由地が上限なら経由地には置けず、ほかの役割には置ける", async () => {
    onBackend("GET", "/api/place-search", () => Response.json({ candidates: [BLOCK] }));
    const { onPlace } = renderSearch({ waypointsFull: true });

    await searchFor("丸の内");
    await userEvent.click(await screen.findByRole("button", { name: new RegExp(BLOCK.name) }));

    expect(screen.getByRole("button", { name: "経由地は上限まで置いてあります" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "出発地へ" }));
    expect(onPlace).toHaveBeenCalledExactlyOnceWith("origin", { latitude: BLOCK.latitude, longitude: BLOCK.longitude });
  });

  it("当たらなければそう出し、検索が使えなければ口の文を出す", async () => {
    onBackend("GET", "/api/place-search", () => Response.json({ candidates: [] }));
    renderSearch();

    await searchFor("どこにもない");
    expect(await screen.findByRole("status")).toHaveTextContent("当たる住所がありません。");

    onBackend("GET", "/api/place-search", () =>
      Response.json({ detail: "住所の検索は今は使えません" }, { status: 503 }),
    );
    await searchFor("丸の内");
    expect(await screen.findByRole("alert")).toHaveTextContent("住所の検索は今は使えません");
  });
});
