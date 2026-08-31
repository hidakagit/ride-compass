import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { RouteCandidate } from "@/types/route";
import RouteList from "./RouteList";

function makeRoute(overrides: Partial<RouteCandidate>): RouteCandidate {
  return {
    id: "route-1",
    direction_label: "北",
    distance_km: 30,
    geometry: { type: "LineString", coordinates: [] },
    elevation_gain_m: null,
    min_elevation_m: null,
    max_elevation_m: null,
    max_gradient_percent: null,
    wind_score: null,
    road_score: null,
    total_score: null,
    score_breakdown: null,
    segments: null,
    overall_difficulty: null,
    axis_difficulties: {},
    ...overrides,
  };
}

// 改善計画（ルート結果パネル省スペース化）: RouteList自体が「おすすめ度について」の
// 情報アイコンボタンを持つようになったため、screen.getByRole("button")のような全体
// クエリはこのボタンも拾ってしまう。候補ボタン一覧はul(role="list")配下に限定して
// 取得する。
function getRouteItemButtons() {
  return within(screen.getByRole("list")).getAllByRole("button");
}

describe("RouteList", () => {
  it("候補が無い場合は何も表示しない", () => {
    const { container } = render(<RouteList routes={[]} selectedRouteId={null} onSelect={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("各候補の距離と方向を表示し、選択中の候補をボタンで示す", () => {
    const routes = [makeRoute({ id: "a", direction_label: "北", distance_km: 30.2 }), makeRoute({ id: "b", direction_label: "南", distance_km: 28.5 })];
    render(<RouteList routes={routes} selectedRouteId="a" onSelect={vi.fn()} />);

    expect(screen.getByText(/北方向/)).toBeInTheDocument();
    expect(screen.getByText(/南方向/)).toBeInTheDocument();
    expect(screen.getByText(/30\.2 km/)).toBeInTheDocument();
  });

  it("候補をクリックするとonSelectがそのidで呼ばれる", async () => {
    const user = userEvent.setup();
    const routes = [makeRoute({ id: "a" }), makeRoute({ id: "b" })];
    const onSelect = vi.fn();
    render(<RouteList routes={routes} selectedRouteId="a" onSelect={onSelect} />);

    await user.click(getRouteItemButtons()[1]);

    expect(onSelect).toHaveBeenCalledWith("b");
  });

  // 改善計画T331: 選択状態スタイル・条件付き表示（おすすめ度）の肯定的な検証が無かったため追加。
  describe("選択状態スタイル・条件付き表示（改善計画T331）", () => {
    it("選択中の候補はitemSelectedクラスを持ち、非選択の候補は持たない", () => {
      const routes = [makeRoute({ id: "a" }), makeRoute({ id: "b" })];
      render(<RouteList routes={routes} selectedRouteId="a" onSelect={vi.fn()} />);

      const [buttonA, buttonB] = getRouteItemButtons();
      expect(buttonA.className).toMatch(/itemSelected/);
      expect(buttonB.className).not.toMatch(/itemSelected/);
    });

    it("total_scoreが指定されていればおすすめ度を表示し、nullなら表示しない", () => {
      const routes = [
        makeRoute({ id: "a", total_score: 87.6 }),
        makeRoute({ id: "b", total_score: null }),
      ];
      render(<RouteList routes={routes} selectedRouteId={null} onSelect={vi.fn()} />);

      expect(screen.getByText(/おすすめ度 88点/)).toBeInTheDocument();
      const buttons = getRouteItemButtons();
      expect(buttons[1].textContent).not.toMatch(/おすすめ度/);
    });
  });

  // 改善計画T421: サマリ行を「距離」と「軸による重みづけ（おすすめ度）」の2つへ単純化し、
  // 旧scoring.yaml時代の個別フィールド（獲得標高・風・舗装率）の表示を撤去した。値が
  // 入っていても表示に出てこないことを回帰確認する（T331で足した肯定テストの裏返し）。
  describe("旧scoring.yaml時代の個別フィールドは撤去済み（改善計画T421）", () => {
    it("elevation_gain_m/wind_score/road_scoreが指定されていても候補行に表示しない", () => {
      const routes = [
        makeRoute({ id: "a", elevation_gain_m: 123.4, wind_score: 3.2, road_score: 76.4 }),
      ];
      render(<RouteList routes={routes} selectedRouteId={null} onSelect={vi.fn()} />);

      const [button] = getRouteItemButtons();
      expect(button.textContent).not.toMatch(/獲得標高/);
      expect(button.textContent).not.toMatch(/向かい風|追い風/);
      expect(button.textContent).not.toMatch(/舗装率/);
    });
  });

  describe("おすすめ度説明文（改善計画T421）", () => {
    // ユーザー指示（省スペース化）により、説明文は常時表示ではなく情報アイコンの
    // ポップオーバー（FieldLabel）へ収納した。開くまでは非表示、開くと見えることを確認する
    // （WeightPanel.test.tsxの同種テストと同じパターン）。
    it("情報アイコンを開くと距離側・軸重みづけ側それぞれの説明（description）が見える", async () => {
      const user = userEvent.setup();
      const routes = [makeRoute({ id: "a" })];
      render(<RouteList routes={routes} selectedRouteId={null} onSelect={vi.fn()} />);

      expect(screen.queryByText(/指定距離との差の小ささ/)).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "おすすめ度についての説明を表示" }));

      expect(screen.getByText(/指定距離との差の小ささ/)).toBeInTheDocument();
      expect(screen.getByText(/各軸の重み付け設定で合成した総合難易度/)).toBeInTheDocument();
    });

    it("一般ユーザー向け画面のため、Basic認証必須の管理画面限定機能名「軸スタジオ」を含まない" +
      "（review:ui 2026-08-30 F-4の再発防止）", () => {
      const routes = [makeRoute({ id: "a" })];
      const { container } = render(<RouteList routes={routes} selectedRouteId={null} onSelect={vi.fn()} />);

      expect(container.textContent).not.toContain("軸スタジオ");
    });
  });
});
