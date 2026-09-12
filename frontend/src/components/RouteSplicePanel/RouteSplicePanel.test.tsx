import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { RouteCandidate } from "@/types/route";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import RouteSplicePanel from "./RouteSplicePanel";

function candidate(id: string, edgeIds: string[]): RouteCandidate {
  return makeRouteCandidate({
    id,
    direction_label: id === "route-00" ? "目的地ルート" : "代替ルート",
    distance_km: 24.5,
    edge_ids: edgeIds,
  });
}

function baseProps(overrides: Partial<Parameters<typeof RouteSplicePanel>[0]> = {}) {
  return {
    displayed: candidate("route-00", ["a", "b", "c"]),
    targets: [candidate("route-01", ["a", "x", "c"])],
    targetId: null as string | null,
    onSelectTarget: vi.fn(),
    stretches: [],
    takenIndexes: [],
    onToggleStretch: vi.fn(),
    onApply: vi.fn(),
    applying: false,
    ...overrides,
  };
}

describe("RouteSplicePanel", () => {
  it("比較相手を選ぶまでは区間を出さない", () => {
    render(<RouteSplicePanel {...baseProps()} />);

    expect(screen.getByText(/比較相手を選ぶと/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /区間/ })).toBeNull();
  });

  it("相手を選ぶとその候補が親へ渡る", async () => {
    const onSelectTarget = vi.fn();
    render(<RouteSplicePanel {...baseProps({ onSelectTarget })} />);

    await userEvent.selectOptions(screen.getByLabelText("比較相手"), "route-01");

    expect(onSelectTarget).toHaveBeenCalledWith("route-01");
  });

  it("同じ道だけを通る2本ではその旨を出す", () => {
    render(<RouteSplicePanel {...baseProps({ targetId: "route-01", stretches: [] })} />);

    expect(screen.getByText("この2本は同じ道を通ります。")).toBeInTheDocument();
  });

  it("押した区間の位置が親へ渡る", async () => {
    // 位置を取り違えると、地図で光っている帯と実際に差し替わる区間がずれる
    const onToggleStretch = vi.fn();
    render(
      <RouteSplicePanel
        {...baseProps({
          targetId: "route-01",
          stretches: [
            { start: 1, end: 2 },
            { start: 4, end: 6 },
          ],
          onToggleStretch,
        })}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /2本目の区間/ }));

    expect(onToggleStretch).toHaveBeenCalledWith(1);
  });

  it("区間を1つも選んでいなければ候補へ追加できない", () => {
    render(<RouteSplicePanel {...baseProps({ targetId: "route-01", stretches: [{ start: 1, end: 2 }] })} />);

    expect(screen.getByRole("button", { name: /候補へ追加/ })).toBeDisabled();
  });

  it("選んだ区間があれば追加でき、評価中は押せない", () => {
    const { rerender } = render(
      <RouteSplicePanel
        {...baseProps({ targetId: "route-01", stretches: [{ start: 1, end: 2 }], takenIndexes: [0] })}
      />,
    );
    expect(screen.getByRole("button", { name: /候補へ追加/ })).toBeEnabled();

    rerender(
      <RouteSplicePanel
        {...baseProps({
          targetId: "route-01",
          stretches: [{ start: 1, end: 2 }],
          takenIndexes: [0],
          applying: true,
        })}
      />,
    );
    expect(screen.getByRole("button", { name: "評価中…" })).toBeDisabled();
  });

  it("経路のEdge情報を持たない候補では選べない", () => {
    // edge_idsが空の候補（古い生成結果・Edge列を持たないエンジン）で区間を出すと、
    // 「差が無い」と「そもそも出せない」を利用者が区別できない。
    render(<RouteSplicePanel {...baseProps({ displayed: candidate("route-00", []) })} />);

    expect(screen.getByText(/経路のEdge情報を持たない/)).toBeInTheDocument();
    expect(screen.getByLabelText("比較相手")).toBeDisabled();
  });
});
