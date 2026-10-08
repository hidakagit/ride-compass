/**
 * 「保存」タブ（`SavedConditionsPanel.tsx`）——タブには保存の窓を開くボタンだけを置き、窓で保存する条件・重みの割合・除外と
 * 出発地の扱いを並べ、名前の欄に仮の名前を入れて出し、そのまま・書き換えて保存でき、保存すると窓を閉じる。出発地は固定するかを選べ、選ぶまでは地図で置いたかで決まる。
 * 同じ名前があれば上書きと分かるように出す。保存した設定を名前と条件の1行で並べ、「呼び出す」は窓で中身を見せて「反映する」を
 * 押したときだけ呼び出し、「消す」は確認の窓で「消す」を押したときだけ消す。
 *
 * ここで見ないもの:
 * - 説明の文の作り方（割合・除外の名前） → `savedConditions.test.ts`
 * - 保存・呼び出し・削除で条件と一覧がどう変わるか → `useSavedConditions.test.ts`
 *
 * 差し替えたもの: 軸カタログの応答（網の層）。
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import type { GenerationConditionsSnapshot, SavedCondition } from "@/features/route/savedConditions";
import { serveAxisCatalog } from "@/testing/backendServer";
import { catalogEntry, catalogResponse } from "@/testing/catalogAxes";

import SavedConditionsPanel from "./SavedConditionsPanel";

const CURRENT: GenerationConditionsSnapshot = {
  routeMode: "loop",
  distance: "40",
  maxRoutes: "8",
  waypoints: [],
  destination: null,
  routePreference: null,
  hardFilters: DEFAULT_HARD_FILTERS,
};
const LOOP: SavedCondition = { ...CURRENT, name: "朝の荒川", origin: null };
const POINT = { latitude: 35.1, longitude: 139.1 };
const TRIP: SavedCondition = {
  ...LOOP,
  name: "週末",
  routeMode: "destination",
  origin: POINT,
  waypoints: [POINT, POINT],
  routePreference: { axis_a: 1, axis_b: 3 },
};

function renderPanel(
  saved: SavedCondition[] = [],
  { originManual = false, originKnown = true }: { originManual?: boolean; originKnown?: boolean } = {},
) {
  const handlers = { onSave: vi.fn(), onRecall: vi.fn(), onRemove: vi.fn() };
  render(
    <SavedConditionsPanel
      saved={saved}
      current={CURRENT}
      suggestedName="周回 40km"
      originManual={originManual}
      originKnown={originKnown}
      {...handlers}
    />,
  );
  return handlers;
}

/** 「いまの設定を保存」の窓を開いて、窓を返す。 */
async function openSaveDialog() {
  await userEvent.click(screen.getByRole("button", { name: "いまの設定を保存" }));
  return screen.getByRole("dialog", { name: "いまの設定を保存" });
}

beforeEach(() => {
  serveAxisCatalog(
    catalogResponse([
      catalogEntry({ axis_id: "axis_a", label: "軸A", default_weight: 1 }),
      catalogEntry({ axis_id: "axis_b", label: "軸B", default_weight: 1 }),
    ]),
  );
});

