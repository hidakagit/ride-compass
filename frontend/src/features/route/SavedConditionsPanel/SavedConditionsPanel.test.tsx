/**
 * 「保存」タブ（`SavedConditionsPanel.tsx`）——名前の欄に仮の名前を入れて出し、そのまま・書き換えて保存できる。
 * 同じ名前があれば上書きと分かるように出す。保存した条件を並べ、行で呼び出し、✕で消す。
 *
 * ここで見ないもの:
 * - 保存・呼び出し・削除で条件と一覧がどう変わるか → `useSavedConditions.test.ts`
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import type { SavedCondition } from "@/features/route/savedConditions";

import SavedConditionsPanel from "./SavedConditionsPanel";

const LOOP: SavedCondition = {
  name: "朝の荒川",
  routeMode: "loop",
  distance: "40",
  maxRoutes: "8",
  origin: null,
  waypoints: [],
  destination: null,
  routePreference: null,
  hardFilters: DEFAULT_HARD_FILTERS,
};
const POINT = { latitude: 35.1, longitude: 139.1 };
const TRIP: SavedCondition = {
  ...LOOP,
  name: "週末",
  routeMode: "destination",
  origin: POINT,
  waypoints: [POINT, POINT],
};

function renderPanel(saved: SavedCondition[] = [], suggestedName = "周回 30km") {
  const handlers = { onSave: vi.fn(), onRecall: vi.fn(), onRemove: vi.fn() };
  render(<SavedConditionsPanel saved={saved} suggestedName={suggestedName} {...handlers} />);
  return handlers;
}

describe("保存", () => {
  it("仮の名前が入った欄をそのまま保存でき、書き換えればその名前で保存する", async () => {
    const { onSave } = renderPanel();
    const nameField = screen.getByRole("textbox", { name: "保存する名前" });
    expect(nameField).toHaveValue("周回 30km");

    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(onSave).toHaveBeenLastCalledWith("周回 30km");

    await userEvent.clear(nameField);
    await userEvent.type(nameField, "夕方{Enter}");
    expect(onSave).toHaveBeenLastCalledWith("夕方");
    expect(nameField).toHaveValue("周回 30km");
  });

  it("同じ名前の条件があれば、保存のボタンが上書きになる", async () => {
    renderPanel([LOOP]);
    const nameField = screen.getByRole("textbox", { name: "保存する名前" });

    await userEvent.clear(nameField);
    await userEvent.type(nameField, "朝の荒川");

    expect(screen.getByRole("button", { name: "上書き" })).toBeInTheDocument();
  });
});

describe("保存した条件", () => {
  it("無いうちはまだ無いと出す", () => {
    renderPanel();

    expect(screen.getByText("まだありません。")).toBeInTheDocument();
  });

  it("行に名前と中身の説明を出し、押すと呼び出して呼び出したことを出す", async () => {
    const { onRecall } = renderPanel([LOOP, TRIP]);

    expect(screen.getByRole("button", { name: "「朝の荒川」を呼び出す" })).toHaveTextContent("周回 40km・現在地から");
    const trip = screen.getByRole("button", { name: "「週末」を呼び出す" });
    expect(trip).toHaveTextContent("目的地・経由2地点・地図で置いた出発地から");

    await userEvent.click(trip);

    expect(onRecall).toHaveBeenCalledExactlyOnceWith(TRIP);
    expect(screen.getByRole("status")).toHaveTextContent("「週末」の条件にしました。");
  });

  it("✕で、その行の名前を消す", async () => {
    const { onRemove, onRecall } = renderPanel([LOOP, TRIP]);

    await userEvent.click(screen.getByRole("button", { name: "「週末」を消す" }));

    expect(onRemove).toHaveBeenCalledExactlyOnceWith("週末");
    expect(onRecall).not.toHaveBeenCalled();
  });
});
