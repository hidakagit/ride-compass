import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Tabs } from "@/components/ui/Tabs/Tabs";
import { ORIGIN_MARK_COLOR, ORIGIN_MARK_FALLBACK_COLOR } from "@/lib/mapDisplay/pinMarks";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import RouteForm from "./RouteForm";

const MAX_ROUTES = routeGenerateConfig.max_routes;
const MAX_DISTANCE_KM = routeGenerateConfig.max_distance_km;

type Props = React.ComponentProps<typeof RouteForm>;

function renderForm(overrides: Partial<Props> = {}, tab = "generate") {
  const props: Props = {
    distance: "20",
    onDistanceChange: vi.fn(),
    maxRoutes: "3",
    onMaxRoutesChange: vi.fn(),
    routeMode: "loop",
    onRouteModeChange: vi.fn(),
    waypointCount: 0,
    onWaypointsClear: vi.fn(),
    destinationSet: false,
    onDestinationClear: vi.fn(),
    originManual: false,
    originLocated: true,
    onOriginReset: vi.fn(),
    armedPinRole: null,
    onArmPinRole: vi.fn(),
    weightsPanel: <p>重みの中身</p>,
    exclusionsPanel: <p>除外の中身</p>,
    ...overrides,
  };
  // タブの列と選択状態は画面（page.tsx）が持つ。ここは中身だけを描く。
  render(
    <Tabs value={tab}>
      <RouteForm {...props} />
    </Tabs>,
  );
  return props;
}

describe("RouteForm 生成モード", () => {
  it("もう一方のモードを選ぶと、そのモードを親へ渡す", async () => {
    const props = renderForm();
    await userEvent.click(screen.getByRole("radio", { name: "目的地" }));
    expect(props.onRouteModeChange).toHaveBeenCalledWith("destination");
  });
});

describe("RouteForm 候補数", () => {
  it("今の件数を出し、1件ずつ増減する", async () => {
    const props = renderForm({ maxRoutes: "3" });
    expect(screen.getByText("3件")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "候補数を増やす" }));
    await userEvent.click(screen.getByRole("button", { name: "候補数を減らす" }));
    expect(props.onMaxRoutesChange).toHaveBeenNthCalledWith(1, "4");
    expect(props.onMaxRoutesChange).toHaveBeenNthCalledWith(2, "2");
  });

  it("1件より減らせず、上限より増やせない", () => {
    renderForm({ maxRoutes: "1" });
    expect(screen.getByRole("button", { name: "候補数を減らす" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "候補数を増やす" })).toBeEnabled();
  });

  it("上限では増やせない", () => {
    renderForm({ maxRoutes: String(MAX_ROUTES) });
    expect(screen.getByRole("button", { name: "候補数を増やす" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "候補数を減らす" })).toBeEnabled();
  });

  it("経由地を置いた目的地では、1件と出して増減できなくし、理由の案内を出す", () => {
    renderForm({ routeMode: "destination", waypointCount: 2, maxRoutes: "4" });
    expect(screen.getByText(`${routeGenerateConfig.routes_with_waypoints}件`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "候補数を増やす" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "候補数を減らす" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "候補数を変えられない理由を表示" })).toBeInTheDocument();
  });

  it("候補数が効く間は、理由の案内を出さない", () => {
    renderForm({ routeMode: "destination", waypointCount: 0 });
    expect(screen.queryByRole("button", { name: /候補数を変えられない理由/ })).not.toBeInTheDocument();
  });
});

describe("RouteForm 周回の距離", () => {
  it("距離は1km〜上限の1km刻みで選び、選んだ値を文字列のまま親へ渡す", () => {
    const props = renderForm({ distance: "20" });
    const slider = screen.getByRole("slider", { name: "距離" });
    expect(slider).toHaveAttribute("min", "1");
    expect(slider).toHaveAttribute("max", String(MAX_DISTANCE_KM));
    expect(slider).toHaveAttribute("step", "1");
    expect(screen.getByText("20km")).toBeInTheDocument();
    // 周回では地点の行を出さない（目的地モードで出る行が、ここには無い）。
    expect(screen.queryByRole("button", { name: "目的地を地図で選ぶ" })).not.toBeInTheDocument();
    fireEvent.change(slider, { target: { value: "21" } });
    expect(props.onDistanceChange).toHaveBeenCalledWith("21");
  });
});

