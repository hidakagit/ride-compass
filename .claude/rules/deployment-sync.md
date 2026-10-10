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
- **既存の仕組みと技術的に別方式の新しい配信・レンダリング機構（例: タイル焼き込み済み
  ramp軸に対する、フィーチャーの鍵で値を配る`dedicated_way_value_layer`）を新設するときは、
  着手前に`docs/architecture/design-principles.md`の構造仕様3・8（1本道の追加点）がこの新しい機構にも
  適用されるかを点検し、適用されるなら軸ごとのファイル・関数・定数・propを新設しない
  汎用設計にする**。
- **MVT焼き込み値（CASE式・材料タグ・domain純関数）を変更したら**、生成物
  （region-tile-config.json）を同一コミットで再生成する（タイル世代は手で上げない。`app/infrastructure/cache_identity.py`参照）。
- **評価軸（`axis_definitions`テーブル）の新規追加・削除・既存軸の`shape_params`調整は、
  すべて`axis_admin`のAPI（軸スタジオのGUI、または直接API呼び出し。新規追加=POST、
  削除=unpublish→DELETE、公開軸の調整=unpublish→PUT→republish）経由で行う。**
  **正本は本番DBだけ**で、リポジトリは軸の写しを持たない。
  本番の既存の表は`create_tables()`が宣言の変更に追従しないので、差は人が本番で埋める（デプロイが入れ替えの後に
  測る。docs/architecture/tech-stack.md「デプロイの反映確認（backend/frontendで注入元が異なる）」の`schema_gap.py`）。
  ビルド時の生成物（`frontend/src/types/generated/`）はコードの宣言から決め、DBを読まない。
  取り直せない管理データのバックアップは`.claude/skills/production-data/SKILL.md`の付録の「管理データのバックアップ」。
  完了扱いにする条件は`.claude/skills/production-data/SKILL.md`の「本番へ効かせたい軸定義の変更は、本番の管理APIへ入れる」
  （開発DBのみの反映で完了扱いにしない）。
- **既存DBの行データを新しいコードが読めなくなる変更（Pydanticモデルの破壊的変更等）を
  含む`backend/**`の変更は、本番DBのデータ移行を完了させてからmasterへ入れる（マージする）**。
  masterに入ってCI（`.github/workflows/ci.yml`）が通ると、backendは本番へ自動デプロイされ、止める仕組みは無い
  （コンテナを入れ替えるかの振り分けは`scripts/deploy_backend_gate.py`が正本）。
  対応順序は事前に次のいずれかを選ぶこと: 1) 本番DBのデータ移行を先に完了させてから
  マージ（移行を即座に行えなければ、終わるまでmasterへ入れずに待つ）、2) 新旧両方の形式を一時的に許容する後方互換コードを
  経由して段階的に移行する。
- **コードが新しく読む表・列を足す`backend/**`の変更も、本番DBに空の表（列）を作ってからmasterへ入れる（マージする）**。
  本番に無い表を読むコードが出ると、その表を読む口がデプロイのあと失敗し、派生の作り直しも本番の今の表を写して作業用のスキーマを作るので動かない。
  読まずに宣言だけ足す表は、出したあとに作ってよい。空の表のDDLは手で書かず、ORMの宣言（`app/infrastructure/orm_base.py: declared_metadata`）から
  `sqlalchemy.schema`の`CreateTable`・`CreateIndex`をPostgreSQLの方言でcompileして出す。マージの前の本番への書き込みの進め方は
  docs/conventions/flow.md「担当」の「自動で進めないもの」。

## backendを先に出した窓では、frontendが新しい材料を知らない

- 対象: 材料（`material_catalog`）・一次属性・レジストリを増やす変更。
- ルール: backendをデプロイしてからfrontendをデプロイするまでの間、**新しい材料を使う軸の
  編集画面は別物として開く**。窓の間は軸スタジオでその軸を触らない（画面はエラーを出さず、保存すると軸の中身が変わって書き戻る）。両方のデプロイが
  終わったことを確認してから編集する。
