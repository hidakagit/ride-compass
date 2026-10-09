/**
 * `RouteForm/RouteForm.tsx`——「ルート設定」区分の各タブの中身。「条件」タブ（周回か目的地か・候補数・距離・地点の並びと詳しく）を
 * 描き、「重み」「除外」タブと「保存」タブの「設定」には受け取った中身を置き、「保存」タブの「地点」には保存した地点を並べる。
 *
 * 見るもの: モードの切り替えで上がるモード、候補数のステッパー（今の件数・1件ずつの増減・端で押せない・経由地があると
 * 決まった件数で押せず、理由の(i)を置く）、周回の距離のスライダーで上がる値、モードごとに出す距離と地点の並び、
 * 地点の並び（出発地・経由地の番号の丸・目的地）と押した地点の詳しく（呼び名・出どころ・名前・その位置から引いた辺り）、出発地の印の色、
 * 地図で置く操作を押したときに上がる役割・消す/戻す操作、名前を打って選んだ候補をその地点として上げること、
 * タブを切り替えても各タブの中身を外さないこと。
 *
 * ここで見ないもの: タブの列と選んだタブ、どのタブの中身が見えるか（スタイルで隠す）→ `app/page.tsx`。
 * 書いた定数や受け取った値をそのまま渡すもの（スライダーの範囲・刻み・今の値と km の表記・候補の距離の幅、印の
 * 役割ごとの背景色、選んでいるモード、(i)の奥の理由の文）。
 * 経由地のある目的地で何件に決まるか → `RouteForm/useRouteFormSubmit.test.ts`（このファイルは決まった数を生成物から読む）。
 * 地点を置ける状態をどう決めるか → `features/route/useGenerationConditions.test.ts`。
 * 打ちかけで引く間・変換中に引かないこと・候補の行の中身（辺り・距離・札）・引けない／当たらないときの文、探して置いた
 * 地点の辺りと代表の位置 → `RouteForm/PointDetail.test.tsx`。
 * 検索で置いた地点が、ピンを動かすまでその候補のままか → `features/route/useGenerationConditions.test.ts`。
 * 並びに入りきらないときに両端の札を印だけにすること（テスト環境はレイアウトの実寸を持たない）→ `e2e/all-states.spec.ts`の
 * 省略の検査（名前を途中で切っていないこと）。
 *
 * 差し替えたもの: 検索の口と辺りの口の応答（網の層）。辺りの口は、テストが応答を渡さなければ辺り無しと答える。
 *
 * タブの中身を描くには`Tabs`の中に置く必要があるので、テストが`page.tsx`の代わりに`Tabs`で包む。
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ORIGIN_MARK_COLOR, ORIGIN_MARK_FALLBACK_COLOR } from "@/components/PinMark/PinMark";
import { Tabs } from "@/components/ui/Tabs/Tabs";
import { onBackend } from "@/testing/backendServer";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { PlaceCandidate } from "@/types/route";

import RouteForm, { type SettingsTab } from "./RouteForm";

type Props = ComponentProps<typeof RouteForm>;
/** 部品へ渡す値。生成の条件の欄（`conditions`）とほかの props を並べて渡し、`renderForm` が分ける。 */
type Options = Partial<Props["conditions"]> & Partial<Omit<Props, "conditions">>;

/** 出発地の位置（現在地）。 */
const ORIGIN = { latitude: 35.75, longitude: 139.73 };

/** コールバック以外の既定。見たい値はテストが渡す。 */
const BASE = {
  distanceInput: "30",
  maxRoutesInput: "8",
  routeMode: "loop",
  waypoints: [],
  destination: null,
  origin: ORIGIN,
  originManual: false,
  originLocated: true,
  armedPinRole: null,
  waypointToReplace: null,
  foundAt: () => null,
  originFound: null,
  mapCenter: { latitude: 35.681, longitude: 139.767 },
  weightsPanel: null,
  exclusionsPanel: null,
  savedConditionsPanel: null,
  savedPlaces: { places: [], save: () => {}, remove: () => {} },
} satisfies Options;

