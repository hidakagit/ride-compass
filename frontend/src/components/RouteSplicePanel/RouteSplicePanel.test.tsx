import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { RouteCandidate } from "@/types/route";
import RouteSplicePanel from "./RouteSplicePanel";

function candidate(id: string, edgeIds: string[]): RouteCandidate {
  return {
    ...({} as RouteCandidate),
    id,
    direction_label: id === "route-00" ? "目的地ルート" : "代替ルート",
    distance_km: 24.5,
    edge_ids: edgeIds,
  };
}

function baseProps(overrides: Partial<Parameters<typeof RouteSplicePanel>[0]> = {}) {
  return {
    displayed: candidate("route-00", ["a", "b", "c"]),
    groups: [] as Parameters<typeof RouteSplicePanel>[0]["groups"],
    onChoose: vi.fn(),
    onApply: vi.fn(),
    applying: false,
    error: null as string | null,
    onCancel: vi.fn(),
    ...overrides,
  };
}

const GROUPS = [
  {
    label: "1本目の区間",
    options: [
      { key: "route-01:1-2", label: "2 19.0km" },
      { key: "route-02:1-2", label: "3 20.5km" },
    ],
    chosenKey: null as string | null,
  },
];

describe("RouteSplicePanel", () => {
  it("区間ごとに、候補横断の代替が並ぶ（相手を1本選ばせない）", () => {
    render(<RouteSplicePanel {...baseProps({ groups: GROUPS })} />);

    expect(screen.getByText("1本目の区間")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "元のまま" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "2 19.0km" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "3 20.5km" })).toBeInTheDocument();
    // 使い方は画面へ書かず、見出し脇の(i)の奥に置く。
    expect(screen.getByRole("button", { name: /^区間の乗り換えの説明を/ })).toBeInTheDocument();
  });

  it("代替を押すとその区間の選択として親へ渡る", async () => {
    const onChoose = vi.fn();
    render(<RouteSplicePanel {...baseProps({ groups: GROUPS, onChoose })} />);

    await userEvent.click(screen.getByRole("button", { name: "2 19.0km" }));

    expect(onChoose).toHaveBeenCalledWith(0, "route-01:1-2");
  });

  it("「元のまま」を押すと選択を外す", async () => {
    const onChoose = vi.fn();
    const chosen = [{ ...GROUPS[0], chosenKey: "route-01:1-2" }];
    render(<RouteSplicePanel {...baseProps({ groups: chosen, onChoose })} />);

    expect(screen.getByRole("button", { name: "2 19.0km" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "元のまま" }));

    expect(onChoose).toHaveBeenCalledWith(0, null);
  });

  it("1区間も選んでいなければ作れない", () => {
    render(<RouteSplicePanel {...baseProps({ groups: GROUPS })} />);

    expect(screen.getByRole("button", { name: "新しいルートを作る" })).toBeDisabled();
  });

  it("1つでも選べば作れる", () => {
    const chosen = [{ ...GROUPS[0], chosenKey: "route-01:1-2" }];
    render(<RouteSplicePanel {...baseProps({ groups: chosen })} />);

    expect(screen.getByRole("button", { name: "新しいルートを作る" })).toBeEnabled();
  });

  it("評価中は押せない", () => {
    const chosen = [{ ...GROUPS[0], chosenKey: "route-01:1-2" }];
    render(<RouteSplicePanel {...baseProps({ groups: chosen, applying: true })} />);

    expect(screen.getByRole("button", { name: "評価中…" })).toBeDisabled();
  });

  it("差が無い候補では、その旨を出す", () => {
    render(<RouteSplicePanel {...baseProps()} />);

    expect(screen.getByText("他の候補と別の道を通る区間がありません。")).toBeInTheDocument();
  });

  it("edge_idsを持たない候補では区間を出せないことを伝える", () => {
    render(<RouteSplicePanel {...baseProps({ displayed: candidate("route-00", []) })} />);

    expect(screen.getByText(/Edge情報を持たない/)).toBeInTheDocument();
  });

  // 合成の失敗は「ルート結果」欄の空状態には出ない（候補がある間は描かれない）。押した場所へ
  // 出さないと「押しても何も起きない」に見える。
  it("合成に失敗した理由をこのパネルへ出す", () => {
    const chosen = [{ ...GROUPS[0], chosenKey: "route-01:1-2" }];
    render(
      <RouteSplicePanel {...baseProps({ groups: chosen, error: "組み合わせたルートを評価できませんでした" })} />,
    );

    expect(screen.getByText("組み合わせたルートを評価できませんでした")).toBeInTheDocument();
  });

  it("編集の元を固定で示し、やめると親へ知らせる", async () => {
    const onCancel = vi.fn();
    render(<RouteSplicePanel {...baseProps({ groups: GROUPS, onCancel })} />);

    expect(screen.getByText(/^元: 目的地ルート/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "編集をやめて候補へ戻る" }));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
