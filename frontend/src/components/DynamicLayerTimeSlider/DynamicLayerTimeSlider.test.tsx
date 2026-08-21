import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import DynamicLayerTimeSlider from "./DynamicLayerTimeSlider";

// jsdomはscrollTo/レイアウトを実装しないため、実際の横スクロールジェスチャー自体
// （マウス/タッチのドラッグで.rulerViewportがスクロールし、慣性が止まったところで
// onIndexChangeが呼ばれる一連の挙動）はここでは検証できない（Playwright実機/ブラウザ
// 確認の領域）。ここではrole="slider"のARIA属性と、代替操作手段であるキーボード操作
// （矢印キー・Home/End）がonIndexChangeを正しく呼ぶことを検証する。

const FRAMES = [{ label: "12:00" }, { label: "12:05" }, { label: "12:10" }];

describe("DynamicLayerTimeSlider", () => {
  it("loading=trueの間はloadingLabelを表示し、スライダーは出さない", () => {
    render(
      <DynamicLayerTimeSlider
        frames={[]}
        index={0}
        onIndexChange={vi.fn()}
        currentIndex={0}
        onNow={vi.fn()}
        loading={true}
        loadingLabel="取得中..."
        error={null}
        ariaLabel="表示時刻"
      />
    );
    expect(screen.getByText("取得中...")).toBeInTheDocument();
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });

  it("errorがあればエラーメッセージを表示し、スライダーは出さない", () => {
    render(
      <DynamicLayerTimeSlider
        frames={[]}
        index={0}
        onIndexChange={vi.fn()}
        currentIndex={0}
        onNow={vi.fn()}
        loading={false}
        loadingLabel="取得中..."
        error="取得に失敗しました"
        ariaLabel="表示時刻"
      />
    );
    expect(screen.getByText("取得に失敗しました")).toBeInTheDocument();
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });

  it("framesがあれば選択中フレームのlabelを表示する（T183: 統合タイムラインの共有ラベルのみ、レイヤー固有のbadgeは廃止）", () => {
    render(
      <DynamicLayerTimeSlider
        frames={FRAMES}
        index={0}
        onIndexChange={vi.fn()}
        currentIndex={0}
        onNow={vi.fn()}
        loading={false}
        loadingLabel="取得中..."
        error={null}
        ariaLabel="表示時刻"
      />
    );
    expect(screen.getByText("12:00")).toBeInTheDocument();
  });

  it("role=sliderでARIA値（min/max/now/text）を反映する", () => {
    render(
      <DynamicLayerTimeSlider
        frames={FRAMES}
        index={1}
        onIndexChange={vi.fn()}
        currentIndex={0}
        onNow={vi.fn()}
        loading={false}
        loadingLabel="取得中..."
        error={null}
        ariaLabel="気象レイヤーの表示時刻"
      />
    );

    const slider = screen.getByRole("slider", { name: "気象レイヤーの表示時刻" });
    expect(slider).toHaveAttribute("aria-valuemin", "0");
    expect(slider).toHaveAttribute("aria-valuemax", "2");
    expect(slider).toHaveAttribute("aria-valuenow", "1");
    expect(slider).toHaveAttribute("aria-valuetext", "12:05");
  });

  describe("キーボード操作（実機フィードバック「横スクロールでメモリの方が移動するように」を受け、input[type=range]の代わりにドラッグ位置を直接扱うルーラーへ置き換えたため、矢印キー等の代替操作を自前で用意している）", () => {
    it("ArrowRight/ArrowLeftで1コマ前後にonIndexChangeが呼ばれる", () => {
      const onIndexChange = vi.fn();
      render(
        <DynamicLayerTimeSlider
          frames={FRAMES}
          index={1}
          onIndexChange={onIndexChange}
          currentIndex={0}
          onNow={vi.fn()}
          loading={false}
          loadingLabel="取得中..."
          error={null}
          ariaLabel="気象レイヤーの表示時刻"
        />
      );
      const slider = screen.getByRole("slider", { name: "気象レイヤーの表示時刻" });

      fireEvent.keyDown(slider, { key: "ArrowRight" });
      expect(onIndexChange).toHaveBeenCalledWith(2);

      fireEvent.keyDown(slider, { key: "ArrowLeft" });
      expect(onIndexChange).toHaveBeenCalledWith(0);
    });

    it("両端では境界を超えて呼ばれない", () => {
      const onIndexChange = vi.fn();
      render(
        <DynamicLayerTimeSlider
          frames={FRAMES}
          index={2}
          onIndexChange={onIndexChange}
          currentIndex={0}
          onNow={vi.fn()}
          loading={false}
          loadingLabel="取得中..."
          error={null}
          ariaLabel="気象レイヤーの表示時刻"
        />
      );
      fireEvent.keyDown(screen.getByRole("slider", { name: "気象レイヤーの表示時刻" }), { key: "ArrowRight" });
      expect(onIndexChange).not.toHaveBeenCalled();
    });

    it("Home/Endで両端へ直接移動する", () => {
      const onIndexChange = vi.fn();
      render(
        <DynamicLayerTimeSlider
          frames={FRAMES}
          index={1}
          onIndexChange={onIndexChange}
          currentIndex={0}
          onNow={vi.fn()}
          loading={false}
          loadingLabel="取得中..."
          error={null}
          ariaLabel="気象レイヤーの表示時刻"
        />
      );
      const slider = screen.getByRole("slider", { name: "気象レイヤーの表示時刻" });

      fireEvent.keyDown(slider, { key: "Home" });
      expect(onIndexChange).toHaveBeenCalledWith(0);

      fireEvent.keyDown(slider, { key: "End" });
      expect(onIndexChange).toHaveBeenCalledWith(2);
    });
  });

  describe("「現在」に戻るボタン（実機フィードバック「現況に戻すボタンも横に追加して」「現在リセットすると23:00になって上バーが消えた」）", () => {
    it("index===currentIndexのときは無効化される", () => {
      render(
        <DynamicLayerTimeSlider
          frames={FRAMES}
          index={1}
          onIndexChange={vi.fn()}
          currentIndex={1}
          onNow={vi.fn()}
          loading={false}
          loadingLabel="取得中..."
          error={null}
          ariaLabel="気象レイヤーの表示時刻"
        />
      );
      expect(screen.getByRole("button", { name: "気象レイヤーの表示時刻を現在に戻す" })).toBeDisabled();
    });

    it("未来側を見ているときは有効化され、押すとonNowが呼ばれる（onIndexChangeではない。風のcurrentIndexは実時刻より最大59分過去の正時に丸まるため、そこへ合わせると降水側が範囲外になる不具合があった）", async () => {
      const user = userEvent.setup();
      const onIndexChange = vi.fn();
      const onNow = vi.fn();
      render(
        <DynamicLayerTimeSlider
          frames={FRAMES}
          index={2}
          onIndexChange={onIndexChange}
          currentIndex={1}
          onNow={onNow}
          loading={false}
          loadingLabel="取得中..."
          error={null}
          ariaLabel="気象レイヤーの表示時刻"
        />
      );

      const nowButton = screen.getByRole("button", { name: "気象レイヤーの表示時刻を現在に戻す" });
      expect(nowButton).not.toBeDisabled();
      await user.click(nowButton);
      expect(onNow).toHaveBeenCalledTimes(1);
      expect(onIndexChange).not.toHaveBeenCalled();
    });
  });
});
