# モジュール別設計書（索引）

機能単位の「現状の設計」を記す場所。フロント/バックで分け、各モジュール内は実コードの
みを根拠に記述する（レビュー結果・タスク記録は参照しない。経緯はタスクの issue が持ち、ここへは書かない。
下の「記載粒度」）。

## 着手の前に読む

**既存モジュールへの修正・追加に着手する際は、対象の docs/modules/*.md を必ず先に精読し、記載と実装の乖離
（未記載のファイル・古くなった記述）は同一コミットで直す**（サンプリング読みで済ませない）。

## 記載粒度（必読、肥大化を防ぐルール）

**このディレクトリの各ファイルは「今のコードがどう動くか」だけを書く。「なぜ今の形に
なったか」は書かない**——経緯の書き込みは積み重なって設計書を肥大化させ、今の動きを埋もれさせる。

- **禁止**: 「以前は…」「tasks#123で…に変更した」「実機/実測で…だったため」といった
  経緯の説明、変更前後のbefore/afterの数値比較、事故・インシデントの詳細な顛末。
  これらはタスクの issue（経緯の置き場。[documentation.md](../../.claude/rules/documentation.md)「用語集」）の役割である。
  **タスク番号もここへは書かない**——タスクの issue は閉じたあと更新されないため、
  維持する文書から辿らせると、指す先の中身が今のコードと合わなくなっても気づけない。
- **許可**: 現在のコードが持つ制約・不変条件とその理由が、コードを正しく使うために
  必須の場合（例:「このロックはXが並列gatherから呼ばれるため必要」）は、経緯ではなく
  **今も成り立つ設計上の理由**として1文で書いてよい。「なぜこの形か」の説明と「どういう
  経緯でこの形になったか」の説明は別物——前者は仕様の一部、後者は履歴。
- **要素を数え上げない**（個数・全件の一覧）。示すべきは挙動で、代表例を挙げるのは
  許容する。詳細は[documentation.md](../../.claude/rules/documentation.md)。このディレクトリの
  **対象ファイル表だけは例外**——新しい実装ファイルの責務を逆引きするために全件を持つ
  （完全性は周期レビューで人が見る）。`backend/scripts/`もこの母集団に入り、どれかのモジュールの表に載せる。
- **表・図を優先し、地の文を増やさない**。1関数・1テーブルにつき1〜2文を目安にする。
  実装の逐次説明（コードを上から読み下すような記述）はしない。何を書くかは
  [documentation.md](../../.claude/rules/documentation.md)「適用範囲の目安」。
- **「暗黙の前提」は現在の制約として書く**。「〜という前提が崩れると…になる」という
  形式は良いが、「なぜその前提を置いたか」の経緯は書かない。
- 1モジュールの目安は300〜400行程度。大きく超える場合は、実装の説明を削れないか
  （経緯・逐次説明が紛れ込んでいないか）を先に疑う。ファイル分割（モジュールの再定義）は
  最後の手段とする。
- **責務・対象ファイル表に行数・件数等のメトリックを書かない**。
  ファイル行数・state宣言数・関数の呼び出し回数のような数値はコード側で変わるたびに
  ここも追従が必要になり、追従されなければ嘘の数字が残るだけの脆い記載になる。
  「大きい/複雑」という性質を伝えたいなら数値ではなく「〜のため複雑」と定性的に書く。
- **レビュー指摘に上げるべきもの（設計原則違反・監視すべき不整合・機能バグの疑い等）を
  ここへ書かない**。「AがBと矛盾する」「Cにガードが無い」のような指摘は
  タスクの issue／周期レビューの起票案（[/review](../../.claude/commands/review.md)）側の役割。
  ここは常に「今のコードはこう動く」という中立的な事実の記述に徹する——起票済みの
  タスクの番号を含め、違反や不整合を名指しする文自体を書かない。

## このディレクトリが扱わない領域（正本は別にある）

機能単位の設計はここにあるが、**コードからは導けず文書だけが持つ制約**は
[docs/architecture/](../architecture/README.md)側にある。その領域に触る変更は、
モジュール設計書ではなくそちらを先に読む。

| 領域 | 正本 | 例 |
|---|---|---|
| 依存ライブラリのバージョン制約 | [architecture/tech-stack.md](../architecture/tech-stack.md) | 「このメジャーへ上げられない理由」。コードには「上げていない」という事実しか無く、理由は書かれていない |
| デプロイ順序・本番反映の前後関係 | [architecture/tech-stack.md](../architecture/tech-stack.md)・[deployment-sync.md](../../.claude/rules/deployment-sync.md) | DB移行を先に済ませないと起動に失敗する変更の扱い |
| 実行環境・プラットフォーム固有の制約 | [architecture/tech-stack.md](../architecture/tech-stack.md) | バンドラ・ホスティング・OSに由来する回避策 |
| 外部データソースの利用条件 | [architecture/data-sources.md](../architecture/data-sources.md) | 商用利用の可否・出典と加工した旨の表記要件。提供元の公式ページにしか無い |
| 検知器・レビュー基盤（`scripts/`） | [/review](../../.claude/commands/review.md)と`scripts/review_checks.py` | 何をどの経路で機械的にブロックするか。アプリの挙動ではなく**アプリを検査する側**のため、下の対象ファイル表の母集団にも入らない |
| タスクの流れのゲート（`tools/flow-gate/`） | [conventions/flow.md](../conventions/flow.md)・[ask/SKILL.md](../../.claude/skills/ask/SKILL.md) | ステータスの遷移の表・問いと答えの形・回答フォーム。アプリの外の運用の道具で、下の対象ファイル表の母集団に入らない |
| クラウドのセッションの用意（`scripts/remote_dev/`） | [architecture/setup.md](../architecture/setup.md)「クラウドのセッション」 | 依存の導入とDB・Redisの起動 |
| 壊れ方の確かめ（`scripts/break_tests.py`） | [.claude/rules/testing-review.md](../../.claude/rules/testing-review.md)「消す・まとめる前に、残す側が落ちるかを見る」 | 壊れ方の一覧の形・断る条件・前の版のテストの並べ方 |
| チェックアウトの遅れの確かめ（`scripts/checkout_freshness.py`） | [architecture/setup.md](../architecture/setup.md)「開発機の本体のチェックアウトの遅れ」 | どの道具が遅れで止まるか・早送りを打つ条件 |
| 本番でルートを作る確かめ（`scripts/prod_route_check.py`） | [architecture/tech-stack.md](../architecture/tech-stack.md)「本番でルートを作る確かめ」 | 何を見て落とすか・どこから回すか・待ちの上限の根拠 |

判断の目安は**「その制約を、コードだけを読んで知れるか」**。知れないならモジュール設計書の
範囲外で、docs/architecture/側を見る。

## backend

| モジュール | 内容 |
|---|---|
| [軸スタジオ・評価軸定義](backend/axis-studio.md) | `axis_definitions`テーブル・評価式・API |
| [ルート生成エンジン・経路探索](backend/routing-engine.md) | road_graphエンジン、周回生成戦略 |
| [評価・スコアリング](backend/evaluation-scoring.md) | 0次フィルタ・軸別difficulty合成・材料カタログ |
| [動的材料・フィーチャー値配信](backend/dynamic-way-values.md) | 風・勾配・雨のようなタイルへ焼けない材料を、路面タイルのフィーチャーの鍵で配る層 |
| [静的道路属性・タイル配信](backend/static-road-attributes.md) | OSM取込・MVTタイル配信 |
| [気象・動的レイヤー](backend/weather-dynamic-layers.md) | 気象庁MSM（数値予報モデル）・気象庁観測/防災データ |
| [標高](backend/elevation.md) | GSI DEMタイル |
| [地点の検索](backend/place-search.md) | 住所の区画の表と立ち寄り先の表を引き、出発地・経由地・目的地の候補を返す。住所の区画の表を作る |
| [横断基盤](backend/cross-cutting-infrastructure.md) | DB・Redis・ログ・レート制限・ジョブ管理 |

## frontend

| モジュール | 内容 |
|---|---|
| [軸スタジオ管理画面](frontend/axis-studio.md) | `/admin`の軸CRUD UI |
| [ルート設定・結果パネル](frontend/route-settings-and-results.md) | 重み設定・候補一覧・軸別内訳 |
| [地図: 軸・ルート色分け](frontend/map-axis-coloring.md) | dedicated_way_value_layer軸の描画 |
| [地図: 動的気象レイヤー](frontend/dynamic-weather-layers.md) | 風・降水・キキクル等の地図表示 |
| [地図: 静的レイヤー・道路表示](frontend/static-map-layers.md) | 路面・道路種別・自転車レーン・POI・事故の地図表示 |
| [ページ全体構成・状態管理](frontend/page-composition.md) | `page.tsx`のコンポジション・永続化。特定モジュールの責務ではない共通部品（`BottomSheet`・`Disclosure`等）もここへ集約する |
| [デザイン基盤](frontend/frontend-design-system.md) | `components/ui/`・デザイントークン（`globals.css`）・見た目は部品が持ち画面は並べ方だけを書く決まり |
| [開発者機能](frontend/developer-tools.md) | デバッグログ・システム状況 |
