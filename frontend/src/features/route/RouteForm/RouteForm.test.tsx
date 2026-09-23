import { useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import RouteForm, { type SettingsTab } from "./RouteForm";
import type { RouteMode } from "./useRouteFormSubmit";

// RouteFormは制御コンポーネント（距離・候補件数はpage.tsxが持ち、生成条件のdirty判定・
// useRouteFormSubmitでの検証に使う）のため、テストでは各stateを持つ最小のラッパーで包んで
// 実際の入力操作を再現する。T616で生成ボタン・検証ロジックはuseRouteFormSubmitへ抽出した
// ため、本コンポーネントの責務は入力欄（モード切替・距離スライダー・候補数ステッパー）と
// 各タブの中身の描画のみ。タブ列と選択状態はpage.tsxが持つ（見出し行に置くため）ので、
// ここではTabs.Rootで包んで「条件」タブを選んだ状態を与える。
function ControlledRouteForm({
  initialDistance = "30",
  initialMaxRoutes = "8",
  initialRouteMode = "loop",
  waypointCount = 0,
  onWaypointsClear = vi.fn(),
  destinationSet = false,
  armedPinRole = null,
  onDestinationClear = () => {},
  onArmPinRole = vi.fn(),
  tab = "generate",
}: {
  initialDistance?: string;
  initialMaxRoutes?: string;
  initialRouteMode?: RouteMode;
  waypointCount?: number;
  onWaypointsClear?: () => void;
  destinationSet?: boolean;
  armedPinRole?: "origin" | "waypoint" | "destination" | null;
  onDestinationClear?: () => void;
  onArmPinRole?: (role: "origin" | "waypoint" | "destination" | null) => void;
  tab?: SettingsTab;
}) {
  const [distance, setDistance] = useState(initialDistance);
  const [maxRoutes, setMaxRoutes] = useState(initialMaxRoutes);
  const [routeMode, setRouteMode] = useState<RouteMode>(initialRouteMode);
  return (
    <Tabs.Root value={tab}>
      <RouteForm
        distance={distance}
        onDistanceChange={setDistance}
        maxRoutes={maxRoutes}
        onMaxRoutesChange={setMaxRoutes}
        routeMode={routeMode}
        onRouteModeChange={setRouteMode}
        waypointCount={waypointCount}
        onWaypointsClear={onWaypointsClear}
        destinationSet={destinationSet}
        originManual={false}
        originLocated
        onOriginReset={() => {}}
        armedPinRole={armedPinRole}
        onArmPinRole={onArmPinRole}
        onDestinationClear={onDestinationClear}
        weightsPanel={<p>重みタブの中身（テスト用ダミー）</p>}
        exclusionsPanel={<p>除外タブの中身（テスト用ダミー）</p>}
      />
    </Tabs.Root>
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
    it("目的地モードに切り替えると距離スライダーが消え、3つの地点の行が出る", async () => {
      const user = userEvent.setup();
      render(<ControlledRouteForm />);

      await user.click(screen.getByRole("radio", { name: "目的地" }));

      expect(screen.queryByRole("slider", { name: "距離" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "出発地を地図で選ぶ" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "経由地を追加" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "目的地を地図で選ぶ" })).toBeInTheDocument();
    });

    // 3つとも同じ形の行で、置いてあるかどうかは行の値で読める（地図を見に行かなくて済む）。
    it("各行は現在の値を示し、目的地を置くと「置き直す」へ変わる", () => {
      const { rerender } = render(<ControlledRouteForm initialRouteMode="destination" />);

      expect(screen.getByText("現在地")).toBeInTheDocument();
      expect(screen.getByText("なし")).toBeInTheDocument();
      expect(screen.getByText("未設定")).toBeInTheDocument();

      rerender(<ControlledRouteForm initialRouteMode="destination" destinationSet waypointCount={2} />);

      expect(screen.getByText("2地点")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "目的地を置き直す" })).toBeInTheDocument();
    });

    // 置ける状態の行は1つだけで、その行の操作は「やめる」に変わる（何を置こうとしているかが
    // 行の形で分かる）。
    it("武装中の行だけが「やめる」になり、押すと解除を親へ渡す", async () => {
      const user = userEvent.setup();
      const onArmPinRole = vi.fn();
      render(
        <ControlledRouteForm initialRouteMode="destination" armedPinRole="waypoint" onArmPinRole={onArmPinRole} />,
      );

      expect(screen.getByRole("button", { name: "経由地の指定をやめる" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "目的地を地図で選ぶ" })).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "経由地の指定をやめる" }));

      expect(onArmPinRole).toHaveBeenCalledWith(null);
    });

    it("行の操作でその役割の武装を親へ渡す", async () => {
      const user = userEvent.setup();
      const onArmPinRole = vi.fn();
      render(<ControlledRouteForm initialRouteMode="destination" onArmPinRole={onArmPinRole} />);

      await user.click(screen.getByRole("button", { name: "出発地を地図で選ぶ" }));

      expect(onArmPinRole).toHaveBeenCalledWith("origin");
    });

    it("目的地の✕でonDestinationClearが呼ばれる", async () => {
      const user = userEvent.setup();
      const onDestinationClear = vi.fn();
      render(
        <ControlledRouteForm initialRouteMode="destination" destinationSet onDestinationClear={onDestinationClear} />,
      );

      await user.click(screen.getByRole("button", { name: "目的地をクリア" }));

      expect(onDestinationClear).toHaveBeenCalledTimes(1);
    });

    it("経由地クリアボタンでonWaypointsClearが呼ばれる", async () => {
      const user = userEvent.setup();
      const onWaypointsClear = vi.fn();
      render(
        <ControlledRouteForm initialRouteMode="destination" waypointCount={2} onWaypointsClear={onWaypointsClear} />,
      );

      await user.click(screen.getByRole("button", { name: "経由地をクリア" }));

      expect(onWaypointsClear).toHaveBeenCalledTimes(1);
    });

    // 経由地があるとbackendは常に1件へ固定する。消すと壊れて見えるため、押せない状態で
    // 残し、理由は隣の(i)の奥に置く。
    it("経由地が1件以上あると候補数ステッパーは押せなくなる", () => {
      render(<ControlledRouteForm initialRouteMode="destination" waypointCount={1} />);

      expect(screen.getByRole("button", { name: "候補数を増やす" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "候補数を減らす" })).toBeDisabled();
      expect(screen.getByText("1件")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^候補数を変えられない理由を/ })).toBeInTheDocument();
    });

    it("経由地が無ければ候補数は押せる", () => {
      render(<ControlledRouteForm initialRouteMode="destination" />);

      expect(screen.getByRole("button", { name: "候補数を増やす" })).toBeEnabled();
      expect(screen.queryByRole("button", { name: /^候補数を変えられない理由を/ })).not.toBeInTheDocument();
    });
  });
  // タブ列と選択状態はpage.tsxが持つ（見出し行に置くため）。ここでは選ばれたタブの中身
  // だけが見える状態になることを見る（どのタブもforceMountで常時マウントされるため、
  // 「出ている/出ていない」はdata-stateで切り替わる）。
  describe("タブの中身", () => {
    it("「重み」タブが選ばれていると重みづけの中身が見える", () => {
      render(<ControlledRouteForm tab="weights" />);

      expect(screen.getByText("重みタブの中身（テスト用ダミー）").closest("[data-state]")).toHaveAttribute(
        "data-state",
        "active",
      );
      expect(screen.getByText("除外タブの中身（テスト用ダミー）").closest("[data-state]")).toHaveAttribute(
        "data-state",
        "inactive",
      );
    });

    it("「除外」タブが選ばれていると除外の中身が見える", () => {
      render(<ControlledRouteForm tab="exclusions" />);

      expect(screen.getByText("除外タブの中身（テスト用ダミー）").closest("[data-state]")).toHaveAttribute(
        "data-state",
        "active",
      );
    });
  });
});
