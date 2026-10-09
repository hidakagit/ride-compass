/**
 * 「保存」タブの「地点」（`SavedPlacesPanel.tsx`）——保存した地点を名前と辺りで並べ、「消す」は確認の窓で「消す」を押したときだけ
 * 消す。無ければ無いと出し、保存の仕方を(i)の奥に置く。
 *
 * ここで見ないもの:
 * - 地点の保存と、保存した地点を選んで置くこと → `RouteForm/PointDetail.test.tsx`・`app/page.test.tsx`
 * - (i)の奥の文（書いた文をそのまま出す）
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SavedPlace } from "@/features/route/savedPlaces";

import SavedPlacesPanel from "./SavedPlacesPanel";

const CAFE: SavedPlace = {
  kind: "facility",
  level: "point",
  name: "いつものカフェ",
  area: "文京区本駒込二丁目",
  latitude: 35.73,
  longitude: 139.75,
};
const HOME: SavedPlace = {
  kind: "facility",
  level: "point",
  name: "自宅",
  area: null,
  latitude: 35.75,
  longitude: 139.73,
};

describe("SavedPlacesPanel", () => {
  it("保存した地点を名前と辺りで並べ、無ければ無いと出して保存の仕方を(i)に置く", () => {
    const { rerender } = render(<SavedPlacesPanel places={[CAFE, HOME]} onRemove={() => {}} />);
    expect(screen.getAllByRole("listitem").map((row) => row.textContent)).toEqual([
      `${CAFE.name}${CAFE.area}`,
      HOME.name,
    ]);

    rerender(<SavedPlacesPanel places={[]} onRemove={() => {}} />);
    expect(screen.getByText("保存した地点はまだありません。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "地点の保存の仕方を表示" })).toBeInTheDocument();
  });

  it("「消す」で、確認の窓の「消す」を押したときだけその地点を消す", async () => {
    const onRemove = vi.fn();
    render(<SavedPlacesPanel places={[CAFE, HOME]} onRemove={onRemove} />);
    const confirmDialog = () => screen.getByRole("dialog", { name: "「自宅」を消します" });

    await userEvent.click(screen.getByRole("button", { name: "「自宅」を消す" }));
    await userEvent.click(within(confirmDialog()).getByRole("button", { name: "キャンセル" }));
    expect(onRemove).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "「自宅」を消す" }));
    await userEvent.click(within(confirmDialog()).getByRole("button", { name: "消す" }));

    expect(onRemove).toHaveBeenCalledExactlyOnceWith(HOME);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
