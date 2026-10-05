/**
 * `RouteForm/RouteForm.tsx`——「ルート設定」区分の各タブの中身。「条件」タブ（周回か目的地か・候補数・距離・地点の行）を
 * 描き、「重み」「除外」「保存」タブには受け取った中身を置く。
 *
 * 見るもの: モードの切り替えで上がるモード、候補数のステッパー（今の件数・1件ずつの増減・端で押せない・経由地があると
 * 決まった件数で押せず、理由の(i)を置く）、周回の距離のスライダーで上がる値、モードごとに出す距離と地点の行、
 * 地点の行が出す値と出発地の印の色、押したときに上がる役割・消す/戻す操作、タブを切り替えても各タブの中身を外さないこと。
 *
 * ここで見ないもの: タブの列と選んだタブ、どのタブの中身が見えるか（スタイルで隠す）→ `app/page.tsx`。
 * 書いた定数や受け取った値をそのまま渡すもの（スライダーの範囲・刻み・今の値と km の表記・候補の距離の幅、行頭の印の
 * 役割ごとの背景色、選んでいるモード、(i)の奥の理由の文）。
 * 経由地のある目的地で何件に決まるか → `RouteForm/useRouteFormSubmit.test.ts`（このファイルは決まった数を生成物から読む）。
 * 地点を置ける状態をどう決めるか → `features/route/useGenerationConditions.test.ts`。
 *
 * タブの中身を描くには`Tabs`の中に置く必要があるので、テストが`page.tsx`の代わりに`Tabs`で包む。
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { ORIGIN_MARK_COLOR, ORIGIN_MARK_FALLBACK_COLOR } from "@/components/PinMark/PinMark";
import { Tabs } from "@/components/ui/Tabs/Tabs";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import RouteForm, { type SettingsTab } from "./RouteForm";

type Props = ComponentProps<typeof RouteForm>;

/** コールバック以外の既定。見たい値はテストが渡す。 */
const BASE = {
  distance: "30",
  maxRoutes: "8",
  routeMode: "loop",
  waypointCount: 0,
  destinationSet: false,
  originManual: false,
  originLocated: true,
  armedPinRole: null,
  weightsPanel: null,
  exclusionsPanel: null,
  savedPanel: null,
} satisfies Partial<Props>;

function renderForm(props: Partial<Props> = {}, tab: SettingsTab = "generate") {
  const handlers = {
    onDistanceChange: vi.fn(),
    onMaxRoutesChange: vi.fn(),
    onRouteModeChange: vi.fn(),
    onWaypointsClear: vi.fn(),
    onDestinationClear: vi.fn(),
    onOriginReset: vi.fn(),
    onArmPinRole: vi.fn(),
  };
  const element = (next: Partial<Props>, nextTab: SettingsTab) => (
    <Tabs value={nextTab}>
      <RouteForm {...BASE} {...handlers} {...next} />
    </Tabs>
  );
  const view = render(element(props, tab));
  return { ...handlers, showTab: (nextTab: SettingsTab) => view.rerender(element(props, nextTab)) };
}

function pointRow(name: string | RegExp) {
  return screen.getByRole("button", { name });
}

describe("RouteForm 生成モード", () => {
  it("もう一方のモードを選ぶとそのモードを上げる", async () => {
    const { onRouteModeChange } = renderForm({ routeMode: "loop" });

    await userEvent.click(screen.getByRole("radio", { name: "目的地" }));

    expect(onRouteModeChange).toHaveBeenCalledExactlyOnceWith("destination");
  });
});

