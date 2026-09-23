import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import TravelBearingControl from "./TravelBearingControl";

describe("TravelBearingControl（走行方位の入口）", () => {
  it("開く前から、今の走行方位へ矢印を向けて示す", () => {
    render(<TravelBearingControl value={135} onChange={vi.fn()} />);
    const arrow = screen.getByRole("button", { name: "走行方位を設定" }).firstElementChild as HTMLElement;
    expect(arrow.style.transform).toBe("rotate(135deg)");
  });

  it("開くと、今の値の方位のダイヤルが出て、回した値を親へ渡す", async () => {
    const onChange = vi.fn();
    render(<TravelBearingControl value={135} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "走行方位を設定" }));
    const dial = await screen.findByRole("slider", { name: "走行方位" });
    expect(dial).toHaveAttribute("aria-valuenow", "135");
    dial.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith(140);
  });
});
