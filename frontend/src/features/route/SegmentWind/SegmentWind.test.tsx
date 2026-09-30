import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SegmentWind from "./SegmentWind";

describe("区間の風", () => {
  it("評価に使ったモデルの計算値の時刻・風向・風速を出す", () => {
    render(
      <SegmentWind wind={{ speed_ms: 3.24, direction_deg: 90, forecast_at: "2026-09-26T12:00", extended: false }} />,
    );

    expect(screen.getByText("12:00のモデルの計算値: 東 3.2m/s")).toBeInTheDocument();
    expect(screen.queryByText("[延長]")).not.toBeInTheDocument();
  });

  it("追える時刻の先の区間には、延ばして使ったことを出す", () => {
    render(<SegmentWind wind={{ speed_ms: 3, direction_deg: 0, forecast_at: "2026-09-26T15:00", extended: true }} />);

    expect(screen.getByText("[延長]")).toBeInTheDocument();
  });

  it("時別の値が無く出発時点の値を使った区間は、そう出す", () => {
    render(<SegmentWind wind={{ speed_ms: 2, direction_deg: 180, forecast_at: null, extended: false }} />);

    expect(screen.getByText("出発時点の風: 南 2.0m/s")).toBeInTheDocument();
  });

  it("風を持たない区間には何も出さない", () => {
    const { container } = render(<SegmentWind wind={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});