describe("RouteForm 候補数", () => {
  it("1件ずつ増減した値を文字列で上げる", async () => {
    const { onMaxRoutesChange } = renderForm({ maxRoutes: "8" });

    await userEvent.click(screen.getByRole("button", { name: "候補数を増やす" }));
    await userEvent.click(screen.getByRole("button", { name: "候補数を減らす" }));

    expect(onMaxRoutesChange.mock.calls).toEqual([["9"], ["7"]]);
  });

  it("1件では減らせない", () => {
    renderForm({ maxRoutes: "1" });

    expect(screen.getByRole("button", { name: "候補数を減らす" })).toBeDisabled();
  });

  it("上限では増やせない", () => {
    renderForm({ maxRoutes: String(routeGenerateConfig.max_routes) });

    expect(screen.getByRole("button", { name: "候補数を増やす" })).toBeDisabled();
  });

  it.each([
    ["周回", { routeMode: "loop" }, "8件", false],
    [
      "経由地を置いた目的地",
      { routeMode: "destination", waypointCount: 2 },
      `${routeGenerateConfig.routes_with_waypoints}件`,
      true,
    ],
  ] as const)(
    "%sでは件数を出し、決まった件数なら増減できなくして変えられない理由の(i)を置く",
    (_mode, props, count, fixed) => {
      renderForm({ maxRoutes: "8", ...props });

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
  ] as const)(
    "%sでは出発地の行を出し、距離のスライダーと経由地・目的地の行のどちらかを出す",
    (routeMode, distance, points) => {
      renderForm({ routeMode });

      expect(pointRow("出発地を地図で選ぶ")).toBeInTheDocument();
      expect(screen.queryByRole("slider", { name: "距離" }) !== null).toBe(distance);
      expect(screen.queryByRole("button", { name: /^経由地/ }) !== null).toBe(points);
      expect(screen.queryByRole("button", { name: /^目的地/ }) !== null).toBe(points);
    },
  );

  it("距離を動かすと、選んだ値を文字列のまま上げる", () => {
    const { onDistanceChange } = renderForm({ routeMode: "loop", distance: "30" });

    fireEvent.change(screen.getByRole("slider", { name: "距離" }), { target: { value: "55" } });

    expect(onDistanceChange).toHaveBeenCalledExactlyOnceWith("55");
  });
});

describe("RouteForm 出発地の行", () => {
  /** 行頭の印（現在地のアイコン）を描く要素。 */
  function originMark() {
    const mark = pointRow(/^出発地/).querySelector<HTMLElement>("svg")?.parentElement;
    if (!mark) throw new Error("出発地の印が無い");
    return mark;
  }

  it.each([
    [true, "現在地", ORIGIN_MARK_COLOR],
    [false, "現在地を取得できていません", ORIGIN_MARK_FALLBACK_COLOR],
  ])(
    "現在地を取れたか（%s）で値を「%s」とし、印の色を変え、現在地に戻す操作は出さない",
    (originLocated, value, color) => {
      renderForm({ originLocated });

      expect(within(pointRow("出発地を地図で選ぶ")).getByText(value)).toBeInTheDocument();
      expect(originMark()).toHaveStyle({ color });
      expect(screen.queryByRole("button", { name: "出発地を現在地に戻す" })).not.toBeInTheDocument();
    },
  );

  it.each([
    [null, "出発地を地図で選ぶ", "false", "現在地", "origin"],
    ["origin", "出発地の指定をやめる", "true", "地図をタップ", null],
  ] as const)(
    "置ける役割が%sなら行を「%s」とし、押すと置ける状態を切り替える",
    async (armedPinRole, name, pressed, value, raised) => {
      const { onArmPinRole } = renderForm({ armedPinRole });

      const row = pointRow(name);
      expect(row).toHaveAttribute("aria-pressed", pressed);
      expect(within(row).getByText(value)).toBeInTheDocument();
      await userEvent.click(row);

      expect(onArmPinRole).toHaveBeenCalledExactlyOnceWith(raised);
    },
  );

  it("地図で置いた出発地は「地図で指定」と出し、現在地に戻す操作を出す", async () => {
    const { onOriginReset } = renderForm({ originManual: true });

    expect(within(pointRow("出発地を地図で選ぶ")).getByText("地図で指定")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "出発地を現在地に戻す" }));

    expect(onOriginReset).toHaveBeenCalledOnce();
  });
});

