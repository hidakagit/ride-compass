# アーキテクチャ（索引）

読み手は**これから作る開発者**。ここには「全体の見取り図」と「コードからは導けない制約」
（外部サービスの仕様・依存ライブラリを上げられない理由・本番環境の設定・デプロイの前後
関係）だけを置く。**実装粒度はここには無い**——モジュール単位の現状は
[docs/modules/README.md](../modules/README.md)が持つ。

| 章 | 内容 |
|---|---|
| [design-principles.md](design-principles.md) | 設計原則（構造仕様・UI仕様）。**規範**であり、コードがこれに従う |
| [tech-stack.md](tech-stack.md) | 技術選定・バージョン固定の理由・実行環境の制約・デプロイの反映確認・DBの版（本番が正本、CI・docker-composeが従う）・本番PostgreSQLの設定・Docker構成 |
| [data-sources.md](data-sources.md) | 外部データソースの利用条件（商用可否・表記の要件）と確認日 |
| [directory-layout.md](directory-layout.md) | backend/frontendの層の役割と、層をまたぐときの約束 |
| [api-design.md](api-design.md) | 公開しているエンドポイントの一覧と応答の形 |
| [data-model.md](data-model.md) | API境界の型と、その正本がどこにあるか |
| [route-generation.md](route-generation.md) | ルート生成の全体像とRoad Graph単一構成 |
| [evaluation-model.md](evaluation-model.md) | 評価軸の層構造（0次〜3次）の概観 |

## 書き分け

| 置きたいもの | 置き場所 |
|---|---|
| 従うべき契約（コードが従う） | design-principles.md |
| コードを読んでも分からない外部の制約・運用 | この章のいずれか |
| 「今のコードがどう動くか」 | [docs/modules/](../modules/README.md) |
| 仕事のやり方の取り決め | [docs/conventions/](../conventions/) |
| 過去（維持しない） | [docs/records/](../records/README.md) |
