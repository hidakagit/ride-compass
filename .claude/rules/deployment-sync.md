---
paths:
  - "backend/app/**"
  - "frontend/src/types/generated/**"
  - "backend/scripts/export_openapi.py"
---

# デプロイ・DB同期の作業標準

コード変更と本番環境（DB・デプロイ）の同期について、「作業として何を完了条件に含めるか」の運用ルールだけを書く。
個々のモジュールの設計・実装事実は`docs/modules/*.md`が持つ。

本番DBを失ったときの作り直しは`.claude/skills/production-data/SKILL.md`の付録の「本番DBを失ったとき」（その材料は同じ付録の「管理データのバックアップ」）、
派生データの作り直しは`.claude/skills/production-data/SKILL.md`の「派生データの作り直し」。

## コミットと同時に揃えるもの

次は**同一コミットで**実施する。

- **backend側のAPIルーター・Pydanticモデル・レジストリ・domain定数を変更したら**、
  `backend/scripts/export_openapi.py`→`cd frontend && npm run generate:api`を実行し、
  `git diff --exit-code -- frontend/src/types/generated/`がクリーンであることを確認する。
- **API・ドメイン概念・レイヤー種を新設するタスクは、完了条件へ
  docs/architecture/・docs/modules/の追従を既定で含める**（書き分けはdocs/architecture/README.md「書き分け」）。
  どちらもコード変更と同一コミットで更新する。
- **MVT焼き込み値（CASE式・材料タグ・domain純関数）を変更したら**、生成物
  （region-tile-config.json）を同一コミットで再生成する（タイル世代は手で上げない。`app/infrastructure/cache_identity.py`参照）。
- **評価軸（`axis_definitions`テーブル）の追加・削除・調整はコミットではなく、
  `.claude/skills/production-data/SKILL.md`の「本番へ効かせたい軸定義の変更は、本番の管理APIへ入れる」で行う。**
  ビルド時の生成物（`frontend/src/types/generated/`）はコードの宣言から決め、DBを読まない。
- **新しいコードが読む前提（表・列・行データの形）を本番DBに揃えてから、その`backend/**`の変更をmasterへ入れる（マージする）**。
  masterに入ってCI（`.github/workflows/ci.yml`）が通ると、backendは本番へ自動デプロイされ、止める仕組みは無い
  （コンテナを入れ替えるかの振り分けは`scripts/deploy_backend_gate.py`が正本）。
  本番の既存の表は`create_tables()`が宣言の変更に追従せず、差は本番で埋める（デプロイが入れ替えの後に
  測る。docs/architecture/tech-stack.md「デプロイの反映確認（backend/frontendで注入元が異なる）」の`schema_gap.py`）。
  本番へ書くのは、開発機の対話のセッションが`.claude/skills/dev-session/SKILL.md`の「本番へ書く」のとおり打つ
  （担当は docs/conventions/flow.md「担当」の「自動で進めないもの」のとおり返す）。
  - 表・列を足す: 本番に無い表を読むコードが出ると、その表を読む口がデプロイのあと失敗し、派生の作り直しも本番の今の表を写して
    作業用のスキーマを作るので動かない。読まずに宣言だけ足す表は、出したあとに作ってよい。空の表のDDLは手で書かず、
    ORMの宣言（`app/infrastructure/orm_base.py: declared_metadata`）から`sqlalchemy.schema`の`CreateTable`・`CreateIndex`を
    PostgreSQLの方言でcompileして出す。
  - 既存の行データを新しいコードが読めなくなる変更（Pydanticモデルの破壊的変更等）: 新旧どちらの形の行も読めるコードを先に出し、
    本番の行を新しい形へ移してから、旧の形を読む口を消す（本番で動くコードが読めない行が残る間を作らない）。旧の口を消すことは、
    そのタスクの完了の条件に残す。
