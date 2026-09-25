import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SegmentWind from "./SegmentWind";

describe("区間の風", () => {
  it("評価に使った予報の時刻・風向・風速を出す", () => {
    render(
      <SegmentWind wind={{ speed_ms: 3.24, direction_deg: 90, forecast_at: "2026-09-26T12:00", extended: false }} />,
    );

    expect(screen.getByText("風 12:00の予報・東の風 3.2m/s")).toBeInTheDocument();
    expect(screen.queryByText("（予報の先を延ばして使用）")).not.toBeInTheDocument();
  });

  it("予報を追える範囲の先の区間には、延ばして使ったことを出す", () => {
    render(<SegmentWind wind={{ speed_ms: 3, direction_deg: 0, forecast_at: "2026-09-26T15:00", extended: true }} />);

    expect(screen.getByText("（予報の先を延ばして使用）")).toBeInTheDocument();
  });

  it("時別の予報が無く出発時点の値を使った区間は、そう出す", () => {
    render(<SegmentWind wind={{ speed_ms: 2, direction_deg: 180, forecast_at: null, extended: false }} />);

    expect(screen.getByText("風 出発時点の風・南の風 2.0m/s")).toBeInTheDocument();
  });

  it("風を持たない区間には何も出さない", () => {
    const { container } = render(<SegmentWind wind={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});
