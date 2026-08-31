"use client";

import { useEffect, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { DialogContent, DialogRoot } from "@/components/ui/Dialog/Dialog";
import { materialLabel } from "@/lib/axisMaterialsCatalog";
import {
  createAxisDefinition,
  deleteAxisDefinition,
  listAxisDefinitions,
  unpublishAxisDefinition,
  updateAxisDefinition,
} from "@/services/axisAdminApi";
import type { AxisDefinitionPayload, AxisDefinitionResponse, AxisShape } from "@/types/route";
import AxisComposer from "./AxisComposer";
import styles from "./AxisStudio.module.css";

// 改善計画T323: shapeが参照する材料id一覧（`kind`ごとにフィールド名が異なるため統一する）。
// この中には材料カタログの材料idだけでなく、他axis_idを指すもの（改善計画T292「他axis_idを
// 材料として参照する内部軸階層」）も混在しうる。
function materialIdsOf(shape: AxisShape): string[] {
  if (shape.kind === "categorical") return [shape.material];
  return shape.terms.map((t) => t.material);
}

// 改善計画T325（UIレビュー2026-08-25 F-3）: 一覧のサマリ表示用に、材料id/軸idどちらも
// 人間向けラベルへ解決する。`materialLabel`は材料カタログにのみ問い合わせるため、
// `t.material`が他axis_id（改善計画T292「他axis_idを材料として参照する内部軸階層」、
// 例: car_stress軸のterms）を指すケースでは該当ラベルを引けず、材料カタログのフォールバック
// （`?? materialId`）で生のsnake_case識別子がそのまま表示されていた。まずこのaxis_id一覧
// 内に該当する軸が無いか探し、あればその表示名(label)を優先する。
function labelForMaterialOrAxis(id: string, definitions: readonly AxisDefinitionResponse[]): string {
  return definitions.find((d) => d.axis_id === id)?.label ?? materialLabel(id);
}

// 改善計画T323: 「この軸を削除しようとしたら、他の軸から材料として参照されていた」という
// 事実が見えないまま削除できてしまう問題への対応（UIレビュー2026-08-25 F-1）。削除の可否は
// 制限せず、削除前に参照元とその影響をユーザーへ明示する。
function axesReferencing(axisId: string, definitions: readonly AxisDefinitionResponse[]): AxisDefinitionResponse[] {
  return definitions.filter((d) => d.axis_id !== axisId && materialIdsOf(d.shape).includes(axisId));
}

// 軸スタジオ（改善計画T270、T221 Stage E）のトップレベルコンポーネント。
// 一覧取得・作成・更新・削除の状態管理をここに集約し、フォーム自体はAxisComposerへ委ねる。
//
// 改善計画T305: 以前はここに管理者ユーザー名/パスワードの入力欄を持っていたが撤去した。
// /adminページ自体が既にBasic認証（frontend/src/proxy.ts）で保護されているため、
// この画面へ来られた時点でブラウザは既に認証済み——二重ログインを求めるUIが分かりにくいと
// いう実機フィードバックへの対応。軸CRUD APIの呼び出しは同一オリジンのroute handler
// （app/admin/api/axis-definitions/配下、services/axisAdminApi.ts参照）を経由するため、
// ブラウザが/admin読込時にキャッシュした認証情報がこのAPI呼び出しにも自動で使われる。
export default function AxisStudio() {
  const [definitions, setDefinitions] = useState<AxisDefinitionResponse[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [editingAxisId, setEditingAxisId] = useState<string | null>(null);
  const [deletingAxisId, setDeletingAxisId] = useState<string | null>(null);
  const [unpublishingAxisId, setUnpublishingAxisId] = useState<string | null>(null);
  // 複製元（改善計画T271）。nullでなければAxisComposerを「新規作成」モードのまま
  // duplicateFromの内容で初期化する（axis_idは空のまま、is_publishedは常にfalseへ
  // 落とす——公開済み軸を複製しても複製先は下書きから始まる）。
  const [duplicateFrom, setDuplicateFrom] = useState<AxisDefinitionResponse | null>(null);
  // 改善計画T304: 「編集ボタンを押した後にそのまま編集画面がポップアップ起動してほしい。
  // 下部エリアの編集エリアまで目が行かない」という実機フィードバックへの対応。以前は
  // AxisComposerが一覧の下に常時表示（新規作成モード）されており、「編集」を押しても
  // 一覧のさらに下までスクロールしないと気づけなかった。編集・複製・新規作成のどれかを
  // 選んだときだけモーダル（components/ui/Dialog）で開く方式へ変更した。creatingNewは
  // 「新しい軸を作る」ボタンを押したときだけtrueになる（以前は常時この状態がデフォルト
  // 表示されていたが、一覧を隠さない・目的の操作を選んでから開く、という一貫した導線にする）。
  const [creatingNew, setCreatingNew] = useState(false);
  const composerOpen = editingAxisId !== null || duplicateFrom !== null || creatingNew;

  async function reload() {
    setListError(null);
    try {
      const list = await listAxisDefinitions();
      setDefinitions(list);
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    }
  }

  // effect本体からの直接同期setState呼び出しを避け、マイクロタスク経由で実行する
  // （react-hooks/set-state-in-effect対策、SystemStatusPanel.tsxと同じ流儀）。
  // マウント時に一度だけ読み込む。
  useEffect(() => {
    Promise.resolve().then(() => reload());
  }, []);

  function closeComposer() {
    setEditingAxisId(null);
    setDuplicateFrom(null);
    setCreatingNew(false);
  }

  async function handleSave(payload: AxisDefinitionPayload, isNew: boolean) {
    if (isNew) {
      await createAxisDefinition(payload);
    } else {
      await updateAxisDefinition(payload.axis_id, payload);
    }
    await reload();
    closeComposer();
  }

  function handleDuplicate(def: AxisDefinitionResponse) {
    setEditingAxisId(null);
    setCreatingNew(false);
    setDuplicateFrom(def);
  }

  async function handleUnpublish(axisId: string) {
    // 改善計画T302: 公開済み軸を下書きへ戻す。一般ユーザー向けGET /api/axis-catalogから
    // 即座に消えるため、フロント側の自己修復（RouteSettingsPanel）とセットで
    // 初めて安全な操作になる（docs/decisions/t221-axis-registry.md「Stage D拡張3」）。
    setUnpublishingAxisId(axisId);
    try {
      await unpublishAxisDefinition(axisId);
      await reload();
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    } finally {
      setUnpublishingAxisId(null);
    }
  }

  async function handleDelete(axisId: string) {
    // 改善計画T323: 削除しようとしている軸が他の軸から材料として参照されている場合、
    // その事実と影響を確認ダイアログで明示する（一律拒否はしない——内部軸を整理・
    // 再設計するために意図的に削除したい場面もありうるため、最終判断はユーザーに委ねる）。
    const referencing = definitions ? axesReferencing(axisId, definitions) : [];
    if (referencing.length > 0) {
      const names = referencing.map((d) => d.label).join("・");
      const confirmed = window.confirm(
        `この軸は次の軸から材料として参照されています: ${names}\n削除すると、それらの軸が正しく評価できなくなります（評価対象外になります）。\n本当に削除しますか？`,
      );
      if (!confirmed) return;
    }
    setDeletingAxisId(axisId);
    try {
      await deleteAxisDefinition(axisId);
      await reload();
      if (editingAxisId === axisId) setEditingAxisId(null);
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingAxisId(null);
    }
  }

  const editingDefinition = definitions?.find((d) => d.axis_id === editingAxisId) ?? null;
  const composerTitle = editingDefinition
    ? editingDefinition.is_published
      ? `表示専用フィールドを編集: ${editingDefinition.label}`
      : `軸を編集: ${editingDefinition.label}`
    : duplicateFrom
      ? `「${duplicateFrom.label}」を複製して新しい軸を作る`
      : "新しい軸を作る";

  const draftDefs = definitions?.filter((d) => !d.is_published) ?? [];
  const publishedDefs = definitions?.filter((d) => d.is_published) ?? [];

  function renderRowMain(def: AxisDefinitionResponse) {
    return (
      <div className={styles.listRowMain}>
        <span className={styles.listLabel} title={`axis_id: ${def.axis_id}`}>
          {def.label}
        </span>
        <span className={styles.listMeta}>
          {def.category} ・ 重み{def.default_weight.toFixed(2)} ・{" "}
          {materialIdsOf(def.shape)
            .map((id) => labelForMaterialOrAxis(id, definitions ?? []))
            .join("・")}
        </span>
      </div>
    );
  }

  return (
    <div className={styles.studio}>
      {/* 改善計画T397フォローアップ2（ユーザー指摘: 見出し「評価軸（軸スタジオ）」と
          タイトルが被る・軸の説明も何が言いたいか分からない）: 常設の説明文は撤去した。 */}
      {listError && <p className={styles.errorText}>{listError}</p>}

      {/* 改善計画T397フォローアップ（ユーザー指摘: 公開済みと未公開をタブで分けたい）。
          下書きタブを既定にする——新規作成した軸はまず下書きから始まり、実際の編集・
          削除操作もほぼ下書きに対して行うため。公開済みタブに削除ボタンは出さない
          （常に無効化されているだけの状態を見せるより、そもそも出さない方がシンプル。
          削除は先に「非公開に戻す」という導線を残す）。編集ボタンは改善計画T501により
          「表示だけ編集」として復活させた——AxisComposerが編集対象の公開状態を見て
          自動的に表示専用フィールドのみの制限モードへ切り替わるため、材料・計算式・
          重みを変えたい場合は引き続き「複製して新規作成」に導線を残す。 */}
      <Tabs.Root className={styles.tabs} defaultValue="draft">
        <Tabs.List className={styles.tabList}>
          <Tabs.Trigger className={styles.tabTrigger} value="draft">
            下書き（{draftDefs.length}）
          </Tabs.Trigger>
          <Tabs.Trigger className={styles.tabTrigger} value="published">
            公開済み（{publishedDefs.length}）
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content className={styles.list} value="draft">
          {draftDefs.length === 0 && <p className={styles.hint}>下書きの軸はありません。</p>}
          {draftDefs.map((def) => (
            <div key={def.axis_id} className={styles.listRow}>
              {renderRowMain(def)}
              <div className={styles.listRowActions}>
                <button type="button" onClick={() => setEditingAxisId(def.axis_id)}>
                  編集
                </button>
                <button type="button" onClick={() => handleDuplicate(def)}>
                  複製して新規作成
                </button>
                <button
                  type="button"
                  className={styles.deleteButton}
                  onClick={() => handleDelete(def.axis_id)}
                  disabled={deletingAxisId === def.axis_id || (definitions?.length ?? 0) <= 1}
                  title={(definitions?.length ?? 0) <= 1 ? "最後の1軸は削除できません" : undefined}
                >
                  削除
                </button>
              </div>
            </div>
          ))}
        </Tabs.Content>

        <Tabs.Content className={styles.list} value="published">
          {publishedDefs.length === 0 && <p className={styles.hint}>公開済みの軸はありません。</p>}
          {publishedDefs.map((def) => (
            <div key={def.axis_id} className={styles.listRow}>
              {renderRowMain(def)}
              <div className={styles.listRowActions}>
                <button
                  type="button"
                  onClick={() => setEditingAxisId(def.axis_id)}
                  title="材料・計算式・重みは変更できません。地図チップ・色分けしきい値等の表示専用フィールドのみ編集できます"
                >
                  表示だけ編集
                </button>
                <button type="button" onClick={() => handleDuplicate(def)}>
                  複製して新規作成
                </button>
                <button
                  type="button"
                  onClick={() => handleUnpublish(def.axis_id)}
                  disabled={unpublishingAxisId === def.axis_id}
                  title="一般ユーザー向けの軸カタログから外し、下書きへ戻します（削除するにはこの後もう一度「削除」を押します）"
                >
                  非公開に戻す
                </button>
              </div>
            </div>
          ))}
        </Tabs.Content>
      </Tabs.Root>

      <button
        type="button"
        className={styles.newAxisButton}
        onClick={() => {
          setEditingAxisId(null);
          setDuplicateFrom(null);
          setCreatingNew(true);
        }}
      >
        + 新しい軸を作る
      </button>

      <DialogRoot open={composerOpen} onOpenChange={(open) => { if (!open) closeComposer(); }}>
        {/* 既定のDialogContentは幅min(90vw,28rem)・高さ内容依存だが、AxisComposerは
            材料/折れ点/フラグの可変長リストを持つ比較的大きなフォームのため、幅と
            最大高さ+縦スクロールを拡張する（改善計画T304）。cn()のtwMergeで既定の
            Tailwindユーティリティ(w-[...]/デフォルトのoverflow無指定)を正しく
            上書きするため、CSS Modulesではなくここでも同じくTailwindクラス文字列を渡す。 */}
        <DialogContent title={composerTitle} className="w-[min(94vw,42rem)] max-h-[85vh] overflow-y-auto">
          <AxisComposer
            key={editingAxisId ?? (duplicateFrom ? `duplicate-${duplicateFrom.axis_id}` : "new")}
            editing={editingDefinition}
            duplicateFrom={duplicateFrom}
            otherAxes={definitions ?? []}
            onCancelEdit={closeComposer}
            onSave={handleSave}
          />
        </DialogContent>
      </DialogRoot>
    </div>
  );
}
