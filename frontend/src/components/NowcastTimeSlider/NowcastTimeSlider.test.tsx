import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import NowcastTimeSlider from "./NowcastTimeSlider";
import type { NowcastFrame } from "@/components/Map/precipitationNowcast";

const FRAMES: NowcastFrame[] = [
  { basetime: "20260820030000", validtime: "20260820025500", isForecast: false },
  { basetime: "20260820030000", validtime: "20260820030000", isForecast: false },
  { basetime: "20260820030000", validtime: "20260820030500", isForecast: true },
];

describe("NowcastTimeSlider", () => {
  it("loading=trueの間は取得中メッセージを表示し、スライダーは出さない", () => {
    render(<NowcastTimeSlider frames={[]} index={0} onIndexChange={vi.fn()} loading={true} error={null} />);
    expect(screen.getByText("降水ナウキャストの時刻を取得中...")).toBeInTheDocument();
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });

  it("errorがあればエラーメッセージを表示し、スライダーは出さない", () => {
    render(<NowcastTimeSlider frames={[]} index={0} onIndexChange={vi.fn()} loading={false} error="取得に失敗しました" />);
    expect(screen.getByText("取得に失敗しました")).toBeInTheDocument();
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });

  it("framesがあれば選択中フレームの時刻(JST)と実況/予測ラベルを表示する", () => {
    render(<NowcastTimeSlider frames={FRAMES} index={1} onIndexChange={vi.fn()} loading={false} error={null} />);
    // 20260820030000(UTC) = JST 12:00、実況(isForecast=false)
    expect(screen.getByText("12:00")).toBeInTheDocument();
    expect(screen.getByText("実況")).toBeInTheDocument();
  });

  it("予測フレームを選択中は「予測」ラベルになる", () => {
    render(<NowcastTimeSlider frames={FRAMES} index={2} onIndexChange={vi.fn()} loading={false} error={null} />);
    expect(screen.getByText("予測")).toBeInTheDocument();
  });

  it("スライダー操作でonIndexChangeが新しいindexで呼ばれる", () => {
    const onIndexChange = vi.fn();
    render(<NowcastTimeSlider frames={FRAMES} index={0} onIndexChange={onIndexChange} loading={false} error={null} />);

    const slider = screen.getByRole("slider", { name: "降水ナウキャストの表示時刻" });
    expect(slider).toHaveAttribute("min", "0");
    expect(slider).toHaveAttribute("max", "2");
    fireEvent.change(slider, { target: { value: "2" } });
    expect(onIndexChange).toHaveBeenCalledWith(2);
  });
});