/** 置いた経由地（地点は並べるだけ）。 */
function waypointsOf(count: number) {
  return Array.from({ length: count }, (_, i) => ({ latitude: 35 + i * 0.01, longitude: 139 }));
}

const DESTINATION = { latitude: 35.1, longitude: 139.1 };
/** 字・丁目で当たった住所（その範囲の代表の位置）。 */
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

// 詳しくは置いた地点の辺りを引く。辺りを見ないテストには、辺り無しと答える（見るテストは後から応答を渡す）。
beforeEach(() => {
  onBackend("GET", "/api/place-area", () => Response.json({ area: null }));
});

function renderForm(options: Options = {}, tab: SettingsTab = "generate") {
  const handlers = {
    setDistanceInput: vi.fn(),
    setMaxRoutesInput: vi.fn(),
    changeRouteMode: vi.fn(),
    removeWaypoint: vi.fn(),
    clearDestination: vi.fn(),
    onOriginReset: vi.fn(),
    armPinRole: vi.fn(),
    onPlaceFound: vi.fn(),
  };
  const element = (nextTab: SettingsTab, changed: Options = {}) => {
    const {
      origin,
      originManual,
      originLocated,
      onOriginReset,
      originFound,
      mapCenter,
      onPlaceFound,
      weightsPanel,
      exclusionsPanel,
      savedConditionsPanel,
      savedPlaces,
      ...conditions
    } = {
      ...BASE,
      ...handlers,
      ...options,
      ...changed,
    };
    return (
      <Tabs value={nextTab}>
        <RouteForm
          conditions={conditions}
          origin={origin}
          originManual={originManual}
          originLocated={originLocated}
          onOriginReset={onOriginReset}
          originFound={originFound}
          mapCenter={mapCenter}
          onPlaceFound={onPlaceFound}
          savedPlaces={savedPlaces}
          weightsPanel={weightsPanel}
          exclusionsPanel={exclusionsPanel}
          savedConditionsPanel={savedConditionsPanel}
        />
      </Tabs>
    );
  };
  const view = render(element(tab));
  return {
    ...handlers,
    showTab: (nextTab: SettingsTab) => view.rerender(element(nextTab)),
    /** 上げた操作を受けて変わった条件で描き直す。 */
    showWith: (changed: Options) => view.rerender(element(tab, changed)),
  };
}

/** 地図で置く操作・消す・現在地に戻す等のボタン。 */
function button(name: string) {
  return screen.getByRole("button", { name });
}

/** 押した地点の詳しく（呼び名・出どころ・名前・打つ欄・操作）。 */
function detail(title: string) {
  return screen.getByRole("region", { name: title });
}

/** 詳しくの打つ欄。 */
function pointBox(title: string) {
  return screen.getByRole("searchbox", { name: `${title}を住所・施設で探す` });
}

/** 地点の並び（出発地 › 経由地の番号の丸 ＋ › 目的地）の、押せるものの名前。 */
function strip() {
  return within(screen.getByRole("group", { name: "地点の並び" }))
    .getAllByRole("button")
    .map((chip) => chip.getAttribute("aria-label"));
}

describe("RouteForm 生成モード", () => {
  it("もう一方のモードを選ぶとそのモードを上げる", async () => {
    const { changeRouteMode } = renderForm({ routeMode: "loop" });

    await userEvent.click(screen.getByRole("radio", { name: "目的地" }));

    expect(changeRouteMode).toHaveBeenCalledExactlyOnceWith("destination");
  });
});

