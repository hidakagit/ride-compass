import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import RouteForm, { type DestinationButtonState, type RouteMode } from "./RouteForm";

// RouteFormは制御コンポーネント（距離・候補件数はpage.tsxが持ち、生成条件のdirty判定・
// useRouteFormSubmitでの検証に使う）のため、テストでは各stateを持つ最小のラッパーで包んで
// 実際の入力操作を再現する。T616で生成ボタン・検証ロジックはuseRouteFormSubmitへ抽出した
// ため、本コンポーネントの責務は入力欄（モード切替・距離スライダー・候補数ステッパー）と
// 「生成条件」「重みづけ」タブの表示切替のみ。
function ControlledRouteForm({
  initialDistance = "30",
  initialMaxRoutes = "8",
  initialRouteMode = "loop",
  waypointCount = 0,
  onWaypointsClear = vi.fn(),
  destinationState = "unset",
  onDestinationButtonClick = vi.fn(),
}: {
  initialDistance?: string;
  initialMaxRoutes?: string;
  initialRouteMode?: RouteMode;
  waypointCount?: number;
  onWaypointsClear?: () => void;
  destinationState?: DestinationButtonState;
  onDestinationButtonClick?: () => void;
}) {
  const [distance, setDistance] = useState(initialDistance);
  const [maxRoutes, setMaxRoutes] = useState(initialMaxRoutes);
  const [routeMode, setRouteMode] = useState<RouteMode>(initialRouteMode);
  return (
    <RouteForm
      distance={distance}
      onDistanceChange={setDistance}
      maxRoutes={maxRoutes}
      onMaxRoutesChange={setMaxRoutes}
      routeMode={routeMode}
      onRouteModeChange={setRouteMode}
      waypointCount={waypointCount}
      onWaypointsClear={onWaypointsClear}
      destinationState={destinationState}
      onDestinationButtonClick={onDestinationButtonClick}
      weightsPanel={<p>重みづけタブの中身（テスト用ダミー）</p>}
    />
  );
}

function getDistanceSlider(): HTMLElement {
  return screen.getByRole("slider", { name: "距離" });
}

describe("RouteForm", () => {
  it("初期表示で距離スライダーの値が30、候補数ステッパーの表示が8件", () => {
    render(<ControlledRouteForm />);

    expect(getDistanceSlider()).toHaveValue("30");
    expect(screen.getByText("30km")).toBeInTheDocument();
    expect(screen.getByText("8件")).toBeInTheDocument();
  });

  it("距離スライダーを操作するとonDistanceChangeが呼ばれ、表示値も更新される", () => {
    render(<ControlledRouteForm />);

    // input[type=range]はuserEvent.typeでの打鍵を再現できないため（datetime-local入力と
    // 同種の既知の制約、RideConditionBar.test.tsx参照）fireEvent.changeで値を直接設定する。
    fireEvent.change(getDistanceSlider(), { target: { value: "50" } });

    expect(screen.getByText("50km")).toBeInTheDocument();
  });

  describe("候補数ステッパー", () => {
    it("「›」を押すと候補数が1増える", async () => {
      const user = userEvent.setup();
      render(<ControlledRouteForm />);

      await user.click(screen.getByRole("button", { name: "候補数を増やす" }));

      expect(screen.getByText("9件")).toBeInTheDocument();
    });

    it("「‹」を押すと候補数が1減る", async () => {
      const user = userEvent.setup();
      render(<ControlledRouteForm />);

      await user.click(screen.getByRole("button", { name: "候補数を減らす" }));

      expect(screen.getByText("7件")).toBeInTheDocument();
    });

    it("上限(15件)では「›」が無効化される", () => {
      render(<ControlledRouteForm initialMaxRoutes="15" />);

      expect(screen.getByRole("button", { name: "候補数を増やす" })).toBeDisabled();
    });

    it("下限(1件)では「‹」が無効化される", () => {
      render(<ControlledRouteForm initialMaxRoutes="1" />);

      expect(screen.getByRole("button", { name: "候補数を減らす" })).toBeDisabled();
    });
  });

  describe("改善計画T365-2: 周回/目的地モード切り替え", () => {
    it("目的地モードに切り替えると距離スライダーが消え、目的地ボタンが表示される（候補数は経由地なしのため残る）", async () => {
      const user = userEvent.setup();
      render(<ControlledRouteForm />);

      await user.click(screen.getByRole("button", { name: "目的地" }));

      expect(screen.queryByRole("slider", { name: "距離" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "目的地を設定（地図をタップ）" })).toBeInTheDocument();
      expect(screen.getByText("8件")).toBeInTheDocument();
    });

    it("経由地クリアボタンでonWaypointsClearが呼ばれる", async () => {
      const user = userEvent.setup();
      const onWaypointsClear = vi.fn();
      render(
        <ControlledRouteForm initialRouteMode="destination" waypointCount={2} onWaypointsClear={onWaypointsClear} />
      );

      await user.click(screen.getByRole("button", { name: "経由地をクリア" }));

      expect(onWaypointsClear).toHaveBeenCalledTimes(1);
    });

    it("目的地ボタン押下でonDestinationButtonClickが呼ばれる", async () => {
      const user = userEvent.setup();
      const onDestinationButtonClick = vi.fn();
      render(
        <ControlledRouteForm initialRouteMode="destination" onDestinationButtonClick={onDestinationButtonClick} />
      );

      await user.click(screen.getByRole("button", { name: "目的地を設定（地図をタップ）" }));

      expect(onDestinationButtonClick).toHaveBeenCalledTimes(1);
    });

    it("経由地が1件以上あると候補数ステッパーは表示されない", () => {
      render(<ControlledRouteForm initialRouteMode="destination" waypointCount={1} />);

      expect(screen.queryByRole("button", { name: "候補数を増やす" })).not.toBeInTheDocument();
    });
  });

  describe("「生成条件」「重みづけ」タブ", () => {
    it("既定では「生成条件」タブが選択されている", () => {
      render(<ControlledRouteForm />);

      expect(screen.getByRole("tab", { name: "生成条件" })).toHaveAttribute("aria-selected", "true");
      expect(screen.getByRole("tab", { name: "重みづけ" })).toHaveAttribute("aria-selected", "false");
    });

    it("「重みづけ」タブに切り替えるとweightsPanelの中身が見え、タブの選択状態が入れ替わる", async () => {
      const user = userEvent.setup();
      render(<ControlledRouteForm />);

      await user.click(screen.getByRole("tab", { name: "重みづけ" }));

      expect(screen.getByText("重みづけタブの中身（テスト用ダミー）")).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "重みづけ" })).toHaveAttribute("aria-selected", "true");
      expect(screen.getByRole("tab", { name: "生成条件" })).toHaveAttribute("aria-selected", "false");
    });
  });
});
