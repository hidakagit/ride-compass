/**
 * `TuningPanel.tsx`——較正値を開いたときに取り、backendが返した効き方ごとに並べ、打った値は「DBへ保存」で
 * まとめて書くこと。既定と同じ値にして保存した行は上書きを消す（nullを送る）。
 *
 * 並べる項目・効き方の見出しはbackendが返したものだけを使う（画面側に一覧を持たない）ため、テストも
 * 架空の項目を与える。
 *
 * ここで見ないもの:
 * - 数値の入力欄の途中の文字の扱い → `components/ui/NumberInput`
 * - 叩く先 → `features/admin/adminApi.test.ts`
 */
import { StrictMode } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { dotVariants } from "@/components/ui/Dot/Dot";
import type { TuningParameter } from "@/features/admin/adminApi";

const api = vi.hoisted(() => ({ listTuningParameters: vi.fn(), updateTuningParameter: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => api);

import TuningPanel from "./TuningPanel";

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

beforeEach(() => {
  api.listTuningParameters.mockReset();
  api.updateTuningParameter.mockReset();
});

async function openWith(rows: TuningParameter[]) {
  api.listTuningParameters.mockResolvedValue(rows);
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
    let resolve!: (rows: TuningParameter[]) => void;
    api.listTuningParameters.mockReturnValue(new Promise<TuningParameter[]>((res) => (resolve = res)));
    render(<TuningPanel />);

    expect(api.listTuningParameters).toHaveBeenCalledTimes(1);
    expect(screen.getByText("読み込み中…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "DBへ保存" })).not.toBeInTheDocument();

    resolve([alpha]);
    expect(await screen.findByRole("button", { name: "DBへ保存" })).toBeDisabled();
    expect(screen.queryByText("読み込み中…")).not.toBeInTheDocument();
  });

  it("取得に失敗したら理由と読み込み直しの口を出し、読み込み直して届けば一覧を出す", async () => {
    api.listTuningParameters.mockRejectedValueOnce(new Error("リクエストに失敗しました"));
    const user = userEvent.setup();
    render(<TuningPanel />);

    expect(await screen.findByText("リクエストに失敗しました")).toBeInTheDocument();
    api.listTuningParameters.mockResolvedValueOnce([alpha]);
    await user.click(screen.getByRole("button", { name: "読み込み直す" }));

    expect(await screen.findByRole("spinbutton", { name: "アルファ" })).toHaveValue(10);
    expect(screen.queryByText("リクエストに失敗しました")).not.toBeInTheDocument();
  });

  it.each([
    ["成功", (late: { resolve: (rows: TuningParameter[]) => void }) => late.resolve([beta])],
    ["失敗", (late: { reject: (reason: unknown) => void }) => late.reject(new Error("古い取得の失敗"))],
  ] as const)("立ち上げ直しで取得が2回走っても、後から届いた古い方の%sで上書きしない", async (_kind, settleLate) => {
    let late!: { resolve: (rows: TuningParameter[]) => void; reject: (reason: unknown) => void };
    api.listTuningParameters
      .mockReturnValueOnce(new Promise<TuningParameter[]>((resolve, reject) => (late = { resolve, reject })))
      .mockResolvedValueOnce([alpha]);
    render(
      <StrictMode>
        <TuningPanel />
      </StrictMode>,
    );
    expect(await screen.findByRole("spinbutton", { name: "アルファ" })).toBeInTheDocument();

    await act(async () => settleLate(late));
    expect(screen.getByRole("spinbutton", { name: "アルファ" })).toBeInTheDocument();
    expect(screen.queryByRole("spinbutton", { name: "ベータ" })).not.toBeInTheDocument();
    expect(screen.queryByText("古い取得の失敗")).not.toBeInTheDocument();
  });

  it("取得の失敗がError以外なら、取得に失敗したと言う", async () => {
    api.listTuningParameters.mockRejectedValue("offline");
    render(<TuningPanel />);
    expect(await screen.findByText("較正値の取得に失敗しました")).toBeInTheDocument();
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

  it("説明の奥に、説明・既定値・範囲を置く", async () => {
    const user = await openWith([
      parameter({
        id: "p",
        label: "転がり抵抗",
        description: "タイヤの抵抗",
        default: 0.005,
        unit: "",
        minimum: 0,
        maximum: 0.02,
      }),
    ]);

    await user.click(screen.getByRole("button", { name: "転がり抵抗の説明を表示" }));
    expect(await screen.findByText("タイヤの抵抗")).toBeInTheDocument();
    expect(screen.getByText(/既定 0\.005（0〜0\.02）/)).toBeInTheDocument();
  });

  it("打っただけでは送らず、今の値と違う行だけを未保存として数える。元の値へ戻せば数えない", async () => {
    const user = await openWith([alpha, beta]);

    await typeValue(user, "アルファ", "12");
    expect(screen.getByText("1件が未保存")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "DBへ保存" })).toBeEnabled();
    expect(api.updateTuningParameter).not.toHaveBeenCalled();

    await typeValue(user, "アルファ", "10");
    expect(screen.queryByText(/件が未保存/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "DBへ保存" })).toBeDisabled();
  });

  it("保存すると、打った値を行ごとに送り、既定と同じ値にした行は上書きを消す（null）。返った値で行を置き換える", async () => {
    const user = await openWith([alpha, beta]);
    api.updateTuningParameter.mockImplementation(async (id: string, value: number | null) =>
      id === alpha.id
        ? { ...alpha, value: value ?? alpha.default, overridden: value !== null }
        : { ...beta, value: value ?? beta.default, overridden: value !== null },
    );

    await typeValue(user, "アルファ", "12");
    await typeValue(user, "ベータ", "5");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));

    await waitFor(() => expect(api.updateTuningParameter).toHaveBeenCalledTimes(2));
    expect(api.updateTuningParameter).toHaveBeenNthCalledWith(1, alpha.id, 12);
    expect(api.updateTuningParameter).toHaveBeenNthCalledWith(2, beta.id, null);
    await waitFor(() => expect(screen.queryByText(/件が未保存/)).not.toBeInTheDocument());
    expect(screen.getByRole("spinbutton", { name: "アルファ" })).toHaveValue(12);
    expect(screen.getByRole("spinbutton", { name: "ベータ" })).toHaveValue(5);
    expect(screen.getByRole("button", { name: "DBへ保存" })).toBeDisabled();
  });

  it("保存で送るのは、値を変えた行だけ", async () => {
    const gamma = parameter({ id: "g.gamma", label: "ガンマ", default: 1, value: 1 });
    const user = await openWith([alpha, beta, gamma]);
    api.updateTuningParameter.mockResolvedValue({ ...beta, value: 8 });

    await typeValue(user, "ベータ", "8");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));

    await waitFor(() => expect(screen.queryByText(/件が未保存/)).not.toBeInTheDocument());
    expect(api.updateTuningParameter).toHaveBeenCalledTimes(1);
    expect(api.updateTuningParameter).toHaveBeenCalledWith(beta.id, 8);
  });

  it("保存中は押せない", async () => {
    const user = await openWith([alpha]);
    api.updateTuningParameter.mockReturnValue(new Promise(() => {}));

    await typeValue(user, "アルファ", "12");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));

    expect(await screen.findByRole("button", { name: "保存中…" })).toBeDisabled();
  });

  it("保存に失敗したら理由を出し、打った値は残す（読み込み直しの口は出さない）。直して保存し直せる", async () => {
    const user = await openWith([alpha]);
    api.updateTuningParameter.mockRejectedValueOnce(new Error("範囲外です"));

    await typeValue(user, "アルファ", "999");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));

    expect(await screen.findByText("範囲外です")).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "アルファ" })).toHaveValue(999);
    expect(screen.getByText("1件が未保存")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "読み込み直す" })).not.toBeInTheDocument();

    api.updateTuningParameter.mockResolvedValueOnce({ ...alpha, value: 50, overridden: true });
    await typeValue(user, "アルファ", "50");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));
    await waitFor(() => expect(screen.queryByText("範囲外です")).not.toBeInTheDocument());
  });

  it("途中の行で失敗したら、それより後の行は送らない。Error以外の失敗は保存に失敗したと言う", async () => {
    const user = await openWith([alpha, beta]);
    api.updateTuningParameter.mockRejectedValueOnce("conflict");

    await typeValue(user, "アルファ", "12");
    await typeValue(user, "ベータ", "6");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));

    expect(await screen.findByText("保存に失敗しました")).toBeInTheDocument();
    expect(api.updateTuningParameter).toHaveBeenCalledTimes(1);
    expect(screen.getByText("2件が未保存")).toBeInTheDocument();
  });
});
