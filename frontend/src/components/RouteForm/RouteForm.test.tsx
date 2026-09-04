import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import RouteForm, { type DestinationButtonState, type RouteMode } from "./RouteForm";

// RouteFormは制御コンポーネント（距離・候補件数はpage.tsxが持ち、生成条件のdirty判定に
// 使う）のため、テストでは各stateを持つ最小のラッパーで包んで実際の入力操作を再現する。
// 改善計画T365-2: routeMode等も同様に制御propsのため、既定値loop（従来どおり距離・候補件数
// 入力を表示）でラップする。目的地モード自体の検証は専用describeブロックで行う。
function ControlledRouteForm({
  onGenerate,
  loading,
  initialDistance = "30",
  initialMaxRoutes = "8",
  initialAssumedSpeed = "20",
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
  initialMaxRoutes?: string;
  initialAssumedSpeed?: string;
  compact?: boolean;
  initialRouteMode?: RouteMode;
  waypointCount?: number;
  onWaypointsClear?: () => void;
  destinationState?: DestinationButtonState;
  onDestinationButtonClick?: () => void;
}) {
  const [distance, setDistance] = useState(initialDistance);
  const [maxRoutes, setMaxRoutes] = useState(initialMaxRoutes);
  const [assumedSpeed, setAssumedSpeed] = useState(initialAssumedSpeed);
  const [routeMode, setRouteMode] = useState<RouteMode>(initialRouteMode);
  return (
    <RouteForm
      distance={distance}
      onDistanceChange={setDistance}
      maxRoutes={maxRoutes}
      onMaxRoutesChange={setMaxRoutes}
      assumedSpeed={assumedSpeed}
      onAssumedSpeedChange={setAssumedSpeed}
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

// 周回モードは距離・候補件数の2つの数値入力を持つため、`getAllByRole`で取得し
// 順序（距離が先、候補件数が後、RouteForm.tsxのJSX順）で参照する。
function getDistanceInput(): HTMLElement {
  return screen.getAllByRole("spinbutton")[0];
}
function getMaxRoutesInput(): HTMLElement {
  return screen.getAllByRole("spinbutton")[1];
}

// 巡航速度入力は距離・候補件数の後（JSX順で3番目）。
function getAssumedSpeedInput(): HTMLElement {
  return screen.getAllByRole("spinbutton")[2];
}

describe("巡航速度入力", () => {
  it("初期値は20で、変更して送信するとonGenerateが呼ばれる(速度自体はpage.tsx側がstateから読む)", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

    expect(getAssumedSpeedInput()).toHaveValue(20);
    await user.clear(getAssumedSpeedInput());
    await user.type(getAssumedSpeedInput(), "25");
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(onGenerate).toHaveBeenCalledWith(30);
  });

  it("範囲外の速度で送信するとonGenerateは呼ばれずエラーが表示される", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

    await user.clear(getAssumedSpeedInput());
    await user.type(getAssumedSpeedInput(), "80");
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(onGenerate).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent("巡航速度は5〜60km/hで入力してください。");
  });

  it("空欄で送信するとonGenerateは呼ばれずエラーが表示される", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

    await user.clear(getAssumedSpeedInput());
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(onGenerate).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent("巡航速度は数値で入力してください。");
  });
});

