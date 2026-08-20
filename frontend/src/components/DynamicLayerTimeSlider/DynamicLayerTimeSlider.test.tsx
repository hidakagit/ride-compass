import { fireEvent, render, screen } from "@testing-library/react";
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
        loading={false}
        loadingLabel="取得中..."
        error="取得に失敗しました"
        ariaLabel="表示時刻"
      />
    );
    expect(screen.getByText("取得に失敗しました")).toBeInTheDocument();
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });

  it("framesがあれば選択中フレームのlabel・badgeを表示する", () => {
    render(
      <DynamicLayerTimeSlider
        frames={FRAMES}
        index={0}
        onIndexChange={vi.fn()}
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
});