describe("RouteForm 候補数", () => {
  it("1件ずつ増減した値を文字列で上げる", async () => {
    const { setMaxRoutesInput } = renderForm({ maxRoutesInput: "8" });

    await userEvent.click(screen.getByRole("button", { name: "候補数を増やす" }));
    await userEvent.click(screen.getByRole("button", { name: "候補数を減らす" }));

    expect(setMaxRoutesInput.mock.calls).toEqual([["9"], ["7"]]);
  });

  it("1件では減らせない", () => {
    renderForm({ maxRoutesInput: "1" });

    expect(screen.getByRole("button", { name: "候補数を減らす" })).toBeDisabled();
  });

  it("上限では増やせない", () => {
    renderForm({ maxRoutesInput: String(routeGenerateConfig.max_routes) });

    expect(screen.getByRole("button", { name: "候補数を増やす" })).toBeDisabled();
  });

  it.each([
    ["周回", { routeMode: "loop" }, "8件", false],
    [
      "経由地を置いた目的地",
      { routeMode: "destination", waypoints: waypointsOf(2) },
      `${routeGenerateConfig.routes_with_waypoints}件`,
      true,
    ],
  ] as const)(
    "%sでは件数を出し、決まった件数なら増減できなくして変えられない理由の(i)を置く",
    (_mode, props, count, fixed) => {
      renderForm({ maxRoutesInput: "8", ...props });

      expect(screen.getByText(count)).toBeInTheDocument();
      for (const name of ["候補数を減らす", "候補数を増やす"]) {
        expect(screen.getByRole("button", { name })).toHaveProperty("disabled", fixed);
      }
      expect(screen.queryByRole("button", { name: "候補数を変えられない理由を表示" }) !== null).toBe(fixed);
    },
  );
});

describe("RouteForm モードごとの入力", () => {
  it.each([
    ["loop", true, false],
    ["destination", false, true],
  ] as const)("%sでは出発地を置け、距離のスライダーと地点の並びのどちらかを出す", (routeMode, distance, points) => {
    renderForm({ routeMode, armedPinRole: "origin" });

    expect(detail("出発地")).toBeInTheDocument();
    expect(screen.queryByRole("slider", { name: "距離" }) !== null).toBe(distance);
    expect(screen.queryByRole("group", { name: "地点の並び" }) !== null).toBe(points);
  });

  it("距離を動かすと、選んだ値を文字列のまま上げる", () => {
    const { setDistanceInput } = renderForm({ routeMode: "loop", distanceInput: "30" });

    fireEvent.change(screen.getByRole("slider", { name: "距離" }), { target: { value: "55" } });

    expect(setDistanceInput).toHaveBeenCalledExactlyOnceWith("55");
  });
});

describe("RouteForm 出発地", () => {
  /** 印（現在地のアイコン）を描く要素。 */
  function originMark() {
    const mark = detail("出発地").querySelector<HTMLElement>("svg")?.parentElement;
    if (!mark) throw new Error("出発地の印が無い");
    return mark;
  }

  it.each([
    [true, "現在地", ORIGIN_MARK_COLOR],
    [false, "現在地を取得できていません", ORIGIN_MARK_FALLBACK_COLOR],
  ])(
    "現在地を取れたか（%s）で名前を「%s」とし、印の色を変え、現在地に戻す操作は出さない",
    (originLocated, name, color) => {
      renderForm({ originLocated });

      expect(detail("出発地")).toHaveTextContent(`出発地・現在地${name}`);
      expect(originMark()).toHaveStyle({ color });
      expect(screen.queryByRole("button", { name: "出発地を現在地に戻す" })).not.toBeInTheDocument();
    },
  );

  it.each([
    [null, "出発地を地図で選ぶ", "false", "住所・施設で探して置き直す", "origin"],
    ["origin", "出発地の指定をやめる", "true", "地図をタップ", null],
  ] as const)(
    "置ける役割が%sなら地図で置く操作を「%s」とし、押すと置ける状態を切り替える",
    async (armedPinRole, name, pressed, placeholder, raised) => {
      const { armPinRole } = renderForm({ armedPinRole });

      expect(button(name)).toHaveAttribute("aria-pressed", pressed);
      expect(pointBox("出発地")).toHaveAttribute("placeholder", placeholder);
      await userEvent.click(button(name));

      expect(armPinRole).toHaveBeenCalledExactlyOnceWith(raised);
    },
  );

  it.each([
    [null, "出発地・地図で選んだ地点地図で選んだ地点"],
    [FACILITY, `出発地・探して選んだ地点${FACILITY.name}`],
  ])(
    "置いた出発地は、探して置いたときの位置のままなら名前、ほかは「地図で選んだ地点」と出し、現在地に戻す操作を出す",
    async (originFound, text) => {
      const { onOriginReset } = renderForm({ originManual: true, originFound });

      expect(detail("出発地").textContent).toContain(text);
      await userEvent.click(button("出発地を現在地に戻す"));

      expect(onOriginReset).toHaveBeenCalledOnce();
    },
  );
});

