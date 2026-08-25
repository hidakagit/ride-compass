"use client";

import { useEffect, useState } from "react";
import { DialogContent, DialogRoot } from "@/components/ui/Dialog/Dialog";
import { useAdminCredentials } from "@/hooks/useAdminCredentials";
import { setAdminCredentials } from "@/lib/adminToken";
import { materialLabel } from "@/lib/axisMaterialsCatalog";
import {
  createAxisDefinition,
  deleteAxisDefinition,
  listAxisDefinitions,
  unpublishAxisDefinition,
  updateAxisDefinition,
} from "@/services/axisAdminApi";
import type { AxisDefinitionPayload, AxisDefinitionResponse } from "@/types/route";
import AxisComposer from "./AxisComposer";
import styles from "./AxisStudio.module.css";

// 軸スタジオ（改善計画T270、T221 Stage E）のトップレベルコンポーネント。
// 一覧取得・作成・更新・削除の状態管理をここに集約し、フォーム自体はAxisComposerへ委ねる。
export default function AxisStudio() {
  const credentials = useAdminCredentials();
  const [usernameInput, setUsernameInput] = useState(credentials.username);
  const [passwordInput, setPasswordInput] = useState(credentials.password);
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
  useEffect(() => {
    if (credentials.username !== "" || credentials.password !== "") Promise.resolve().then(() => reload());
  }, [credentials.username, credentials.password]);

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
    ? `軸を編集: ${editingDefinition.axis_id}`
    : duplicateFrom
      ? `「${duplicateFrom.label}」を複製して新しい軸を作る`
      : "新しい軸を作る";

  return (
    <div className={styles.studio}>
      <div className={styles.tokenRow}>
        <label className={styles.field}>
          管理者ユーザー名
          <input
            type="text"
            value={usernameInput}
            onChange={(e) => setUsernameInput(e.target.value)}
            placeholder="環境変数ADMIN_BASIC_AUTH_USERNAMEと同じ値"
            autoComplete="username"
          />
        </label>
        <label className={styles.field}>
          管理者パスワード
          <input
            type="password"
            value={passwordInput}
            onChange={(e) => setPasswordInput(e.target.value)}
            placeholder="環境変数ADMIN_BASIC_AUTH_PASSWORDと同じ値"
            autoComplete="current-password"
          />
        </label>
        <button
          type="button"
          onClick={() => setAdminCredentials({ username: usernameInput, password: passwordInput })}
        >
          保存して再読み込み
        </button>
      </div>
      <p className={styles.tokenHint}>
        HTTP Basic認証です（改善計画T272。将来アカウント制へ拡張予定）。資格情報はこの
        ブラウザのlocalStorageにのみ保存されます。
      </p>

      {credentials.username === "" && credentials.password === "" && (
        <p className={styles.hint}>ユーザー名とパスワードを入力すると軸の一覧・編集ができます。</p>
      )}

      {(credentials.username !== "" || credentials.password !== "") && (
        <>
          <p className={styles.hint}>
            軸は「距離・獲得標高が近い候補の中から、どれくらい走りやすいか」を評価する
            計算式1本ぶんです。既存の軸を少し調整したいだけなら、一覧から「編集」を押して
            重みや折れ点を変えるだけで十分です（下書きの軸のみ編集可）。一から新しい軸を
            作るには「+ 新しい軸を作る」を押してください。公開済み軸は他ユーザーの設定を
            守るため直接編集・削除できません——「複製して新規作成」→検証→公開、または
            「非公開に戻す」→編集/削除、という流れになります。
          </p>
          {listError && <p className={styles.errorText}>{listError}</p>}
          <div className={styles.list}>
            <p className={styles.groupLabel}>登録済みの軸（{definitions?.length ?? "..."}）</p>
            {definitions?.map((def) => (
              <div key={def.axis_id} className={styles.listRow}>
                <div className={styles.listRowMain}>
                  <span className={styles.listLabel}>{def.label}</span>
                  <span className={def.is_published ? styles.publishedBadge : styles.draftBadge}>
                    {def.is_published ? "公開済み" : "下書き"}
                  </span>
                  <span className={styles.listMeta}>
                    {def.axis_id} ・ {def.category} ・ 重み{def.default_weight.toFixed(2)} ・{" "}
                    {def.shape.kind === "categorical"
                      ? materialLabel(def.shape.material)
                      : def.shape.kind === "flag_sum"
                        ? def.shape.flags.map(([m]) => materialLabel(m)).join("・")
                        : def.shape.terms.map((t) => materialLabel(t.material)).join("・")}
                  </span>
                </div>
                <div className={styles.listRowActions}>
                  <button
                    type="button"
                    onClick={() => setEditingAxisId(def.axis_id)}
                    disabled={def.is_published}
                    title={def.is_published ? "公開済み軸は編集できません（複製して編集してください）" : undefined}
                  >
                    編集
                  </button>
                  <button type="button" onClick={() => handleDuplicate(def)}>
                    複製して新規作成
                  </button>
                  {def.is_published && (
                    <button
                      type="button"
                      onClick={() => handleUnpublish(def.axis_id)}
                      disabled={unpublishingAxisId === def.axis_id}
                      title="一般ユーザー向けの軸カタログから外し、下書きへ戻します（削除するにはこの後もう一度「削除」を押します）"
                    >
                      非公開に戻す
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handleDelete(def.axis_id)}
                    disabled={
                      deletingAxisId === def.axis_id || (definitions?.length ?? 0) <= 1 || def.is_published
                    }
                    title={
                      def.is_published
                        ? "公開済み軸は削除できません（先に「非公開に戻す」を押してください）"
                        : (definitions?.length ?? 0) <= 1
                          ? "最後の1軸は削除できません"
                          : undefined
                    }
                  >
                    削除
                  </button>
                </div>
              </div>
            ))}
          </div>

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
            <DialogContent
              title={composerTitle}
              className="w-[min(94vw,42rem)] max-h-[85vh] overflow-y-auto"
            >
              <AxisComposer
                key={editingAxisId ?? (duplicateFrom ? `duplicate-${duplicateFrom.axis_id}` : "new")}
                editing={editingDefinition}
                duplicateFrom={duplicateFrom}
                onCancelEdit={closeComposer}
                onSave={handleSave}
              />
            </DialogContent>
          </DialogRoot>
        </>
      )}
    </div>
  );
}