describe("RouteForm 目的地の地点", () => {
  const destination = { routeMode: "destination" as const };

  it("距離の代わりに、出発地・経由地・目的地の行を出す", () => {
    renderForm(destination);
    expect(screen.queryByRole("slider", { name: "距離" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "出発地を地図で選ぶ" })).toHaveTextContent("現在地");
    expect(screen.getByRole("button", { name: "経由地を追加" })).toHaveTextContent("なし");
    expect(screen.getByRole("button", { name: "目的地を地図で選ぶ" })).toHaveTextContent("未設定");
  });

  it("行を押すと、その役割で地図のタップを待つ", async () => {
    const props = renderForm(destination);
    await userEvent.click(screen.getByRole("button", { name: "目的地を地図で選ぶ" }));
    expect(props.onArmPinRole).toHaveBeenCalledWith("destination");
  });

  it("待っている行は、値の代わりに地図をタップするよう示し、押すとやめる", async () => {
    const props = renderForm({ ...destination, armedPinRole: "destination" });
    const row = screen.getByRole("button", { name: "目的地の指定をやめる" });
    expect(row).toHaveTextContent("地図をタップ");
    expect(row).toHaveTextContent("やめる");
    await userEvent.click(row);
    expect(props.onArmPinRole).toHaveBeenCalledWith(null);
  });

  it("経由地を待っている間は、置いた数を隠さない", () => {
    renderForm({ ...destination, waypointCount: 2, armedPinRole: "waypoint" });
    expect(screen.getByRole("button", { name: "経由地の指定をやめる" })).toHaveTextContent("地図をタップ（2地点）");
  });

  it("置いた地点は行に出し、消す操作を添える（置いていない地点には添えない）", async () => {
    const props = renderForm({ ...destination, waypointCount: 2, destinationSet: true, originManual: true });
    expect(screen.getByRole("button", { name: "出発地を地図で選ぶ" })).toHaveTextContent("地図で指定");
    expect(screen.getByRole("button", { name: "経由地を追加" })).toHaveTextContent("2地点");
    expect(screen.getByRole("button", { name: "目的地を置き直す" })).toHaveTextContent("地図で指定");

    await userEvent.click(screen.getByRole("button", { name: "経由地をクリア" }));
    await userEvent.click(screen.getByRole("button", { name: "目的地をクリア" }));
    await userEvent.click(screen.getByRole("button", { name: "出発地を現在地に戻す" }));
    expect(props.onWaypointsClear).toHaveBeenCalled();
    expect(props.onDestinationClear).toHaveBeenCalled();
    expect(props.onOriginReset).toHaveBeenCalled();
  });

  it("置いていない地点には、消す操作を出さない", () => {
    renderForm(destination);
    for (const name of ["経由地をクリア", "目的地をクリア", "出発地を現在地に戻す"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });

  it("出発地の印は、現在地を取れていない間は地図のピンと同じ灰色にする", () => {
    renderForm({ ...destination, originLocated: false });
    // 行頭の印（地図のピンと同じ図形を描いた要素）。
    const mark = screen.getByRole("button", { name: "出発地を地図で選ぶ" }).querySelector('[aria-hidden="true"]')!;
    expect(mark.innerHTML).toContain(ORIGIN_MARK_FALLBACK_COLOR);
    expect(mark.innerHTML).not.toContain(ORIGIN_MARK_COLOR);
  });
});

describe("RouteForm タブの中身", () => {
  it("重み・除外の中身は、別のタブを見ている間も描いておく（中の途中の状態を失わない）", () => {
    renderForm({}, "generate");
    for (const text of ["重みの中身", "除外の中身"]) {
      expect(screen.getByText(text).closest("[role=tabpanel]")).toHaveAttribute("data-state", "inactive");
    }
  });
});
