/**
 * `features/route/EditDifference/EditDifference.tsx`——編集で作ったルートの中身の先頭に出す「元との違い」。
 *
 * 見るもの: 元の名前と距離・変えた区間の数、指標ごとの差の書き方（桁・単位・値の無い側があれば「—」）と増減の印
 * （表示する桁で丸めた値で決める）、変えた区間ごとの元の位置と長さの差、「元を見る」で元へ切り替える操作が上がること。
 *
 * ここで見ないもの: 差の求め方（Edge id列の差・座標からの距離） → `features/route/routeEditDiff.ts`。
 * 増減の印の色 → スタイル（テスト環境はTailwindを通さない）。
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { makeRouteCandidate } from "@/testing/routeFixtures";
import type { RouteCandidate } from "@/types/route";
import EditDifference from "./EditDifference";

// 赤道沿いの0.01度ずつの格子（1辺が約1.11km）。元は経度0の上をまっすぐ北へ3辺、編集後は2辺目を東へ回り込む3辺へ
// 差し替える（元の約1.1〜2.2kmの1区間が、約1.1kmから約3.3kmへ伸びる）。
const STRAIGHT: RouteCandidate["geometry"] = {
  type: "LineString",
  coordinates: [
    [0, 0],
    [0, 0.01],
    [0, 0.02],
    [0, 0.03],
  ],
};
const DETOUR: RouteCandidate["geometry"] = {
  type: "LineString",
  coordinates: [
    [0, 0],
    [0, 0.01],
    [0.01, 0.01],
    [0.01, 0.02],
    [0, 0.02],
    [0, 0.03],
  ],
};

function origin(overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return makeRouteCandidate({
    id: "origin",
    distance_km: 10,
    estimated_duration_seconds: 3600,
    overall_difficulty: { average: 40, load: 400 },
    geometry: STRAIGHT,
    edge_ids: ["a", "b", "c"],
    edge_point_offsets: [0, 1, 2, 3],
    ...overrides,
  });
}

function edited(overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return makeRouteCandidate({
    id: "edited",
    distance_km: 12.34,
    estimated_duration_seconds: 3000,
    overall_difficulty: { average: 40.2, load: 380 },
    geometry: DETOUR,
    edge_ids: ["a", "x", "y", "z", "c"],
    edge_point_offsets: [0, 1, 2, 3, 4, 5],
    ...overrides,
  });
}

function renderDifference(props: Partial<React.ComponentProps<typeof EditDifference>> = {}) {
  const onShowOrigin = vi.fn();
  render(<EditDifference originName="2" origin={origin()} edited={edited()} onShowOrigin={onShowOrigin} {...props} />);
  return { onShowOrigin };
}

/** 指標の見出し（`dt`）の隣の値（`dd`）。 */
function metric(label: string): HTMLElement {
  const term = within(screen.getByRole("region", { name: "元との違い" })).getByText(label, { selector: "dt" });
  return term.nextElementSibling as HTMLElement;
}

describe("EditDifference", () => {
  it("元の名前と距離（小数1桁）、変えた区間の数を出す", () => {
    renderDifference({ originName: "最速" });
    expect(screen.getByText("元: 最速 10.0km")).toBeInTheDocument();
    expect(screen.getByText("から1区間")).toBeInTheDocument();
  });

  it("差は指標ごとの桁と単位で符号付きに書き、増えたら悪化・減ったら改善の印、表示する桁で0に丸まれば「±0」で印を付けない", () => {
    renderDifference();
    expect(metric("距離")).toHaveTextContent("+2.3km");
    expect(metric("距離")).toHaveAttribute("data-worse", "true");
    expect(metric("所要")).toHaveTextContent("−10分");
    expect(metric("所要")).toHaveAttribute("data-better", "true");
    expect(metric("負荷")).toHaveTextContent("−20");
    expect(metric("総合難易度")).toHaveTextContent("±0");
    expect(metric("総合難易度")).toHaveAttribute("data-worse", "false");
    expect(metric("総合難易度")).toHaveAttribute("data-better", "false");
  });

  it("どちらかが値を持たない指標は「—」で、印を付けない", () => {
    renderDifference({ origin: origin({ estimated_duration_seconds: null }) });
    expect(metric("所要")).toHaveTextContent("—");
    expect(metric("所要")).toHaveAttribute("data-worse", "false");
    expect(metric("所要")).toHaveAttribute("data-better", "false");
  });

  it("変えた区間ごとに、元の何km〜何kmかと長さの差を出す", () => {
    renderDifference();
    const item = screen.getByRole("listitem");
    expect(item).toHaveTextContent("1.1〜2.2km");
    expect(item).toHaveTextContent("+2.2km");
  });

  it("「元を見る」で元のルートへ切り替える操作を上げる", async () => {
    const { onShowOrigin } = renderDifference();
    await userEvent.click(screen.getByRole("button", { name: "元を見る" }));
    expect(onShowOrigin).toHaveBeenCalledTimes(1);
  });
});