describe("RouteForm 経由地の行", () => {
  it("経由地が無い間は「なし」と出して消す操作を出さず、押すと経由地を置ける状態を上げる", async () => {
    const { onArmPinRole } = renderForm({ routeMode: "destination", waypointCount: 0 });

    expect(within(pointRow("経由地を追加")).getByText("なし")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "経由地をクリア" })).not.toBeInTheDocument();

    await userEvent.click(pointRow("経由地を追加"));

    expect(onArmPinRole).toHaveBeenCalledExactlyOnceWith("waypoint");
  });

  it("経由地があれば件数を値と印に出し、消す操作を押すと上げる", async () => {
    const { onWaypointsClear } = renderForm({ routeMode: "destination", waypointCount: 3 });

    const row = pointRow("経由地を追加");
    expect(within(row).getByText("3地点")).toBeInTheDocument();
    expect(within(row).getByText("3")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "経由地をクリア" }));

    expect(onWaypointsClear).toHaveBeenCalledOnce();
  });

  it.each([
    [3, "地図をタップ[3地点]"],
    [0, "地図をタップ"],
  ])("置いた経由地が%i件のとき、置ける間は件数があれば添えて「地図をタップ」を出す", (waypointCount, hint) => {
    renderForm({ routeMode: "destination", waypointCount, armedPinRole: "waypoint" });

    expect(within(pointRow("経由地の指定をやめる")).getByText(hint)).toBeInTheDocument();
  });

  it.each([
    [routeGenerateConfig.max_waypoints, "経由地は上限まで置いてあります", "上限", true],
    [routeGenerateConfig.max_waypoints - 1, "経由地を追加", "追加", false],
  ])(
    "%i件では行を「%s」とし、生成が受け付ける数までなら押せなくする。消す操作は残す",
    (waypointCount, name, action, full) => {
      renderForm({ routeMode: "destination", waypointCount });

      const row = pointRow(name);
      expect(row).toHaveProperty("disabled", full);
      expect(within(row).getByText(action)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "経由地をクリア" })).toBeInTheDocument();
    },
  );
});

describe("RouteForm 目的地の行", () => {
  it("目的地が無い間は「未設定」と出して消す操作を出さず、押すと目的地を置ける状態を上げる", async () => {
    const { onArmPinRole } = renderForm({ routeMode: "destination", destinationSet: false });

    expect(within(pointRow("目的地を地図で選ぶ")).getByText("未設定")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "目的地をクリア" })).not.toBeInTheDocument();

    await userEvent.click(pointRow("目的地を地図で選ぶ"));

    expect(onArmPinRole).toHaveBeenCalledExactlyOnceWith("destination");
  });

  it("置いた目的地は「地図で指定」と出して置き直す行にし、消す操作を押すと上げる", async () => {
    const { onDestinationClear } = renderForm({ routeMode: "destination", destinationSet: true });

    expect(within(pointRow("目的地を置き直す")).getByText("地図で指定")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "目的地をクリア" }));

    expect(onDestinationClear).toHaveBeenCalledOnce();
  });
});

describe("RouteForm タブの中身", () => {
  /** 打った文字を自分の中に持つ中身（タブを切り替えて外れると消える）。 */
  function Draft({ name }: { name: string }) {
    const [text, setText] = useState("");
    return <input aria-label={name} value={text} onChange={(e) => setText(e.target.value)} />;
  }

  it("「重み」「除外」「保存」に受け取った中身を置き、タブを切り替えても外さない", async () => {
    const { showTab } = renderForm(
      {
        weightsPanel: <Draft name="重みの中身" />,
        exclusionsPanel: <Draft name="除外の中身" />,
        savedPanel: <Draft name="保存の中身" />,
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