describe("RouteForm 地点の並び", () => {
  it("出発地・経由地の番号の丸・足す・目的地を並べ、何も押していなければ目的地の詳しくを出す", () => {
    const [first, second] = waypointsOf(2);
    renderForm({
      routeMode: "destination",
      waypoints: [first, second],
      destination: DESTINATION,
      foundAt: (at) => (at === second ? FACILITY : at === DESTINATION ? AZA : null),
    });

    expect(strip()).toEqual([
      "出発地: 現在地",
      "経由地1: 地図で選んだ地点",
      `経由地2: ${FACILITY.name}`,
      "経由地を足す",
      `目的地: ${AZA.name}`,
    ]);
    expect(button(`目的地: ${AZA.name}`)).toHaveAttribute("aria-pressed", "true");
    expect(detail("目的地").textContent).toContain(`目的地・探して選んだ地点${AZA.name}`);
  });

  it("押した地点の詳しくを出し、地図で置く状態なら解く", async () => {
    const { armPinRole } = renderForm({
      routeMode: "destination",
      waypoints: waypointsOf(2),
      foundAt: (at) => (at?.latitude === 35.01 ? FACILITY : null),
    });

    await userEvent.click(button(`経由地2: ${FACILITY.name}`));
    expect(detail("経由地2").textContent).toContain(`経由地2・探して選んだ地点${FACILITY.name}`);
    expect(button(`経由地2: ${FACILITY.name}`)).toHaveAttribute("aria-pressed", "true");
    expect(armPinRole).not.toHaveBeenCalled();

    await userEvent.click(button("出発地: 現在地"));
    expect(detail("出発地")).toBeInTheDocument();
  });

  it.each([
    ["出発地: 現在地", "出発地", ORIGIN],
    ["経由地2: 地図で選んだ地点", "経由地2", waypointsOf(2)[1]],
    ["目的地: 地図で選んだ地点", "目的地", DESTINATION],
  ])("押した地点（%s）の詳しくに、その位置から引いた辺りを出す", async (chip, title, point) => {
    onBackend("GET", "/api/place-area", ({ query }) =>
      Response.json({ area: query.latitude === String(point.latitude) ? "押した地点の辺り" : "ほかの地点の辺り" }),
    );
    renderForm({ routeMode: "destination", waypoints: waypointsOf(2), destination: DESTINATION });

    await userEvent.click(button(chip));

    expect(await within(detail(title)).findByText("押した地点の辺り")).toBeInTheDocument();
  });

  it("現在地を取れていない出発地は、仮の位置の辺りを引かない", async () => {
    const sent = onBackend("GET", "/api/place-area", () => Response.json({ area: "仮の位置の辺り" }));
    renderForm({ originLocated: false });

    // 引くなら詳しくを描いた直後に送る。少し待っても送っていない。
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(sent).toEqual([]);
  });

  it("地図で置く状態の地点を押すと、置く状態を解く", async () => {
    const { armPinRole } = renderForm({ routeMode: "destination", armedPinRole: "destination" });

    await userEvent.click(button("出発地: 現在地"));

    expect(armPinRole).toHaveBeenCalledExactlyOnceWith(null);
  });

  it.each([
    [routeGenerateConfig.max_waypoints, "経由地は上限まで置いてあります", true],
    [routeGenerateConfig.max_waypoints - 1, "経由地を足す", false],
  ])("経由地が%i件なら足す操作を「%s」とし、生成が受け付ける数までなら押せなくする", (waypointCount, name, full) => {
    renderForm({ routeMode: "destination", waypoints: waypointsOf(waypointCount) });

    expect(button(name)).toHaveProperty("disabled", full);
  });
});

