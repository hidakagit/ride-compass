import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import DynamicLayerTimeSlider from "./DynamicLayerTimeSlider";

const FRAMES = [
  { label: "12:00", badge: "実況" },
  { label: "12:05", badge: "実況" },
  { label: "12:10", badge: "予測" },
];

describe("DynamicLayerTimeSlider", () => {
  it("loading=trueの間はloadingLabelを表示し、スライダーは出さない", () => {
    render(
      <DynamicLayerTimeSlider
        frames={[]}
        index={0}
        onIndexChange={vi.fn()}
        currentIndex={0}
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
        loading={false}
        loadingLabel="取得中..."
        error="取得に失敗しました"
        ariaLabel="表示時刻"
      />
    );
    expect(screen.getByText("取得に失敗しました")).toBeInTheDocument();
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });

  it("unavailable=trueのときはunavailableLabelを表示し、スライダーは出さない（下部バー2本の時刻連動、実機フィードバック「対応データなしと明示する」）", () => {
    render(
      <DynamicLayerTimeSlider
        frames={FRAMES}
        index={0}
        onIndexChange={vi.fn()}
        currentIndex={0}
        loading={false}
        loadingLabel="取得中..."
        error={null}
        unavailable={true}
        unavailableLabel="この時刻のデータはありません"
        ariaLabel="表示時刻"
      />
    );
    expect(screen.getByText("この時刻のデータはありません")).toBeInTheDocument();
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });

  it("framesがあれば選択中フレームのlabel・badgeを表示する", () => {
    render(
      <DynamicLayerTimeSlider
        frames={FRAMES}
        index={0}
        onIndexChange={vi.fn()}
        currentIndex={0}
        loading={false}
        loadingLabel="取得中..."
        error={null}
        ariaLabel="表示時刻"
      />
    );
    expect(screen.getByText("12:00")).toBeInTheDocument();
    expect(screen.getByText("実況")).toBeInTheDocument();
  });

  it("badgeが無いフレームはバッジ無しで表示する", () => {
    render(
      <DynamicLayerTimeSlider
        frames={[{ label: "8/21 09:00" }]}
        index={0}
        onIndexChange={vi.fn()}
        currentIndex={0}
        loading={false}
        loadingLabel="取得中..."
        error={null}
        ariaLabel="表示時刻"
      />
    );
    expect(screen.getByText("8/21 09:00")).toBeInTheDocument();
  });

  it("スライダー操作でonIndexChangeが新しいindexで呼ばれる", () => {
    const onIndexChange = vi.fn();
    render(
      <DynamicLayerTimeSlider
        frames={FRAMES}
        index={0}
        onIndexChange={onIndexChange}
        currentIndex={0}
        loading={false}
        loadingLabel="取得中..."
        error={null}
        ariaLabel="降水ナウキャストの表示時刻"
      />
    );

    const slider = screen.getByRole("slider", { name: "降水ナウキャストの表示時刻" });
    expect(slider).toHaveAttribute("min", "0");
    expect(slider).toHaveAttribute("max", "2");
    fireEvent.change(slider, { target: { value: "2" } });
    expect(onIndexChange).toHaveBeenCalledWith(2);
  });

  describe("「現在」に戻るボタン（実機フィードバック「現況に戻すボタンも横に追加して」）", () => {
    it("index===currentIndexのときは無効化される", () => {
      render(
        <DynamicLayerTimeSlider
          frames={FRAMES}
          index={1}
          onIndexChange={vi.fn()}
          currentIndex={1}
          loading={false}
          loadingLabel="取得中..."
          error={null}
          ariaLabel="降水ナウキャストの表示時刻"
        />
      );
      expect(screen.getByRole("button", { name: "降水ナウキャストの表示時刻を現在に戻す" })).toBeDisabled();
    });

    it("未来側を見ているときは有効化され、押すとcurrentIndexへonIndexChangeが呼ばれる", async () => {
      const user = userEvent.setup();
      const onIndexChange = vi.fn();
      render(
        <DynamicLayerTimeSlider
          frames={FRAMES}
          index={2}
          onIndexChange={onIndexChange}
          currentIndex={1}
          loading={false}
          loadingLabel="取得中..."
          error={null}
          ariaLabel="降水ナウキャストの表示時刻"
        />
      );

      const nowButton = screen.getByRole("button", { name: "降水ナウキャストの表示時刻を現在に戻す" });
      expect(nowButton).not.toBeDisabled();
      await user.click(nowButton);
      expect(onIndexChange).toHaveBeenCalledWith(1);
    });
  });
});
