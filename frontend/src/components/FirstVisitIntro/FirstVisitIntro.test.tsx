import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import FirstVisitIntro, { FIRST_VISIT_INTRO_STORAGE_KEY } from "./FirstVisitIntro";

beforeEach(() => {
  localStorage.clear();
});

describe("FirstVisitIntro", () => {
  it("初めて開いたときは、アプリの名前と最初の一手を出す", () => {
    render(<FirstVisitIntro isMobile={false} />);

    const intro = screen.getByRole("region", { name: "RideCompass" });
    expect(intro).toHaveTextContent("左の「ルート設定」");
    expect(intro).toHaveTextContent("「使い方を見る」");
  });

  it("スマホでは、最初の一手を下のタブの場所で言う", () => {
    render(<FirstVisitIntro isMobile />);

    expect(screen.getByRole("region", { name: "RideCompass" })).toHaveTextContent("下の「ルート設定」");
  });

  it.each(["はじめる", "案内を閉じる"])("「%s」で閉じると、開き直しても出ない", async (name) => {
    const user = userEvent.setup();
    const { unmount } = render(<FirstVisitIntro isMobile={false} />);

    await user.click(screen.getByRole("button", { name }));
    expect(screen.queryByRole("region", { name: "RideCompass" })).not.toBeInTheDocument();

    unmount();
    render(<FirstVisitIntro isMobile={false} />);
    expect(screen.queryByRole("region", { name: "RideCompass" })).not.toBeInTheDocument();
  });

  it("前に閉じた端末では出さない", () => {
    localStorage.setItem(FIRST_VISIT_INTRO_STORAGE_KEY, "true");
    render(<FirstVisitIntro isMobile={false} />);

    expect(screen.queryByRole("region", { name: "RideCompass" })).not.toBeInTheDocument();
  });
});
