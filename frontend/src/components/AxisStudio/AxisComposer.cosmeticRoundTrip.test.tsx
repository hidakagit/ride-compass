// 公開済み軸の「表示だけ編集」が、表示専用フィールド以外を一切書き換えないことの回帰テスト。
// backendは公開済み軸のPUTを「表示専用フィールドだけの差分」のときしか受け付けない
// （domain/axis_definitions.py: _COSMETIC_ONLY_FIELDS・is_cosmetic_only_update）ため、
// フォームが編集欄を持たないフィールドを1つでも作り直して送ると、画面上は何も変えていない
// のに保存がAxisPublishedImmutableErrorで拒否される。
//
// 実在する全軸（backend/fixtures/axis_definitions_snapshot.json、実DBのダンプ）を材料に
// するのは、この欠陥が「値が既定と違う軸」でだけ現れるため——フォームの初期値と同じ軸を
// 1件だけ置いたテストは通ってしまう。
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { AxisDefinitionResponse } from "@/types/route";
import AxisComposer from "./AxisComposer";

// 分布プレビュー・材料カタログの実行時取得は塞ぐ（実HTTPを発火させない）。
vi.mock("@/services/axisPreviewApi", () => ({
  fetchAxisValueDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  fetchMaterialDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));
vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  getMaterialValues: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

// backendの_COSMETIC_ONLY_FIELDSと対になる一覧。ここを増やすだけでは意味が無く、
// backend側にも同じフィールドが入っていなければ保存は拒否される。
const COSMETIC_FIELDS = [
  "icon_id",
  "chip_label",
  "panel_hint",
  "show_map_icon",
  "display_thresholds_override",
  "display_band_labels_override",
];

const snapshot = JSON.parse(
  readFileSync(resolve(process.cwd(), "../backend/fixtures/axis_definitions_snapshot.json"), "utf-8"),
) as { axes: { definition: Record<string, unknown> }[] };

const publishedAxes = snapshot.axes.map((a) => a.definition).filter((d) => d.is_published);

describe("AxisComposer 公開済み軸の表示だけ編集", () => {
  it("スナップショットに公開済み軸がある（母集団が空のまま通らないことの確認）", () => {
    expect(publishedAxes.length).toBeGreaterThan(0);
  });

  for (const definition of publishedAxes) {
    it(`${definition.axis_id}: 何も触らず保存すると表示専用フィールド以外は既存値のまま送られる`, async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      const editing = { ...definition, display: { kind: "none" } } as unknown as AxisDefinitionResponse;
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.click(screen.getByRole("button", { name: "更新する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      for (const key of Object.keys(definition)) {
        if (COSMETIC_FIELDS.includes(key)) continue;
        expect({ [key]: payload[key] }).toEqual({ [key]: definition[key] });
      }
    });
  }
});