describe("RouteForm 経由地", () => {
  it("足す操作を押すと、地図で経由地を足せる状態を上げる", async () => {
    const { armPinRole } = renderForm({ routeMode: "destination" });

    await userEvent.click(button("経由地を足す"));

    expect(armPinRole).toHaveBeenCalledExactlyOnceWith("waypoint");
  });

  it.each([
    [3, "地図をタップ[3地点]"],
    [0, "地図をタップ"],
  ])(
    "置いた経由地が%i件のとき、足せる間は新しい経由地の詳しくに件数があれば添えて「地図をタップ」を出す",
    (count, hint) => {
      renderForm({ routeMode: "destination", waypoints: waypointsOf(count), armedPinRole: "waypoint" });

      expect(button("新しい経由地の指定をやめる")).toBeInTheDocument();
      expect(pointBox("新しい経由地")).toHaveAttribute("placeholder", hint);
    },
  );

  it("上限まで置いたあとは、新しい経由地を地図でも探しても置けない", () => {
    const max = routeGenerateConfig.max_waypoints;
    renderForm({ routeMode: "destination", waypoints: waypointsOf(max), armedPinRole: "waypoint" });

    expect(button("新しい経由地は上限まで置いてあります")).toBeDisabled();
    expect(pointBox("新しい経由地")).toBeDisabled();
  });

  it("置いた経由地は、地図で置き直す操作でその経由地を置き直せる状態を上げ、消す操作でその経由地を消す", async () => {
    const { armPinRole, removeWaypoint } = renderForm({ routeMode: "destination", waypoints: waypointsOf(3) });

    await userEvent.click(button("経由地2: 地図で選んだ地点"));
    await userEvent.click(button("経由地2を地図で置き直す"));
    expect(armPinRole).toHaveBeenLastCalledWith("waypoint", 1);

    await userEvent.click(button("経由地2を消す"));
    expect(removeWaypoint).toHaveBeenCalledExactlyOnceWith(1);
  });

  it("その経由地を置き直せる間は、その詳しくを出して指定をやめる操作にする", () => {
    renderForm({ routeMode: "destination", waypoints: waypointsOf(3), armedPinRole: "waypoint", waypointToReplace: 2 });

    expect(button("経由地3の指定をやめる")).toHaveAttribute("aria-pressed", "true");
    expect(pointBox("経由地3")).toHaveAttribute("placeholder", "地図をタップ");
  });
});

describe("RouteForm 目的地", () => {
  it("目的地が無い間は「未設定」と出して消す操作を出さず、押すと目的地を置ける状態を上げる", async () => {
    const { armPinRole } = renderForm({ routeMode: "destination", destination: null });

    expect(detail("目的地")).toHaveTextContent("目的地未設定");
    expect(screen.queryByRole("button", { name: "目的地を消す" })).not.toBeInTheDocument();

    await userEvent.click(button("目的地を地図で選ぶ"));

    expect(armPinRole).toHaveBeenCalledExactlyOnceWith("destination");
  });

  it.each([
    [null, "目的地・地図で選んだ地点地図で選んだ地点"],
    [FACILITY, `目的地・探して選んだ地点${FACILITY.name}`],
  ])(
    "置いた目的地は、探して置いたときの位置のままなら名前、ほかは「地図で選んだ地点」と出して置き直せるようにし、消す操作を押すと上げる",
    async (found, text) => {
      const { clearDestination } = renderForm({
        routeMode: "destination",
        destination: DESTINATION,
        foundAt: (at) => (at === DESTINATION ? found : null),
      });

      expect(detail("目的地").textContent).toContain(text);
      expect(button("目的地を地図で置き直す")).toBeInTheDocument();

      await userEvent.click(button("目的地を消す"));

      expect(clearDestination).toHaveBeenCalledOnce();
    },
  );
});