describe("RouteForm", () => {
  it("初期表示で距離入力のデフォルト値が30、候補件数のデフォルト値が8、ボタンラベルがルート生成", () => {
    render(<ControlledRouteForm onGenerate={vi.fn()} loading={false} />);

    expect(getDistanceInput()).toHaveValue(30);
    expect(getMaxRoutesInput()).toHaveValue(8);
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

    const input = getDistanceInput();
    await user.clear(input);
    await user.type(input, "50");
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(onGenerate).toHaveBeenCalledWith(50);
  });

  it("距離を0にして送信してもonGenerateは呼ばれない", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

    const input = getDistanceInput();
    await user.clear(input);
    await user.type(input, "0");
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(onGenerate).not.toHaveBeenCalled();
  });

  it("距離を空文字にして送信してもonGenerateは呼ばれない", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

    const input = getDistanceInput();
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

    const input = getDistanceInput();
    await user.clear(input);
    await user.type(input, "0");
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("距離は0より大きい値を入力してください。");
  });

  it("上限(100km)を超える距離を送信するとonGenerateは呼ばれずエラーが表示される", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

    const input = getDistanceInput();
    await user.clear(input);
    await user.type(input, "150");
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(onGenerate).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent("距離は100km以下で入力してください。");
  });

  describe("改善計画T531: 候補件数入力", () => {
    it("候補件数を変更してから送信するとonGenerateが呼ばれる(距離のみ引数、件数はpage.tsx側がstateから読む)", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

      const input = getMaxRoutesInput();
      await user.clear(input);
      await user.type(input, "3");
      await user.click(screen.getByRole("button", { name: "ルート生成" }));

      expect(onGenerate).toHaveBeenCalledWith(30);
    });

    it("候補件数を空にして送信してもonGenerateは呼ばれずエラーが表示される", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

      const input = getMaxRoutesInput();
      await user.clear(input);
      const form = input.closest("form")!;
      form.requestSubmit();

      expect(onGenerate).not.toHaveBeenCalled();
      expect(await screen.findByRole("alert")).toHaveTextContent("候補件数は整数で入力してください。");
    });

    it("候補件数に小数を入力して送信するとonGenerateは呼ばれずエラーが表示される", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

      const input = getMaxRoutesInput();
      await user.clear(input);
      await user.type(input, "2.5");
      await user.click(screen.getByRole("button", { name: "ルート生成" }));

      expect(onGenerate).not.toHaveBeenCalled();
      expect(await screen.findByRole("alert")).toHaveTextContent("候補件数は整数で入力してください。");
    });

    it("候補件数に0を入力して送信するとonGenerateは呼ばれずエラーが表示される", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

      const input = getMaxRoutesInput();
      await user.clear(input);
      await user.type(input, "0");
      await user.click(screen.getByRole("button", { name: "ルート生成" }));

      expect(onGenerate).not.toHaveBeenCalled();
      expect(await screen.findByRole("alert")).toHaveTextContent("候補件数は1〜15件で入力してください。");
    });

    it("候補件数に上限(15件)を超える値を入力して送信するとonGenerateは呼ばれずエラーが表示される", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

      const input = getMaxRoutesInput();
      await user.clear(input);
      await user.type(input, "16");
      await user.click(screen.getByRole("button", { name: "ルート生成" }));

      expect(onGenerate).not.toHaveBeenCalled();
      expect(await screen.findByRole("alert")).toHaveTextContent("候補件数は1〜15件で入力してください。");
    });

    it("上限(15件)ちょうどなら送信できる", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(<ControlledRouteForm onGenerate={onGenerate} loading={false} />);

      const input = getMaxRoutesInput();
      await user.clear(input);
      await user.type(input, "15");
      await user.click(screen.getByRole("button", { name: "ルート生成" }));

      expect(onGenerate).toHaveBeenCalledWith(30);
    });
  });

  describe("compact", () => {
    it("ボタン文言が「生成」に短縮され、距離・候補件数の各入力にaria-labelが付く", () => {
      render(<ControlledRouteForm onGenerate={vi.fn()} loading={false} compact />);

      expect(screen.getByRole("button", { name: "生成" })).toBeInTheDocument();
      expect(screen.getByRole("spinbutton", { name: "距離(km)" })).toHaveValue(30);
      expect(screen.getByRole("spinbutton", { name: "候補件数" })).toHaveValue(8);
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
    it("目的地モードに切り替えると距離入力が消え、目的地ボタンが表示される（候補件数は経由地なしのため残る）", async () => {
      const user = userEvent.setup();
      render(<ControlledRouteForm onGenerate={vi.fn()} loading={false} />);

      await user.click(screen.getByRole("button", { name: "目的地" }));

      // 距離入力が消え、候補件数・巡航速度の2つが残る。
      expect(screen.getAllByRole("spinbutton")).toHaveLength(2);
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

  describe("目的地モード（経由地なし）の候補件数入力", () => {
    it("経由地が無ければ候補件数入力が表示され、変更した値のまま送信できる", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(
        <ControlledRouteForm onGenerate={onGenerate} loading={false} initialRouteMode="destination" destinationState="set" />,
      );

      const input = screen.getAllByRole("spinbutton")[0];
      await user.clear(input);
      await user.type(input, "3");
      await user.click(screen.getByRole("button", { name: "ルート生成" }));

      expect(input).toHaveValue(3);
      expect(onGenerate).toHaveBeenCalledWith(0);
    });

    it("経由地が1件以上あると候補件数入力は表示されない", () => {
      render(
        <ControlledRouteForm onGenerate={vi.fn()} loading={false} initialRouteMode="destination" waypointCount={1} />,
      );

      // 残る数値入力は巡航速度の1つだけ（候補件数入力は無い）。
      expect(screen.getAllByRole("spinbutton")).toHaveLength(1);
    });

    it("経由地なしで候補件数を空にして送信するとonGenerateは呼ばれずエラーが表示される", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(
        <ControlledRouteForm onGenerate={onGenerate} loading={false} initialRouteMode="destination" destinationState="set" />,
      );

      const input = screen.getAllByRole("spinbutton")[0];
      await user.clear(input);
      const form = input.closest("form")!;
      form.requestSubmit();

      expect(onGenerate).not.toHaveBeenCalled();
      expect(await screen.findByRole("alert")).toHaveTextContent("候補件数は整数で入力してください。");
    });

    it("経由地なしで候補件数に上限(15件)を超える値を入力して送信するとエラーが表示される", async () => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      render(
        <ControlledRouteForm onGenerate={onGenerate} loading={false} initialRouteMode="destination" destinationState="set" />,
      );

      const input = screen.getAllByRole("spinbutton")[0];
      await user.clear(input);
      await user.type(input, "16");
      await user.click(screen.getByRole("button", { name: "ルート生成" }));

      expect(onGenerate).not.toHaveBeenCalled();
      expect(await screen.findByRole("alert")).toHaveTextContent("候補件数は1〜15件で入力してください。");
    });
  });
});
