import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import RouteForm, { type DestinationButtonState, type RouteMode } from "./RouteForm";

// RouteFormは制御コンポーネント（距離はpage.tsxが持ち、生成条件のdirty判定に使う）のため、
// テストでは距離stateを持つ最小のラッパーで包んで実際の入力操作を再現する。
// 改善計画T365-2: routeMode等も同様に制御propsのため、既定値loop（従来どおり距離入力を
// 表示）でラップする。目的地モード自体の検証は専用describeブロックで行う。
function ControlledRouteForm({
  onGenerate,
  loading,
  initialDistance = "30",
  compact = false,
  initialRouteMode = "loop",
  waypointCount = 0,
  onWaypointsClear = vi.fn(),
  destinationState = "unset",
  onDestinationButtonClick = vi.fn(),
}: {
  onGenerate: (distanceKm: number) => void;
  loading: boolean;
  initialDistance?: string;
  compact?: boolean;
  initialRouteMode?: RouteMode;
  waypointCount?: number;
  onWaypointsClear?: () => void;
  destinationState?: DestinationButtonState;
  onDestinationButtonClick?: () => void;
}) {
  const [distance, setDistance] = useState(initialDistance);
  const [routeMode, setRouteMode] = useState<RouteMode>(initialRouteMode);
  return (
    <RouteForm
      distance={distance}
      onDistanceChange={setDistance}
      onGenerate={onGenerate}
      loading={loading}
      compact={compact}
      routeMode={routeMode}
      onRouteModeChange={setRouteMode}
      waypointCount={waypointCount}
      onWaypointsClear={onWaypointsClear}
      destinationState={destinationState}
      onDestinationButtonClick={onDestinationButtonClick}
    />
  );
}

