/**
 * `TuningPanel.tsx`——較正値を開いたときに取り、backendが返した効き方ごとに並べ、打った値は「DBへ保存」で
 * まとめて書くこと。既定と同じ値にして保存した行は上書きを消す（nullを送る）。
 *
 * 並べる項目・効き方の見出しはbackendが返したものだけを使う（画面側に一覧を持たない）ため、テストも
 * 架空の項目を与える。
 *
 * ここで見ないもの:
 * - 数値の入力欄の途中の文字の扱い → `components/ui/NumberInput`
 * - 叩く先 → `app/admin/adminApi.test.ts`
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { dotVariants } from "@/components/ui/Dot/Dot";
import type { TuningParameter } from "@/features/admin/adminApi";
import { heldReplies, inTurn, onSameOrigin, type SentRequest } from "@/testing/backendServer";

import TuningPanel from "./TuningPanel";

const LIST = "/admin/api/tuning";
const UPDATE = "/admin/api/tuning/:paramId";

function parameter(overrides: Partial<TuningParameter>): TuningParameter {
  return {
    id: "group.param_a",
    label: "項目A",
    unit: "",
    description: "",
    default: 0,
    minimum: 0,
    maximum: 100,
    effect: "effect_a",
    effect_title: "効き方A",
    value: 0,
    overridden: false,
    ...overrides,
  };
}

const alpha = parameter({ id: "g.alpha", label: "アルファ", default: 10, value: 10 });
const beta = parameter({ id: "g.beta", label: "ベータ", default: 5, value: 7, overridden: true });

/** 保存に、送った値を効かせた行を返す（nullなら既定へ戻す）。 */
function acceptUpdates(rows: TuningParameter[]): SentRequest[] {
  return onSameOrigin("PUT", UPDATE, ({ path, body }) => {
    const row = rows.find((candidate) => path.endsWith(`/${candidate.id}`))!;
    const { value } = body as { value: number | null };
    return Response.json({ ...row, value: value ?? row.default, overridden: value !== null });
  });
}

const updates = (sent: SentRequest[]) => sent.map(({ path, body }) => [path, body]);

async function openWith(rows: TuningParameter[]) {
  onSameOrigin("GET", LIST, () => Response.json(rows));
  const user = userEvent.setup();
  render(<TuningPanel />);
  await screen.findByRole("button", { name: "DBへ保存" });
  return user;
}

async function typeValue(user: ReturnType<typeof userEvent.setup>, label: string, value: string) {
  const input = screen.getByRole("spinbutton", { name: label });
  await user.clear(input);
  await user.type(input, value);
}