describe("RouteForm 探して置く", () => {
  it.each([
    ["目的地", null, "destination", null],
    ["新しい経由地", "経由地を足す", "waypoint", null],
    ["経由地2", "経由地2: 地図で選んだ地点", "waypoint", 1],
    ["出発地", "出発地: 現在地", "origin", null],
  ] as const)(
    "%sの詳しくで名前を打つと候補を欄の下に出し、選ぶとその地点として上げて、打った文字と一覧を消す",
    async (title, chip, role, waypointIndex) => {
      const sent = onBackend("GET", "/api/place-search", () => Response.json({ candidates: [AZA, FACILITY] }));
      const { onPlaceFound } = renderForm({ routeMode: "destination", waypoints: waypointsOf(2) });
      if (chip !== null) await userEvent.click(button(chip));

      await userEvent.type(pointBox(title), "浅草寺{Enter}");

      const list = await within(detail(title)).findByRole("list", { name: "地点の候補" });
      expect(sent.map((request) => request.query.q)).toEqual(["浅草寺"]);
      await userEvent.click(within(list).getByRole("button", { name: new RegExp(FACILITY.name) }));

      expect(onPlaceFound).toHaveBeenCalledExactlyOnceWith(role, FACILITY, waypointIndex);
      expect(screen.queryByRole("list", { name: "地点の候補" })).toBeNull();
    },
  );

  it("新しい経由地を探して足したら、足した経由地の詳しくを出す", async () => {
    onBackend("GET", "/api/place-search", () => Response.json({ candidates: [FACILITY] }));
    const { showWith } = renderForm({ routeMode: "destination", waypoints: waypointsOf(2) });
    await userEvent.click(button("経由地を足す"));

    await userEvent.type(pointBox("新しい経由地"), "浅草寺{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: new RegExp(FACILITY.name) }));
    showWith({ waypoints: waypointsOf(3), armedPinRole: null });

    expect(detail("経由地3")).toBeInTheDocument();
  });

  it("候補の一覧は✕で閉じ、打った文字も消す", async () => {
    onBackend("GET", "/api/place-search", () => Response.json({ candidates: [AZA] }));
    const { onPlaceFound } = renderForm({ routeMode: "destination" });

    await userEvent.type(pointBox("目的地"), "丸の内{Enter}");
    await screen.findByRole("list", { name: "地点の候補" });
    await userEvent.click(button("目的地の候補を閉じる"));

    expect(screen.queryByRole("list", { name: "地点の候補" })).toBeNull();
    expect(pointBox("目的地")).toHaveValue("");
    expect(onPlaceFound).not.toHaveBeenCalled();
  });
});

describe("RouteForm タブの中身", () => {
  /** 打った文字を自分の中に持つ中身（タブを切り替えて外れると消える）。 */
  function Draft({ name }: { name: string }) {
    const [text, setText] = useState("");
    return <input aria-label={name} value={text} onChange={(e) => setText(e.target.value)} />;
  }

  it("「重み」「除外」と「保存」の「設定」に受け取った中身を置き、タブを切り替えても外さない", async () => {
    const { showTab } = renderForm(
      {
        weightsPanel: <Draft name="重みの中身" />,
        exclusionsPanel: <Draft name="除外の中身" />,
        savedConditionsPanel: <Draft name="保存の中身" />,
      },
      "weights",
    );
    await userEvent.type(screen.getByRole("textbox", { name: "重みの中身" }), "動かした配分");
    showTab("exclusions");
    await userEvent.type(screen.getByRole("textbox", { name: "除外の中身" }), "外した種類");
    showTab("saved");
    await userEvent.type(screen.getByRole("textbox", { name: "保存の中身" }), "書きかけの名前");

    showTab("generate");
    showTab("weights");

    expect(screen.getByRole("textbox", { name: "重みの中身" })).toHaveValue("動かした配分");
    expect(screen.getByRole("textbox", { name: "除外の中身" })).toHaveValue("外した種類");
    expect(screen.getByRole("textbox", { name: "保存の中身" })).toHaveValue("書きかけの名前");
  });
});
