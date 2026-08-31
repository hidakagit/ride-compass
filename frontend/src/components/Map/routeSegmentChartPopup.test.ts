// @vitest-environment node
// routeSegmentChartPopup.tsはDOM操作を一切行わない純粋なHTML文字列生成のみ
// （axisInspectorPopup.test.tsのようなdocument.createElement/querySelectorは不要）のため、
// node環境で実行する（docs/testing.md「フロントエンドの新規テストがDOM…を使わない純ロジック
// なら@vitest-environment nodeを付ける」）。

import { describe, expect, it } from "vitest";

import { buildAxisDifficultyRadarSvg, buildRouteSegmentChartPopupHtml, type RouteSegmentChartSegment } from "./routeSegmentChartPopup";
import { rampColorForValue } from "./axisLayers";

const AXIS_LABELS: Record<string, string> = {
  gradient: "勾配",
  wind: "風",
  surface_q: "舗装質",
  stop_density: "停止密度",
  car_stress: "車の圧迫感",
  accident: "事故密度",
  night: "夜間",
  bicycle_infra_quality: "自転車インフラ",
};

function makeSegment(overrides: Partial<RouteSegmentChartSegment> = {}): RouteSegmentChartSegment {
  return {
    start_latitude: 35.7,
    start_longitude: 139.7,
    end_latitude: 35.71,
    end_longitude: 139.71,
    cumulative_distance_km: 3.2,
    distance_km: 0.5,
    estimated_arrival_time: "2026-08-30T09:15:00+09:00",
    gradient_percent: 4.5,
    wind_penalty: 1.2,
    road_surface_good: true,
    axis_difficulties: {
      car_stress: 25.0,
      stop_density: 50.0,
      accident: 10.0,
      night: 0.0,
      surface_q: 5.0,
      gradient: 60.0,
      wind: 30.0,
      bicycle_infra_quality: 15.0,
    },
    difficulty: 28.0,
    ...overrides,
  };
}

describe("buildRouteSegmentChartPopupHtml", () => {
  it("距離・到達予想時刻・勾配/風/路面の一次情報を含む", () => {
    const html = buildRouteSegmentChartPopupHtml(makeSegment(), AXIS_LABELS);
    expect(html).toContain("3.2 km地点");
    expect(html).toContain("4.5%");
    expect(html).toContain("向かい風 1.2 m/s");
    expect(html).toContain("舗装路");
  });

  it("axis_difficultiesの全軸ぶんレーダーチャート（svg）と凡例（ラベル・値）を含む", () => {
    const html = buildRouteSegmentChartPopupHtml(makeSegment(), AXIS_LABELS);
    expect(html).toContain("<svg");
    for (const [axisId, value] of Object.entries(makeSegment().axis_difficulties)) {
      expect(html).toContain(AXIS_LABELS[axisId]);
      expect(html).toContain(`${value.toFixed(1)}/100`);
    }
    // 勾配・風もaxis_difficultiesに含まれる（一般道路網向けaxis-inspectorでは「算出不可」に
    // なるが、ルート線クリックはルート生成時計算済みの値をそのまま使えるため出せる）。
    expect(html).toContain("勾配");
    expect(html).toContain("風");
  });

  it("axisLabelsに無いaxis_id（軸スタジオのGUI作成軸等）は生のaxis_idのまま表示する（改善計画T320と同じ規約）", () => {
    const html = buildRouteSegmentChartPopupHtml(
      makeSegment({ axis_difficulties: { gui_created_axis: 42.0 } }),
      AXIS_LABELS
    );
    expect(html).toContain("gui_created_axis");
    expect(html).toContain("42.0/100");
  });

  it("axis_difficultiesが空の区間は「算出できませんでした」を表示し、svgは出さない", () => {
    const html = buildRouteSegmentChartPopupHtml(makeSegment({ axis_difficulties: {} }), AXIS_LABELS);
    expect(html).toContain("軸別の内訳を算出できませんでした。");
    expect(html).not.toContain("<svg");
  });

  it("軸が2件以下（3頂点未満）は多角形として意味を持たないためsvgを出さず、凡例のみ表示する", () => {
    const html = buildRouteSegmentChartPopupHtml(
      makeSegment({ axis_difficulties: { gradient: 10.0, wind: 20.0 } }),
      AXIS_LABELS
    );
    expect(html).not.toContain("<svg");
    expect(html).toContain("勾配");
    expect(html).toContain("10.0/100");
  });

  it("値の欠測（estimated_arrival_time/gradient_percent等がnull）はaxisInspectorPopupと同じ「不明/データなし」表記にフォールバックする", () => {
    const html = buildRouteSegmentChartPopupHtml(
      makeSegment({ estimated_arrival_time: null, gradient_percent: null, wind_penalty: null, road_surface_good: null }),
      AXIS_LABELS
    );
    expect(html).toContain("不明");
    expect(html).toContain("データなし");
  });
});

describe("buildAxisDifficultyRadarSvg", () => {
  it("軸数ぶんの頂点circle（軸ごとの色分けドット）を描画する", () => {
    const entries = [
      { axisId: "a", label: "A", value: 0 },
      { axisId: "b", label: "B", value: 50 },
      { axisId: "c", label: "C", value: 100 },
    ];
    const svg = buildAxisDifficultyRadarSvg(entries);
    const circleCount = (svg.match(/<circle/g) ?? []).length;
    expect(circleCount).toBe(3);
  });

  it("頂点の色は統一パレット（rampColorForValue、地図のramp軸と同じ配色）で塗られる", () => {
    const entries = [
      { axisId: "a", label: "A", value: 0 },
      { axisId: "b", label: "B", value: 100 },
      { axisId: "c", label: "C", value: 50 },
    ];
    const svg = buildAxisDifficultyRadarSvg(entries);
    expect(svg).toContain(rampColorForValue(0));
    expect(svg).toContain(rampColorForValue(100));
    expect(svg).toContain(rampColorForValue(50));
  });

  // 改善計画T466: 呼び出し側（buildRouteSegmentChartPopupHtml）の`entries.length >= 3`判定を
  // 経由しない直接呼び出しでも、3軸未満（0軸含む）で例外・破綻せず空文字を返すことを確認する。
  it("3軸未満（多角形として破綻する軸数）は空文字を返す", () => {
    expect(buildAxisDifficultyRadarSvg([])).toBe("");
    expect(buildAxisDifficultyRadarSvg([{ axisId: "a", label: "A", value: 50 }])).toBe("");
    expect(
      buildAxisDifficultyRadarSvg([
        { axisId: "a", label: "A", value: 0 },
        { axisId: "b", label: "B", value: 100 },
      ])
    ).toBe("");
  });
});
