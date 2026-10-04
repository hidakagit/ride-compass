import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { vocabulary } from "@/types/generated/vocabulary";

import WarningBadgeList, { type WarningBadgeItem } from "./WarningBadge";

// 段階の呼び名は、出所ごとにbackendの宣言（domain/warning_display.py）が配る。
const display = (source: WarningBadgeItem["source"], level: WarningBadgeItem["level"]) =>
  vocabulary.warningBadge[source].find((entry) => entry.level === level)!;

const item = (id: string, source: WarningBadgeItem["source"], level: WarningBadgeItem["level"], title?: string) => ({
  id,
  label: `${id}の名前`,
  source,
  level,
  title,
});

describe("WarningBadgeList", () => {
  it("警告も失敗も無ければ何も出さない", () => {
    const { container } = render(<WarningBadgeList items={[]} failures={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("1件なら、その段階の出所の呼び名を1つのボタンにする", () => {
    render(<WarningBadgeList items={[item("a", "wbgt", "warning")]} failures={[]} />);
    const expected = display("wbgt", "warning");
    const button = screen.getByRole("button", { name: `気象警報・注意報あり: ${expected.label}。押すと詳細を表示` });
    expect(button).toHaveTextContent(expected.label);
  });

  it("複数なら、最も重い段階の呼び名に件数を添える（同じ重さなら先の方）", () => {
    render(
      <WarningBadgeList
        items={[item("a", "jma", "advisory"), item("b", "flood", "warning"), item("c", "jma", "warning")]}
        failures={[]}
      />,
    );
    expect(screen.getByRole("button", { name: /^気象警報・注意報あり/ })).toHaveTextContent(
      `${display("flood", "warning").label}3件`,
    );
  });

  it("押すと全件を、補足と一緒に出す", async () => {
    render(
      <WarningBadgeList
        items={[item("a", "jma", "warning", "付随事項: 土砂災害"), item("b", "wbgt", "advisory")]}
        failures={[]}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /^気象警報・注意報あり/ }));
    const list = await screen.findByRole("list", { name: "気象警報・注意報の詳細" });
    const entries = within(list).getAllByRole("listitem");
    expect(entries.map((entry) => entry.textContent)).toEqual(["aの名前付随事項: 土砂災害", "bの名前"]);
  });

  it("取得に失敗した出所があれば「未取得」の印を出し、押すと出所ごとの理由を出す（警告なしと読ませない）", async () => {
    render(
      <WarningBadgeList
        items={[]}
        failures={[
          { id: "jma", label: "警報・注意報", detail: "[通信エラー]", effect: "警報のバッジは出ません。" },
          { id: "flood", label: "河川氾濫予報", detail: "混雑しています", effect: "予報のバッジは出ません。" },
        ]}
      />,
    );
    const mark = screen.getByRole("button", {
      name: "警報・注意報・河川氾濫予報を取得できていません。押すと詳細を表示",
    });
    expect(mark).toHaveTextContent("未取得");
    await userEvent.click(mark);
    expect(await screen.findByText("警報・注意報・河川氾濫予報を取得できていません")).toBeInTheDocument();
    expect(screen.getByText("警報・注意報: [通信エラー]")).toBeInTheDocument();
    expect(screen.getByText("警報のバッジは出ません。")).toBeInTheDocument();
    expect(screen.getByText("河川氾濫予報: 混雑しています")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "再試行" })).not.toBeInTheDocument();
  });

  it("取り直せる出所には、何が起きているかと再試行を出す", async () => {
    const retries: string[] = [];
    render(
      <WarningBadgeList
        items={[]}
        failures={[
          { id: "catalog", label: "軸一覧", effect: "地図の道路は出ません。", onRetry: () => retries.push("catalog") },
        ]}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /^軸一覧を取得できていません/ }));
    expect(await screen.findByText("地図の道路は出ません。")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "再試行" }));
    expect(retries).toEqual(["catalog"]);
  });

  it("警告と失敗は並べて出す", () => {
    render(
      <WarningBadgeList
        items={[item("a", "jma", "warning")]}
        failures={[{ id: "wbgt", label: "暑さ指数", detail: "x", effect: "y" }]}
      />,
    );
    expect(screen.getByRole("button", { name: /^気象警報・注意報あり/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^暑さ指数を取得できていません/ })).toBeInTheDocument();
  });
});
