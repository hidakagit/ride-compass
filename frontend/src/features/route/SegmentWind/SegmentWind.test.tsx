/**
 * `features/route/SegmentWind/SegmentWind.tsx`——区間の詳細に出す、その区間の評価に使った風。
 *
 * 見るもの: 風の値が無ければ何も描かないこと、どの時刻の値か（出発時点・モデルの計算値の時刻を日本時間で）、
 * 方位の呼び名と風速（小数1桁）、追える時刻の先で延ばした印。
 *
 * ここで見ないもの: 角度から方位の呼び名への丸め → `lib/cardinalLabel.ts`。時刻の書き方 → `lib/time.ts`。
 * (i)の開閉と名前 → `components/ui/InfoPopover`。(i)の説明の文は生成物の値をそのまま差し込むだけなので見ない。
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { cardinalLabel } from "@/lib/cardinalLabel";
import type { RouteSegmentDetail } from "@/types/route";
import SegmentWind from "./SegmentWind";

type Wind = NonNullable<RouteSegmentDetail["wind"]>;

function wind(overrides: Partial<Wind> = {}): Wind {
  return { speed_ms: 0, direction_deg: 0, forecast_at: null, extended: false, ...overrides };
}

describe("SegmentWind", () => {
  it("風の値が無い区間（backendが値を返さない）では何も描かない", () => {
    const { container } = render(<SegmentWind wind={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    [null, "出発時点の風"],
    ["2026-10-04T09:05", "09:05のモデルの計算値"],
  ])("計算値の時刻が%sなら「%s」として、方位の呼び名と小数1桁の風速を出す", (forecastAt, when) => {
    render(<SegmentWind wind={wind({ forecast_at: forecastAt, direction_deg: 180, speed_ms: 3.26 })} />);
    expect(screen.getByText(`${when}: ${cardinalLabel(180)} 3.3m/s`)).toBeInTheDocument();
  });

  it("追える時刻の先で延ばして使った区間にだけ「延長」の印を付ける", () => {
    const { rerender } = render(<SegmentWind wind={wind({ extended: true })} />);
    expect(screen.getByText("[延長]")).toBeInTheDocument();
    rerender(<SegmentWind wind={wind({ extended: false })} />);
    expect(screen.queryByText("[延長]")).not.toBeInTheDocument();
  });
});