describe("保存", () => {
  it("タブには窓を開くボタンだけを置き、窓で、いまの設定の条件と重みの割合を並べる", async () => {
    renderPanel();
    expect(screen.queryByText("周回 40km・候補 8本")).not.toBeInTheDocument();

    const dialog = await openSaveDialog();

    expect(within(dialog).getByText("周回 40km・候補 8本")).toBeInTheDocument();
    expect(await within(dialog).findByText("軸A 50%・軸B 50%")).toBeInTheDocument();
  });

  it("仮の名前が入った欄をそのまま保存でき、書き換えればその名前で保存し、保存すると窓を閉じる", async () => {
    const { onSave } = renderPanel();
    let dialog = await openSaveDialog();
    expect(within(dialog).getByRole("textbox", { name: "保存する名前" })).toHaveValue("周回 40km");

    await userEvent.click(within(dialog).getByRole("button", { name: "保存" }));
    expect(onSave).toHaveBeenLastCalledWith("周回 40km", false);
    expect(screen.queryByRole("dialog")).toBeNull();

    dialog = await openSaveDialog();
    const nameField = within(dialog).getByRole("textbox", { name: "保存する名前" });
    await userEvent.clear(nameField);
    await userEvent.type(nameField, "夕方{Enter}");
    expect(onSave).toHaveBeenLastCalledWith("夕方", false);

    dialog = await openSaveDialog();
    expect(within(dialog).getByRole("textbox", { name: "保存する名前" })).toHaveValue("周回 40km");
  });

  it("同じ名前の設定があれば、保存のボタンが上書き保存になる", async () => {
    renderPanel([LOOP]);
    const dialog = await openSaveDialog();
    const nameField = within(dialog).getByRole("textbox", { name: "保存する名前" });

    await userEvent.clear(nameField);
    await userEvent.type(nameField, "朝の荒川");

    expect(within(dialog).getByRole("button", { name: "上書き保存" })).toBeInTheDocument();
  });

  it.each([
    ["地図で置いた出発地は、既定で固定する", { originManual: true }, true, false],
    ["現在地のままなら、既定で呼び出した時の現在地", { originManual: false }, false, false],
    ["分からない出発地は、地図で置いても固定できない", { originManual: true, originKnown: false }, false, true],
  ])("出発地: %s", async (_, origin, fixed, fixDisabled) => {
    const { onSave } = renderPanel([], origin);
    const dialog = await openSaveDialog();

    expect(
      within(dialog).getByRole("radio", { name: fixed ? "今の出発地に固定" : "呼び出した時の現在地" }),
    ).toBeChecked();
    expect(within(dialog).getByRole("radio", { name: "今の出発地に固定" })).toHaveProperty("disabled", fixDisabled);
    await userEvent.click(within(dialog).getByRole("button", { name: "保存" }));
    expect(onSave).toHaveBeenLastCalledWith("周回 40km", fixed);
  });

  it("現在地のままでも出発地を固定して保存でき、保存すると選び直す前の既定へ戻る", async () => {
    const { onSave } = renderPanel();
    let dialog = await openSaveDialog();

    await userEvent.click(within(dialog).getByRole("radio", { name: "今の出発地に固定" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "保存" }));

    expect(onSave).toHaveBeenLastCalledWith("周回 40km", true);
    dialog = await openSaveDialog();
    expect(within(dialog).getByRole("radio", { name: "呼び出した時の現在地" })).toBeChecked();
  });
});

describe("保存した設定", () => {
  it("無いうちはまだ無いと出す", () => {
    renderPanel();

    expect(screen.getByText("まだありません。")).toBeInTheDocument();
  });

  it("行は名前と条件の1行だけを出し、出発地・重み・除外は呼び出しの窓で読める", async () => {
    renderPanel([LOOP, TRIP]);

    const trip = screen.getAllByRole("listitem")[1];
    expect(trip).toHaveTextContent("目的地へ・経由 2地点・候補 8本");
    expect(screen.queryByText("保存した地点に固定")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "「週末」を呼び出す" }));

    const dialog = screen.getByRole("dialog", { name: "「週末」を反映します" });
    expect(within(dialog).getByText("保存した地点に固定")).toBeInTheDocument();
    expect(await within(dialog).findByText("軸B 75%・軸A 25%")).toBeInTheDocument();
  });

  it.each([
    ["固定しない設定", LOOP, "「朝の荒川」を呼び出しました。出発地は今いる場所です。"],
    ["出発地を固定した設定", TRIP, "「週末」を呼び出しました。出発地は保存した地点です。"],
  ])("窓の「反映する」を押したときだけ%sを呼び出し、呼び出したことと出発地を出す", async (_, entry, expected) => {
    const { onRecall } = renderPanel([LOOP, TRIP]);
    const recallDialog = () => screen.getByRole("dialog", { name: `「${entry.name}」を反映します` });

    await userEvent.click(screen.getByRole("button", { name: `「${entry.name}」を呼び出す` }));
    await userEvent.click(within(recallDialog()).getByRole("button", { name: "キャンセル" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onRecall).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: `「${entry.name}」を呼び出す` }));
    await userEvent.click(within(recallDialog()).getByRole("button", { name: "反映する" }));

    expect(onRecall).toHaveBeenCalledExactlyOnceWith(entry);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent(expected);
  });

  it("「消す」で、確認の窓の「消す」を押したときだけその行の名前を消す", async () => {
    const { onRemove, onRecall } = renderPanel([LOOP, TRIP]);
    const confirmDialog = () => screen.getByRole("dialog", { name: "「週末」を消します" });

    await userEvent.click(screen.getByRole("button", { name: "「週末」を消す" }));
    await userEvent.click(within(confirmDialog()).getByRole("button", { name: "キャンセル" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onRemove).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "「週末」を消す" }));
    await userEvent.click(within(confirmDialog()).getByRole("button", { name: "消す" }));

    expect(onRemove).toHaveBeenCalledExactlyOnceWith("週末");
    expect(onRecall).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
