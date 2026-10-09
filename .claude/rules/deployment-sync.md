---
paths:
  - "backend/app/**"
  - "frontend/src/types/generated/**"
  - "backend/scripts/export_openapi.py"
---

# デプロイ・DB同期の作業標準

コード変更と本番環境（DB・デプロイ）の同期に関する作業標準をまとめる。個々のモジュールの設計・実装事実は
ここに書かない（`docs/modules/*.md`が正）。ここに書くのは「作業として何を完了条件に
含めるべきか」という運用ルールのみ。

本番DBを失ったときの作り直しは`.claude/skills/production-data/SKILL.md`の付録の「本番DBを失ったとき」（その材料は同じ付録の「管理データのバックアップ」）、
派生データの作り直しは`.claude/skills/production-data/SKILL.md`の「派生データの作り直し」。

## コミットと同時に揃えるもの

コード変更と同期して更新すべきペアは、別のコミットに分けると片方が漏れる。次は**同一コミットで**実施する。

- **backend側のAPIルーター・Pydanticモデル・レジストリ・domain定数を変更したら**、
  `backend/scripts/export_openapi.py`→`cd frontend && npm run generate:api`を実行し、
  `git diff --exit-code -- frontend/src/types/generated/`がクリーンであることを確認する。
- **API・ドメイン概念・レイヤー種を新設するタスクは、完了条件へ
  docs/architecture/・docs/modules/の追従を既定で含める**。今のコードの動き（「現状」）はdocs/modules/が持ち、
  docs/architecture/は構造の約束と外部の制約を持つ（docs/architecture/README.md「書き分け」）。どちらもコード変更と
  同一コミットで更新する。
- **既存の仕組みと技術的に別方式の新しい配信・レンダリング機構（例: タイル焼き込み済み
  ramp軸に対する、フィーチャーの鍵で値を配る`dedicated_way_value_layer`）を新設するときは、
  着手前に`docs/architecture/design-principles.md`の構造仕様3・8（1本道の追加点）がこの新しい機構にも
  適用されるかを点検し、適用されるなら軸ごとのファイル・関数・定数・propを新設しない
  汎用設計にする**（新しい種類の機構を作る時にだけ点検が漏れやすい）。
- **MVT焼き込み値（CASE式・材料タグ・domain純関数）を変更したら**、生成物
  （region-tile-config.json）を同一コミットで再生成する（タイル世代そのものは焼き込みSQLから
  導出されるため手で上げない。`app/infrastructure/cache_identity.py`参照）。
- **評価軸（`axis_definitions`テーブル）の新規追加・削除・既存軸の`shape_params`調整は、
  すべて`axis_admin`のAPI（軸スタジオのGUI、または直接API呼び出し。新規追加=POST、
  削除=unpublish→DELETE、公開軸の調整=unpublish→PUT→republish）経由で行う。**
  **正本は本番DBだけ**で、リポジトリは軸の写しを持たない——スキーマはORMの宣言から
  `create_tables()`が作り、軸の中身は実行時の`GET /api/axis-catalog`がフロントへ配る。
  `create_tables()`はまっさらなDB向けで、本番の既存の表は宣言を変えても追従しない。差は人が本番で埋め、
  デプロイが入れ替えの後に測る（docs/architecture/tech-stack.md「デプロイの反映確認（backend/frontendで注入元が異なる）」の`schema_gap.py`）。
  ビルド時の生成物（`frontend/src/types/generated/`）はすべてコードの宣言から決まり、
  DBを読まない。取り直せない管理データのバックアップは`.claude/skills/production-data/SKILL.md`の付録の「管理データのバックアップ」。
  完了扱いにする条件は`.claude/skills/production-data/SKILL.md`の「本番へ効かせたい軸定義の変更は、本番の管理APIへ入れる」
  （開発DBのみの反映で完了扱いにしない）。
- **既存DBの行データを新しいコードが読めなくなる変更（Pydanticモデルの破壊的変更等）を
  含む`backend/**`の変更は、本番DBのデータ移行を完了させてからmasterへ入れる（マージする）**。
  作業ブランチへのpushでは本番へ出ない。masterに入ってCI（`.github/workflows/ci.yml`）が通ると、backendは本番へ自動デプロイされる
  （コンテナを入れ替えるかの振り分けは`scripts/deploy_backend_gate.py`が正本）。
  DB移行より先にmasterへ入れると、新コードが本番DBに残る旧形式データを読めず、
  `refresh_axis_definitions`等のfail-fast設計により本番backendが起動失敗する。
  対応順序は事前に次のいずれかを選ぶこと: 1) 本番DBのデータ移行を先に完了させてから
  マージ（移行を即座に行えなければ、終わるまでmasterへ入れずに待つ——masterのCIが通れば必ず
  デプロイされ、自動のデプロイを止める仕組みは無い）、2) 新旧両方の形式を一時的に許容する後方互換コードを
  経由して段階的に移行する。

## backendを先に出した窓では、frontendが新しい材料を知らない

- 対象: 材料（`material_catalog`）・一次属性・レジストリを増やす変更。
- ルール: backendをデプロイしてからfrontendをデプロイするまでの間、**新しい材料を使う軸の
  編集画面は別物として開く**——frontend側のカタログにその材料が無いため、材料として引けず
  「組み合わせる軸」の側へ倒れる。窓の間は軸スタジオでその軸を触らない。両方のデプロイが
  終わったことを確認してから編集する。
- なぜ黙って起きるか: 画面はエラーを出さない（引けない材料は「無い」として扱われる）ため、
  開いた人には壊れて見えず、保存すると**軸の中身が変わって書き戻る**。
