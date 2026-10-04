/**
 * `RouteForm/RouteForm.tsx`——「ルート設定」区分の各タブの中身。「条件」タブ（周回か目的地か・候補数・距離・地点の行）を
 * 描き、「重み」「除外」タブには受け取った中身を置く。
 *
 * 見るもの: モードの切り替えで上がるモード、候補数のステッパー（今の件数・1件ずつの増減・端で押せない・経由地があると
 * 決まった件数で押せず、理由を(i)の奥に置く）、周回の距離のスライダー（選べる値の範囲と刻み）、モードごとに出す地点の行、
 * 地点の行が出す値と行頭の印の色、押したときに上がる役割・消す/戻す操作、タブを切り替えても各タブの中身を外さないこと。
 *
 * ここで見ないもの: タブの列と選んだタブ、どのタブの中身が見えるか（スタイルで隠す）→ `app/page.tsx`。
 * 経由地のある目的地で何件に決まるか → `RouteForm/useRouteFormSubmit.test.ts`（このファイルは決まった数を生成物から読む）。
 * 地点を置ける状態をどう決めるか → `features/route/useGenerationConditions.test.ts`。
 *
 * タブの中身を描くには`Tabs`の中に置く必要があるので、テストが`page.tsx`の代わりに`Tabs`で包む。
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { ORIGIN_MARK_COLOR, ORIGIN_MARK_FALLBACK_COLOR, PIN_MARK_BACKGROUND } from "@/components/PinMark/PinMark";
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
  it("今のモードを選んだ状態で出し、もう一方を選ぶとそのモードを上げる", async () => {
    const { onRouteModeChange } = renderForm({ routeMode: "loop" });

    expect(screen.getByRole("radio", { name: "周回" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "目的地" })).not.toBeChecked();

    await userEvent.click(screen.getByRole("radio", { name: "目的地" }));

    expect(onRouteModeChange).toHaveBeenCalledExactlyOnceWith("destination");
  });
});

describe("RouteForm 候補数", () => {
  it("今の件数を出し、1件ずつ増減した値を文字列で上げる", async () => {
    const { onMaxRoutesChange } = renderForm({ maxRoutes: "8" });

    expect(screen.getByText("8件")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "候補数を増やす" }));
    await userEvent.click(screen.getByRole("button", { name: "候補数を減らす" }));

    expect(onMaxRoutesChange.mock.calls).toEqual([["9"], ["7"]]);
  });

  it("1件では減らせない", () => {
    renderForm({ maxRoutes: "1" });

    expect(screen.getByRole("button", { name: "候補数を減らす" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "候補数を増やす" })).toBeEnabled();
  });

  it("上限では増やせない", () => {
    renderForm({ maxRoutes: String(routeGenerateConfig.max_routes) });

    expect(screen.getByRole("button", { name: "候補数を減らす" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "候補数を増やす" })).toBeDisabled();
  });

  it("経由地を置いた目的地では、決まった件数を出して増減できなくし、(i)の奥に理由を置く", async () => {
    const fixed = routeGenerateConfig.routes_with_waypoints;
    renderForm({ routeMode: "destination", waypointCount: 2, maxRoutes: "8" });

    expect(screen.getByText(`${fixed}件`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "候補数を減らす" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "候補数を増やす" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "候補数を変えられない理由を表示" }));

    expect(screen.getByText(new RegExp(`経路を${fixed}本だけ引きます`))).toBeInTheDocument();
  });

  it("候補数の指定が効く間は、変えられない理由を出さない", () => {
    renderForm({ routeMode: "loop" });

    expect(screen.queryByRole("button", { name: /候補数を変えられない理由/ })).not.toBeInTheDocument();
  });
});

describe("RouteForm 周回", () => {
  it("出発地の行と距離のスライダー（1km〜上限を1km刻み）と候補の距離の幅を出し、経由地・目的地の行は出さない", () => {
    renderForm({ routeMode: "loop", distance: "42" });

    const slider = screen.getByRole("slider", { name: "距離" });
    expect(slider).toHaveAttribute("min", "1");
    expect(slider).toHaveAttribute("max", String(routeGenerateConfig.max_distance_km));
    expect(slider).toHaveAttribute("step", "1");
    expect(slider).toHaveValue("42");
    expect(screen.getByText("42km")).toBeInTheDocument();
    const tolerance = `±${routeGenerateConfig.default_distance_tolerance_km}km`;
    expect(screen.getByText(tolerance)).toBeInTheDocument();
    expect(slider.dataset.usage).toContain(tolerance);
    expect(pointRow("出発地を地図で選ぶ")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^経由地/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^目的地/ })).not.toBeInTheDocument();
  });

  it("距離を動かすと、選んだ値を文字列のまま上げる", () => {
    const { onDistanceChange } = renderForm({ routeMode: "loop", distance: "30" });

    fireEvent.change(screen.getByRole("slider", { name: "距離" }), { target: { value: "55" } });

    expect(onDistanceChange).toHaveBeenCalledExactlyOnceWith("55");
  });
});

describe("RouteForm 目的地", () => {
  it("出発地・経由地・目的地の行を出し、距離は出さない", () => {
    renderForm({ routeMode: "destination" });

    expect(pointRow("出発地を地図で選ぶ")).toBeInTheDocument();
    expect(pointRow("経由地を追加")).toBeInTheDocument();
    expect(pointRow("目的地を地図で選ぶ")).toBeInTheDocument();
    expect(screen.queryByRole("slider", { name: "距離" })).not.toBeInTheDocument();
  });

  it("各行の行頭の印を、地図のピンと同じ役割ごとの背景色で描く", () => {
    renderForm({ routeMode: "destination" });

    const rows = { origin: "出発地を地図で選ぶ", waypoint: "経由地を追加", destination: "目的地を地図で選ぶ" } as const;
    for (const [role, name] of Object.entries(rows) as [keyof typeof rows, string][]) {
      const mark = pointRow(name).querySelector<HTMLElement>("span[aria-hidden='true']");
      expect(mark).toHaveStyle({ background: PIN_MARK_BACKGROUND[role] });
    }
  });
});

describe("RouteForm 出発地の行", () => {
  /** 行頭の印（現在地のアイコン）を描く要素。 */
  function originMark() {
    const mark = pointRow(/^出発地/).querySelector<HTMLElement>("svg")?.parentElement;
    if (!mark) throw new Error("出発地の印が無い");
    return mark;
  }

  it("現在地を取れていれば「現在地」と出し、印を地図のピンと同じ色にする", () => {
    renderForm({ originLocated: true });

    expect(within(pointRow("出発地を地図で選ぶ")).getByText("現在地")).toBeInTheDocument();
    expect(originMark()).toHaveStyle({ color: ORIGIN_MARK_COLOR });
  });

  it("現在地を取れていなければ「現在地」と出さずにそう書き、印を取れていないときの色にする", () => {
    renderForm({ originLocated: false });

    expect(within(pointRow("出発地を地図で選ぶ")).getByText("現在地を取得できていません")).toBeInTheDocument();
    expect(originMark()).toHaveStyle({ color: ORIGIN_MARK_FALLBACK_COLOR });
  });

  it("押すと出発地を置ける状態を上げる", async () => {
    const { onArmPinRole } = renderForm({ armedPinRole: null });

    expect(pointRow("出発地を地図で選ぶ")).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(pointRow("出発地を地図で選ぶ"));

    expect(onArmPinRole).toHaveBeenCalledExactlyOnceWith("origin");
  });

  it("置ける間は値の代わりに「地図をタップ」を出し、もう一度押すとやめる", async () => {
    const { onArmPinRole } = renderForm({ armedPinRole: "origin" });

    const row = pointRow("出発地の指定をやめる");
    expect(row).toHaveAttribute("aria-pressed", "true");
    expect(within(row).getByText("地図をタップ")).toBeInTheDocument();
    await userEvent.click(row);

    expect(onArmPinRole).toHaveBeenCalledExactlyOnceWith(null);
  });

  it("地図で置いた出発地は「地図で指定」と出し、現在地に戻す操作を出す", async () => {
    const { onOriginReset } = renderForm({ originManual: true });

    expect(within(pointRow("出発地を地図で選ぶ")).getByText("地図で指定")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "出発地を現在地に戻す" }));

    expect(onOriginReset).toHaveBeenCalledOnce();
  });

  it("現在地のままの出発地には、現在地に戻す操作を出さない", () => {
    renderForm({ originManual: false });

    expect(screen.queryByRole("button", { name: "出発地を現在地に戻す" })).not.toBeInTheDocument();
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

  it("置ける間は、置いた件数を添えて「地図をタップ」を出す", () => {
    renderForm({ routeMode: "destination", waypointCount: 3, armedPinRole: "waypoint" });

    expect(within(pointRow("経由地の指定をやめる")).getByText("地図をタップ[3地点]")).toBeInTheDocument();
  });

  it("経由地が無いまま置ける間は、件数を添えずに「地図をタップ」を出す", () => {
    renderForm({ routeMode: "destination", waypointCount: 0, armedPinRole: "waypoint" });

    expect(within(pointRow("経由地の指定をやめる")).getByText("地図をタップ")).toBeInTheDocument();
  });

  it("生成が受け付ける数まで置いてあれば、行を押せなくして「上限」と出し、消す操作は残す", () => {
    const max = routeGenerateConfig.max_waypoints;
    renderForm({ routeMode: "destination", waypointCount: max });

    const row = pointRow("経由地は上限まで置いてあります");
    expect(row).toBeDisabled();
    expect(within(row).getByText("上限")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "経由地をクリア" })).toBeInTheDocument();
  });

  it("上限の1つ手前までは押せる", () => {
    renderForm({ routeMode: "destination", waypointCount: routeGenerateConfig.max_waypoints - 1 });

    expect(pointRow("経由地を追加")).toBeEnabled();
  });
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

  it("「重み」「除外」に受け取った中身を置き、タブを切り替えても外さない", async () => {
    const { showTab } = renderForm(
      { weightsPanel: <Draft name="重みの中身" />, exclusionsPanel: <Draft name="除外の中身" /> },
      "weights",
    );
    await userEvent.type(screen.getByRole("textbox", { name: "重みの中身" }), "動かした配分");
    showTab("exclusions");
    await userEvent.type(screen.getByRole("textbox", { name: "除外の中身" }), "外した種類");

    showTab("generate");
    showTab("weights");

    expect(screen.getByRole("textbox", { name: "重みの中身" })).toHaveValue("動かした配分");
    expect(screen.getByRole("textbox", { name: "除外の中身" })).toHaveValue("外した種類");
  });
});
