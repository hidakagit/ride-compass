/**
 * `DbStatusPanel.tsx`——本番DBの状態を押したときだけ集計し、取込・接続・テーブルの3群を同じ1行の形で並べ、
 * 注意の要る件数と母数を先頭に出すこと。テーブルは注意のあるものだけを行にし、残りは基準を名乗る1行へ畳む。
 *
 * 一覧の描き方そのものは `StatusRowList.test.tsx` が持つ。
 * 集計のカードの骨格（押すまで集計しない・集計中・失敗の表示・集計時刻）は `ReportCard.test.tsx` が持つ。
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DbStatusResponse } from "@/types/route";

const api = vi.hoisted(() => ({ getDbStatus: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => api);

import DbStatusPanel from "./DbStatusPanel";

type ImportEntry = DbStatusResponse["imports"][number];
type TableEntry = DbStatusResponse["tables"][number];
type Connections = DbStatusResponse["connections"];

const MB = 1024 * 1024;

function importEntry(overrides: Partial<ImportEntry>): ImportEntry {
  return {
    label: "import_a",
    latest_id: null,
    latest_status: null,
    latest_finished_at: null,
    latest_identity: {},
    latest_item_count: null,
    latest_succeeded_id: null,
    latest_succeeded_finished_at: null,
    needs_attention: false,
    note: "",
    ...overrides,
  };
}

function tableEntry(overrides: Partial<TableEntry>): TableEntry {
  return {
    table_name: "table_a",
    row_count: 0,
    total_bytes: 0,
    dead_tuples: 0,
    analyzed_at: null,
    vacuumed_at: null,
    needs_attention: false,
    note: "",
    ...overrides,
  };
}

function connections(overrides: Partial<Connections> = {}): Connections {
  return {
    total: 0,
    max_connections: 0,
    idle_in_transaction: 0,
    longest_idle_transaction_seconds: 0,
    longest_query_seconds: 0,
    needs_attention: false,
    note: "",
    ...overrides,
  };
}

function status(overrides: Partial<DbStatusResponse> = {}): DbStatusResponse {
  return {
    computed_at: "not-a-date",
    imports: [],
    tables: [],
    connections: connections(),
    database_bytes: 0,
    ...overrides,
  };
}

beforeEach(() => {
  api.getDbStatus.mockReset();
});

async function collect(response: DbStatusResponse) {
  api.getDbStatus.mockResolvedValue(response);
  const user = userEvent.setup();
  render(<DbStatusPanel />);
  await user.click(screen.getByRole("button", { name: "集計する" }));
  await screen.findByRole("button", { name: "再集計する" });
  return user;
}

function detailOf(name: string): [string | null, string | null | undefined][] {
  return Array.from(screen.getByText(name).closest("details")!.querySelectorAll("dt")).map((dt) => [
    dt.textContent,
    dt.nextSibling?.textContent,
  ]);
}

function listItems(): (string | null)[] {
  return within(screen.getByRole("list"))
    .getAllByRole("listitem")
    .map((item) => item.querySelector("summary > span:not([aria-hidden])")?.textContent ?? item.textContent);
}

describe("DbStatusPanel", () => {
  it("先頭に母数（テーブル数・行数の合計・DB全体の容量）と集計時刻を出す", async () => {
    await collect(
      status({
        computed_at: "2026-09-24T01:02:03Z",
        tables: [tableEntry({ table_name: "a", row_count: 1500 }), tableEntry({ table_name: "b", row_count: 500 })],
        database_bytes: 3 * 1024 * MB,
      }),
    );

    expect(screen.getByText("2テーブル ・ 2,000行 ・ 3.0 GB ・ 9/24 10:02")).toBeInTheDocument();
  });

  it("容量は1024MB未満ならMBの整数、以上ならGBの小数1桁で出す", async () => {
    await collect(
      status({
        tables: [
          tableEntry({ table_name: "small", total_bytes: 1023.4 * MB, needs_attention: true }),
          tableEntry({ table_name: "large", total_bytes: 1536 * MB, needs_attention: true }),
        ],
      }),
    );

    expect(detailOf("small")).toContainEqual(["容量", "1023 MB"]);
    expect(detailOf("large")).toContainEqual(["容量", "1.5 GB"]);
  });

  it("群は取込・接続・テーブルの順で、テーブルが1つも無ければテーブルの群を出さない", async () => {
    await collect(status({ imports: [importEntry({ label: "osm" })] }));

    expect(listItems()).toEqual(["取込", "osm", "接続", "同時接続"]);
  });

  it("テーブルは注意のあるものを1行ずつ並べ、残りは件数を名乗る1行へ畳んで、開いた先に一覧を置く", async () => {
    await collect(
      status({
        tables: [
          tableEntry({ table_name: "hot", needs_attention: true }),
          tableEntry({ table_name: "calm_a", row_count: 1000, total_bytes: 10 * MB }),
          tableEntry({ table_name: "calm_b", row_count: 2000, total_bytes: 20 * MB }),
        ],
      }),
    );

    expect(listItems().slice(-3)).toEqual(["テーブル（容量の大きい順）", "hot", "注意なし 2テーブル"]);
    const folded = screen.getByText("注意なし 2テーブル").closest("summary")!;
    expect(folded).toHaveTextContent("3,000行 ・ 30 MB");
    expect(within(folded).getByText("問題なし")).toBeInTheDocument();
    expect(detailOf("注意なし 2テーブル")).toEqual([
      ["calm_a", "1,000行 ・ 10 MB"],
      ["calm_b", "2,000行 ・ 20 MB"],
    ]);
  });

  it("注意のないテーブルが無ければ、畳んだ行を作らない", async () => {
    await collect(status({ tables: [tableEntry({ table_name: "hot", needs_attention: true })] }));
    expect(screen.queryByText(/^注意なし/)).not.toBeInTheDocument();
  });

  it("注意のあるテーブルは、実数・容量・統計とVACUUMの時刻（日本時間）・不要行（あるときだけ）・注記を開いた先に出す", async () => {
    await collect(
      status({
        tables: [
          tableEntry({
            table_name: "dead",
            row_count: 4200,
            total_bytes: 5 * MB,
            dead_tuples: 300,
            analyzed_at: null,
            vacuumed_at: "2026-09-24T01:02:03Z",
            needs_attention: true,
            note: "autovacuumが追いついていない",
          }),
          tableEntry({ table_name: "clean", needs_attention: true, dead_tuples: 0 }),
        ],
      }),
    );

    expect(screen.getByText("dead").closest("summary")).toHaveTextContent("4,200行 ・ 5 MB");
    expect(detailOf("dead")).toEqual([
      ["行数", "4,200件（実数）"],
      ["容量", "5 MB"],
      ["統計の取得", "記録なし"],
      ["VACUUM", "9/24 10:02"],
      ["不要行", "300件"],
    ]);
    expect(screen.getByText("autovacuumが追いついていない")).toBeInTheDocument();
    expect(detailOf("clean").map(([label]) => label)).not.toContain("不要行");
  });

  it("取込の行は、最新の番号と状態（成功はそう訳す）を規模に出し、開いた先に最終実行・成功した最新・件数・識別を並べる", async () => {
    await collect(
      status({
        imports: [
          importEntry({
            label: "osm",
            latest_id: 12,
            latest_status: "succeeded",
            latest_finished_at: "2026-09-24T01:02:03Z",
            latest_succeeded_id: 12,
            latest_succeeded_finished_at: null,
            latest_item_count: 34567,
            latest_identity: { pbf: "kanto-latest.osm.pbf" },
          }),
          importEntry({ label: "accidents", latest_id: 5, latest_status: "failed", needs_attention: true }),
          importEntry({ label: "never", note: "まだ一度も取り込んでいない" }),
        ],
      }),
    );

    expect(screen.getByText("osm").closest("summary")).toHaveTextContent("#12 成功");
    expect(detailOf("osm")).toEqual([
      ["最終実行", "#12 ・ 9/24 10:02"],
      ["成功した最新", "#12 ・ 記録なし"],
      ["取込件数", "34,567件"],
      ["pbf", "kanto-latest.osm.pbf"],
    ]);

    const failed = screen.getByText("accidents").closest("summary")!;
    expect(failed).toHaveTextContent("#5 failed");
    expect(within(failed).getByText("注意が要る")).toBeInTheDocument();

    expect(screen.getByText("never").closest("summary")).toHaveTextContent("記録なし");
    expect(detailOf("never")).toEqual([
      ["最終実行", "#- ・ 記録なし"],
      ["成功した最新", "なし"],
    ]);
    expect(screen.getByText("まだ一度も取り込んでいない")).toBeInTheDocument();
  });

  it("接続の行は、接続数と、放置されたトランザクション・実行中の最長を秒か分で出す", async () => {
    await collect(
      status({
        connections: connections({
          total: 8,
          max_connections: 100,
          idle_in_transaction: 2,
          longest_idle_transaction_seconds: 150,
          longest_query_seconds: 12.4,
          needs_attention: true,
          note: "放置が続いている",
        }),
      }),
    );

    expect(screen.getByText("同時接続").closest("summary")).toHaveTextContent("8 / 100");
    expect(detailOf("同時接続")).toEqual([
      ["接続数", "8 / 100"],
      ["未完了のまま放置", "2件 ・ 最長 3分"],
      ["実行中の最長", "12秒"],
    ]);
    expect(screen.getByText("放置が続いている")).toBeInTheDocument();
  });

  it("放置も実行中のクエリも無ければ、どちらも「なし」", async () => {
    await collect(status({ connections: connections({ idle_in_transaction: 0, longest_query_seconds: 0 }) }));

    expect(detailOf("同時接続").slice(1)).toEqual([
      ["未完了のまま放置", "なし"],
      ["実行中の最長", "なし"],
    ]);
  });

  it("注意の件数は、取込・接続・テーブル（畳む前の注意ありの行）をまとめて数える", async () => {
    await collect(
      status({
        imports: [importEntry({ label: "i1", needs_attention: true }), importEntry({ label: "i2" })],
        connections: connections({ needs_attention: true }),
        tables: [tableEntry({ table_name: "t1", needs_attention: true }), tableEntry({ table_name: "t2" })],
      }),
    );

    expect(screen.getByText("3件に注意")).toBeInTheDocument();
  });

  it("注意の要るものが無ければ、注意はなしと言う", async () => {
    await collect(status({ imports: [importEntry({})], tables: [tableEntry({})] }));
    expect(screen.getByText("注意はなし")).toBeInTheDocument();
  });
});
