/**
 * `ReportCard.tsx`——集計のカードが、押したときだけ集計し、集計中は押せず、終わると再集計の口になり、失敗の理由を
 * 出し、集計の時刻を日本時間で（母数があればその前に）出すこと。中身の描き方は各パネルのテストが持つ。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReportCard } from "./ReportCard";

interface Report {
  computed_at: string;
  count: number;
}

function renderCard(load: () => Promise<Report>, summary?: (report: Report) => string) {
  const user = userEvent.setup();
  render(
    <ReportCard title="集計の名前" info="説明" load={load} summary={summary}>
      {(report) => <p>中身 {report.count}</p>}
    </ReportCard>,
  );
  return user;
}

describe("ReportCard", () => {
  it("押すまで集計しない。集計中は押せず、終わると中身を出して再集計の口になる", async () => {
    let resolve!: (value: Report) => void;
    const load = vi.fn(() => new Promise<Report>((res) => (resolve = res)));
    const user = renderCard(load);
    expect(load).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "集計する" }));
    expect(screen.getByRole("button", { name: "集計中…" })).toBeDisabled();

    resolve({ computed_at: "2026-09-24T01:02:03Z", count: 3 });
    expect(await screen.findByRole("button", { name: "再集計する" })).toBeEnabled();
    expect(screen.getByText("中身 3")).toBeInTheDocument();
  });

  it("失敗したら理由を出し、再集計が成功すれば消える。Error以外の失敗も値を出す", async () => {
    const load = vi
      .fn<() => Promise<Report>>()
      .mockRejectedValueOnce(new Error("DB状態の取得に失敗しました"))
      .mockRejectedValueOnce("timeout")
      .mockResolvedValueOnce({ computed_at: "2026-09-24T01:02:03Z", count: 1 });
    const user = renderCard(load);

    await user.click(screen.getByRole("button", { name: "集計する" }));
    expect(await screen.findByText("集計失敗: DB状態の取得に失敗しました")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "集計する" }));
    expect(await screen.findByText("集計失敗: timeout")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "集計する" }));
    await screen.findByRole("button", { name: "再集計する" });
    expect(screen.queryByText(/集計失敗/)).not.toBeInTheDocument();
  });

  it("集計の時刻を日本時間で出し、母数があればその前に並べる", async () => {
    const report = { computed_at: "2026-09-24T15:02:03Z", count: 1 };
    const user = renderCard(
      async () => report,
      (r) => `${r.count}件`,
    );
    await user.click(screen.getByRole("button", { name: "集計する" }));
    expect(await screen.findByText("1件 ・ 9/25 00:02")).toBeInTheDocument();
  });
});