describe("RouteForm", () => {
  it("初期表示で距離入力のデフォルト値が30、ボタンラベルがルート生成", () => {
    render(<ControlledRouteForm onGenerate={vi.fn()} loading={false} />);

    expect(screen.getByRole("spinbutton")).toHaveValue(30);
    expect(screen.getByRole("button", { name: "ルート生成" })).toBeInTheDocument();
  });

  it("loading=trueのときボタンがdisabledかつ生成中...と表示される", () => {
    render(<ControlledRouteForm onGenerate={vi.fn()} loading={true} />);

    const button = screen.getByRole("button", { name: "生成中..." });
    expect(button).toBeDisabled();
  });

  it("デフォルト値のまま送信するとonGenerateが30(number)で呼ばれる", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(onGenerate).toHaveBeenCalledWith(30);
  });

  it("距離入力を変更してから送信すると変更後の数値でonGenerateが呼ばれる", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

    const input = screen.getByRole("spinbutton");
    await user.clear(input);
    await user.type(input, "50");
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(onGenerate).toHaveBeenCalledWith(50);
  });

  it("距離を0にして送信してもonGenerateは呼ばれない", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

    const input = screen.getByRole("spinbutton");
    await user.clear(input);
    await user.type(input, "0");
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(onGenerate).not.toHaveBeenCalled();
  });

  it("距離を空文字にして送信してもonGenerateは呼ばれない", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

    const input = screen.getByRole("spinbutton");
    await user.clear(input);
    // フォームのsubmitボタンをクリックしてsubmitイベントを発火させる
    // (formのrequestSubmitはHTML標準のnumber inputバリデーションに阻まれる可能性があるため、
    // ここではフォーム要素を直接submitして実装のガード条件を検証する)
    const form = input.closest("form")!;
    form.requestSubmit();

    expect(onGenerate).not.toHaveBeenCalled();
  });

  it("距離を0にして送信するとエラーメッセージが表示される(以前はサイレント失敗だった)", async () => {
    const user = userEvent.setup();
    render(<ControlledRouteForm onGenerate={vi.fn()} loading={false} />);

    const input = screen.getByRole("spinbutton");
    await user.clear(input);
    await user.type(input, "0");
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("距離は0より大きい値を入力してください。");
  });

  it("上限(100km)を超える距離を送信するとonGenerateは呼ばれずエラーが表示される", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

    const input = screen.getByRole("spinbutton");
    await user.clear(input);
    await user.type(input, "150");
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(onGenerate).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent("距離は100km以下で入力してください。");
  });

  describe("compact", () => {
    it("ボタン文言が「生成」に短縮され、距離入力にaria-labelが付く", () => {
      render(<ControlledRouteForm onGenerate={vi.fn()} loading={false} compact />);

      expect(screen.getByRole("button", { name: "生成" })).toBeInTheDocument();
      expect(screen.getByRole("spinbutton", { name: "距離(km)" })).toHaveValue(30);
    });

    it("loading=trueのときボタンが「…」と表示される", () => {
      render(<ControlledRouteForm onGenerate={vi.fn()} loading={true} compact />);

      expect(screen.getByRole("button", { name: "…" })).toBeDisabled();
    });

    it("送信するとonGenerateが呼ばれる(通常版と同じ検証ロジックを共有)", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(<ControlledRouteForm onGenerate={onGenerate} loading={false} compact />);

      await user.click(screen.getByRole("button", { name: "生成" }));

      expect(onGenerate).toHaveBeenCalledWith(30);
    });
  });

  describe("改善計画T365-2: 周回/目的地モード切り替え", () => {
    it("目的地モードに切り替えると距離入力が消え、目的地ボタンが表示される", async () => {
      const user = userEvent.setup();
      render(<ControlledRouteForm onGenerate={vi.fn()} loading={false} />);

      await user.click(screen.getByRole("button", { name: "目的地" }));

      expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "目的地を設定（地図をタップ）" })).toBeInTheDocument();
    });

    it("目的地モードで経由地・目的地とも未指定のまま送信するとエラーになりonGenerateは呼ばれない", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);
      await user.click(screen.getByRole("button", { name: "目的地" }));

      await user.click(screen.getByRole("button", { name: "ルート生成" }));

      expect(onGenerate).not.toHaveBeenCalled();
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "地図をタップして目的地か経由地を指定してください。",
      );
    });

    it("目的地モードでdestinationState=setなら送信でonGenerate(0)が呼ばれる（距離はpage.tsx側で自動算出）", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(
        <ControlledRouteForm onGenerate={onGenerate} loading={false} initialRouteMode="destination" destinationState="set" />,
      );

      await user.click(screen.getByRole("button", { name: "ルート生成" }));

      expect(onGenerate).toHaveBeenCalledWith(0);
    });

    it("目的地モードで経由地が1件以上あれば目的地未設定でも送信できる", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(
        <ControlledRouteForm onGenerate={onGenerate} loading={false} initialRouteMode="destination" waypointCount={1} />,
      );

      await user.click(screen.getByRole("button", { name: "ルート生成" }));

      expect(onGenerate).toHaveBeenCalledWith(0);
    });

    it("経由地クリアボタンでonWaypointsClearが呼ばれる", async () => {
      const user = userEvent.setup();
      const onWaypointsClear = vi.fn();
      render(
        <ControlledRouteForm
          onGenerate={vi.fn()}
          loading={false}
          initialRouteMode="destination"
          waypointCount={2}
          onWaypointsClear={onWaypointsClear}
        />,
      );

      await user.click(screen.getByRole("button", { name: "経由地をクリア" }));

      expect(onWaypointsClear).toHaveBeenCalledTimes(1);
    });

    it("目的地ボタン押下でonDestinationButtonClickが呼ばれる", async () => {
      const user = userEvent.setup();
      const onDestinationButtonClick = vi.fn();
      render(
        <ControlledRouteForm
          onGenerate={vi.fn()}
          loading={false}
          initialRouteMode="destination"
          onDestinationButtonClick={onDestinationButtonClick}
        />,
      );

      await user.click(screen.getByRole("button", { name: "目的地を設定（地図をタップ）" }));

      expect(onDestinationButtonClick).toHaveBeenCalledTimes(1);
    });
  });
});
