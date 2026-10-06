import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { getQueryClient } from "@/lib/queryClient";
import { serveAxisCatalog } from "@/testing/backendServer";
import { catalogResponse, dedicatedEntry } from "@/testing/catalogAxes";

import TravelBearingControl from "./TravelBearingControl";

describe("TravelBearingControl", () => {
  it.each([
    [
      "向きで値の変わる評価があれば、その名前で",
      ["bearing_deg"],
      "「評価A」で周りの道を色分けするときと、道の評価を見るときの走る向きを決めます。ルートの評価は、ルートを実際に走る向きで決まります。地図や端末の向きとは連動しません。",
    ],
    ["無ければ評価に触れずに", ["at"], "地図や端末の向きとは連動しません。"],
  ] as const)("走行方位の説明は、%s何に使うかを書く", async (_case, conditions, usage) => {
    serveAxisCatalog(
      catalogResponse([dedicatedEntry("a", [1], { label: "評価A", dynamic_way_value_conditions: [...conditions] })]),
    );
    render(<TravelBearingControl value={0} onChange={vi.fn()} />);
    await waitFor(() => expect(getQueryClient().isFetching()).toBe(0));
    expect(screen.getByRole("button", { name: "走行方位を設定" })).toHaveAttribute("data-usage", usage);
  });
});