describe("TuningPanel", () => {
  it("開くとすぐ取りに行き、届くまで読み込み中と出す。保存の口は届いてから出す", async () => {
    const held = heldReplies();
    onSameOrigin("GET", LIST, held.reply);
    render(<TuningPanel />);

    expect(screen.getByText("読み込み中…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "DBへ保存" })).not.toBeInTheDocument();

    await held.answer(0, Response.json([alpha]));
    expect(await screen.findByRole("button", { name: "DBへ保存" })).toBeDisabled();
    expect(screen.queryByText("読み込み中…")).not.toBeInTheDocument();
  });

  it("取得に失敗したら理由と読み込み直しの口を出し、読み込み直して届けば一覧を出す", async () => {
    onSameOrigin(
      "GET",
      LIST,
      inTurn(Response.json({ detail: "リクエストに失敗しました" }, { status: 500 }), Response.json([alpha])),
    );
    const user = userEvent.setup();
    render(<TuningPanel />);

    expect(await screen.findByText("リクエストに失敗しました")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "読み込み直す" }));

    expect(await screen.findByRole("spinbutton", { name: "アルファ" })).toHaveValue(10);
    expect(screen.queryByText("リクエストに失敗しました")).not.toBeInTheDocument();
  });

  it("効き方ごとに、届いた順で見出しを立て、行も届いた順に並べる", async () => {
    await openWith([
      parameter({ id: "a1", label: "A1", effect: "live", effect_title: "すぐ効く" }),
      parameter({ id: "b1", label: "B1", effect: "restart", effect_title: "再起動で効く" }),
      parameter({ id: "a2", label: "A2", effect: "live", effect_title: "すぐ効く" }),
    ]);

    const headings = screen.getAllByText(/^(すぐ効く|再起動で効く)$/);
    expect(headings.map((heading) => heading.textContent)).toEqual(["すぐ効く", "再起動で効く"]);
    const liveRows = within(headings[0].parentElement!).getAllByRole("spinbutton");
    expect(liveRows.map((input) => input.getAttribute("aria-label"))).toEqual(["A1", "A2"]);
    expect(within(headings[1].parentElement!).getAllByRole("spinbutton")).toHaveLength(1);
  });

  it("行は今効いている値を入れて出し、DBへ保存済みの行に印を付ける", async () => {
    await openWith([alpha, beta]);

    expect(screen.getByRole("spinbutton", { name: "アルファ" })).toHaveValue(10);
    expect(screen.getByRole("spinbutton", { name: "ベータ" })).toHaveValue(7);
    const dotOf = (label: string) =>
      screen.getByRole("spinbutton", { name: label }).closest("li")!.querySelector("[aria-hidden='true']");
    expect(dotOf("ベータ")).toHaveClass(dotVariants({ tone: "accent" }));
    expect(dotOf("アルファ")).not.toHaveClass(dotVariants({ tone: "accent" }));
  });

  it("打っただけでは送らず、今の値と違う行だけを未保存として数える。元の値へ戻せば数えない", async () => {
    const user = await openWith([alpha, beta]);
    const sent = acceptUpdates([alpha, beta]);

    await typeValue(user, "アルファ", "12");
    expect(screen.getByText("1件が未保存")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "DBへ保存" })).toBeEnabled();
    expect(sent).toEqual([]);

    await typeValue(user, "アルファ", "10");
    expect(screen.queryByText(/件が未保存/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "DBへ保存" })).toBeDisabled();
  });

  it("保存すると、値を変えた行だけを行ごとに送り、既定と同じ値にした行は上書きを消す（null）。返った値で行を置き換える", async () => {
    const gamma = parameter({ id: "g.gamma", label: "ガンマ", default: 1, value: 1 });
    const user = await openWith([alpha, beta, gamma]);
    const sent = acceptUpdates([alpha, beta, gamma]);

    await typeValue(user, "アルファ", "12");
    await typeValue(user, "ベータ", "5");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));

    await waitFor(() => expect(screen.queryByText(/件が未保存/)).not.toBeInTheDocument());
    expect(updates(sent)).toEqual([
      ["/admin/api/tuning/g.alpha", { value: 12 }],
      ["/admin/api/tuning/g.beta", { value: null }],
    ]);
    expect(screen.getByRole("spinbutton", { name: "アルファ" })).toHaveValue(12);
    expect(screen.getByRole("spinbutton", { name: "ベータ" })).toHaveValue(5);
    expect(screen.getByRole("button", { name: "DBへ保存" })).toBeDisabled();
  });

  it("保存中は押せない", async () => {
    const user = await openWith([alpha]);
    onSameOrigin("PUT", UPDATE, heldReplies().reply);

    await typeValue(user, "アルファ", "12");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));

    expect(await screen.findByRole("button", { name: "保存中…" })).toBeDisabled();
  });

  it("保存に失敗したら理由を出し、打った値は残す（読み込み直しの口は出さない）。直して保存し直せる", async () => {
    const user = await openWith([alpha]);
    onSameOrigin(
      "PUT",
      UPDATE,
      inTurn(
        Response.json({ detail: "範囲外です" }, { status: 422 }),
        Response.json({ ...alpha, value: 50, overridden: true }),
      ),
    );

    await typeValue(user, "アルファ", "999");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));

    expect(await screen.findByText("範囲外です")).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "アルファ" })).toHaveValue(999);
    expect(screen.getByText("1件が未保存")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "読み込み直す" })).not.toBeInTheDocument();

    await typeValue(user, "アルファ", "50");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));
    await waitFor(() => expect(screen.queryByText("範囲外です")).not.toBeInTheDocument());
  });

  it("途中の行で失敗したら、それより後の行は送らない", async () => {
    const user = await openWith([alpha, beta]);
    const sent = onSameOrigin("PUT", UPDATE, () => Response.json({ detail: "競合しました" }, { status: 409 }));

    await typeValue(user, "アルファ", "12");
    await typeValue(user, "ベータ", "6");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));

    expect(await screen.findByText("競合しました")).toBeInTheDocument();
    expect(updates(sent)).toEqual([["/admin/api/tuning/g.alpha", { value: 12 }]]);
    expect(screen.getByText("2件が未保存")).toBeInTheDocument();
  });
});
