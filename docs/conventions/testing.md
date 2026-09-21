# テスト方針（実行効率を保つためのパターン）

RideCompassのテストスイートは規模が大きい（backend 800件超、frontend 330件超）。
**新しいテストを追加するときは、以下のパターンに従って実行時間の増加を最小限に抑えること。**
2026-08-18の実効性改善（backend 243秒→47秒、frontend 246秒→193秒）で得た知見をまとめたもの。

## 基本原則

1. **ループで実I/O（HTTPリクエスト・新規DB接続）を繰り返さない。** 「上限回数まで実行してから
   1回超過させる」ようなN回ループの検証は、境界に到達する直前までを実I/O無しで埋め、境界の
   1〜2回だけ実際に実行する。
2. **新規リソース（DB接続・テスト環境）の構築コストはテストスイート全体で使い回せないか検討する。**
   テスト関数ごとに新規構築するコストが積み重なると、テストの絶対数に比例して線形に遅くなる。
3. **速度最適化はテストが検証する内容を変えない範囲で行う。** 上記のいずれも「境界条件の実地検証」
   自体は残し、その手前の準備コストだけを削る。カバレッジを犠牲にしない。
4. **結果を見るときはpassedの件数だけを見ない。警告も結果の一部として扱う。**

## 警告は既定でエラー

`backend/pytest.ini`の`filterwarnings`は`error`から始まる。警告は出ていても誰も読まないため、
黙って積み上がって「気づいたら非推奨APIが削除されて動かない」になる。

直せない／直すべきでない警告（依存ライブラリが自分の内部で出すもの等）は、**その行を
`ignore:<メッセージの先頭>:<警告の種類>`として理由のコメント付きで足す**。放置との違いは、
その1行が読めて消せることにある——依存を上げて不要になったら消す。

- 絞り込みはメッセージまで書く。`ignore::DeprecationWarning`のように種類だけで黙らせない
  （同じ種類の別の警告まで一緒に消える）
- 代償を承知しておく: こちらのコードを変えなくても、**依存ライブラリを上げた瞬間にCIが
  赤くなりうる**。それを知りたいから`error`にしている
- フロントエンド（vitest）にはこの強制が無い。出力の警告は人が読む

## テストが落ちたときの直し方（①〜⑤）

落ちた状態から緑へ戻すまでの手順。**全体を流し直しながら1件ずつ直す**のが一番高くつくため、
順番を固定する。

1. **失敗した対象を最小コストで洗い出す。** 直前の実行ログが手元にあるなら**それを読む**。
   列挙のためにテストを流し直さない——同じ情報を数分かけて取り直すことになる。
2. **失敗の原因を洗い出す。** テスト名や件数ではなく、`AssertionError`の中身・例外の種類・
   実際に渡された値まで取る。**①の出力は「何が落ちたか」しか言わない。「なぜ落ちたか」は
   別に取る。** ここを飛ばすと③でまとめられず、1件直して全体を流す、を繰り返すことになる。
3. **同根のものだけをまとめて直す。** 原因で束ねると1つの編集が複数件を同時に解く。
   束ねられないのは②が足りていない合図で、③へ進む前に②へ戻る。
4. **③で触った範囲だけを検証する。** テストと**静的検査（`tsc --noEmit`・`ruff`）の両方**を
   その範囲へ当てる。全体を流すと、いま直していない失敗が混ざって何が解けたか読めなくなる。
5. ③④を繰り返す。全部解けたら、最終確認として全体を1回だけ流す。

**手を動かす前に現物を読む。** 書いた当時の文字列で照合しない——整形（prettier等）が入って
いると一致せず、置換が黙って空振りする。複数ファイルを直すときは、1ファイルの失敗が残りを
巻き添えにしない形（ファイルごとに独立）で当て、**どれが変わってどれが変わらなかったかを
出力に残す**。

### 収束しなかったら、理由を書く

2周しても同じ失敗が残るなら、原因は手順ではなく②にある。**何を見落としたかをタスク
エントリへ書いてから**3周目に入る（実例: 失敗一覧を「直し方が分かる情報」と誤認して②を
飛ばし、テスト名だけで直し方を決めた。同じ一覧を3回取り直すことになった）。

## 挙動を変えるなら、テストを先に書く

**挙動を変えるタスクは、テストを先に追加/更新してから実装する。** 実装のあとに書くと、
書いたコードが通ることだけを確かめるテストになりやすく、「どう壊れるか」を検証しない。

## 開発機でのbackendテストの回し方

反復フェーズは変更に関係するファイルだけを絞って実行する（CLAUDE.md「テスト方針」）。
まとめて回すときは次の2本立てにする。

```bash
# 反復中: DBを使わないぶんを並列で（PYTHONUTF8=1が無いとワーカー起動が落ちる）
PYTHONUTF8=1 backend/.venv/Scripts/python.exe -m pytest backend/tests -q -m "not postgis" -n auto

# 完了前に1回: DBを使うぶん
backend/.venv/Scripts/python.exe -m pytest backend/tests -q -m postgis
```

**`PYTHONUTF8=1`が要る理由**: 付けないと`execnet`のワーカーが
`UnicodeEncodeError: ... surrogates not allowed`で即死し、親が
`EOFError: expected 1 bytes, got 0`のINTERNALERRORになる。リポジトリのパスに含まれる
非ASCII文字がサロゲート化するためで、UTF-8モードにすると解消する。

### テストDBは作業ツリーごとに分かれる

並行セッション（複数のClaude Code・複数の作業ツリー）が同じDBの同じ行を書き換えると、
**変更と無関係なテストが落ちる**。落ちたファイルを単独で回すと通るため、毎回切り分けに
時間を取られ、慣れると逆に本物の回帰を「どうせ競合」と見送る。

そこで`tests/conftest.py: postgis_database_url`が、チェックアウトの場所からDB名を導き
（`ridecompass_test_<ディレクトリ名>_<パスのダイジェスト>`）、無ければ作る。同じ作業ツリー
では同じDBを再利用するので、PostGIS拡張とテーブルの作成を毎回払わない。

#### 環境ごとに必要な作業

| 環境 | 必要な作業 | 理由 |
|---|---|---|
| 開発機（ローカルPostgreSQL） | **一度だけ**ロールへ`CREATEDB`を付け、複製元のDBへ拡張を入れる（どちらも下記） | DBを作る権限・拡張を入れる権限が既定では無い |
| CI（GitHub Actions） | 何もしない | `TEST_DATABASE_URL`を注入しており、そちらが優先される。DBは実行ごとの使い捨てコンテナで元から分離されている。拡張は`road_graph_engine`が入れる（CIのDBユーザーはスーパーユーザー） |
| 本番（Oracle VM） | 何もしない | テストDBは本番に存在しない |

権限を付けない場合も動く——共有DB（`ridecompass_test`）へ退避し、その旨を1行出す。
**分離されないだけで、テストが走らなくなることはない。**

開発機での手順（PostgreSQLをインストールした機械で1回だけ。`postgres`ロールのパスワードを
プロンプトで聞かれる）:

```bash
"/c/Program Files/PostgreSQL/18/bin/psql.exe" -U postgres -d postgres -c "ALTER ROLE ridecompass CREATEDB;"
```

`psql`はPATHに入っていないため絶対パスで呼ぶ。元に戻すときは`NOCREATEDB`を同じ形で流す。
付いたかどうかは`SELECT rolcreatedb FROM pg_roles WHERE rolname='ridecompass';`で確かめる。

拡張はロールの権限では入れられない（スーパーユーザーを要求する）。**複製元になるDBへ一度
入れておけば、作業ツリー専用DBは複製で引き継ぐ**——共有の`ridecompass_test`と、その複製元の
`ridecompass_test_template`の両方へ入れる。何が要るかは`road_graph_repository.py:
REQUIRED_EXTENSIONS`が正本で、足りないときは`create_tables()`が実行すべきコマンドを告げて
止まる（**スキップにはならない**——そこを黙って飛ばすと、そのファイルのテストが1件も走らない
まま緑になる）。

```bash
"/c/Program Files/PostgreSQL/18/bin/psql.exe" -U postgres -d ridecompass_test -c "CREATE EXTENSION IF NOT EXISTS postgis_raster;"
```

#### 残骸の片付け

作業ツリーを消してもDBは残る。**どのDBがどの作業ツリーのものかは、DB自身のコメントに
書いてある**——名前から推測しない。

```bash
backend/.venv/Scripts/python.exe backend/scripts/drop_orphan_test_databases.py         # 一覧
backend/.venv/Scripts/python.exe backend/scripts/drop_orphan_test_databases.py --drop  # 落とす
```

**postgisを並列化しても速くならない**: DBを使うテストは`xdist_group(name="postgis")`により
1ワーカーへ固定される（同じDBへの同時TRUNCATEを避けるための設計、後述）。実測で直列6分20秒
（2,189件）に対し`-n auto --dist loadgroup`は7分00秒——postgisの285件が4分23秒を占め、残りを
並列化しても全体は縮まずワーカー起動のぶん増える。縮めるには**ワーカーごとに**DBを分ける
必要があり（作業ツリーごとの分離とは別の軸）、それ自体が別タスク。

**`-m postgis`はCIが通す**（CLAUDE.md「テスト方針」参照）。手元で回すのはCIが落ちた失敗を
再現するときだけで、完了条件には含めない。手元で回す場合は、共有の`ridecompass_test`を
掴むため並行セッションと衝突しうることに注意する。以下は手元で再現するときの前提:
手元の既定実行（`-m "not postgis"`）から外れるため、
実装を変えてテストを直し忘れると、気づくのはCIになる。実際にこの型で3件の赤が生まれている
（[T834](../records/tasks/T834.md)・[T835](../records/tasks/T835.md)）——**CIが担うのはここ**で、手元で
先回りして通すことでは置き換えない。

**あわせて、masterのCIが赤いままなら手元へ出る**（`.githooks/pre-push`→
`scripts/check_master_ci.py`、[T835](../records/tasks/T835.md)）。pushの直前にmasterの最新コミットに
対する結論を読み、成功していないワークフローがあれば警告する。**pushは止めない**——赤の原因が
自分の変更とは限らず、止めると無関係な作業がブロックされるため、気づかせるところまでを担う。
変更が届く範囲を手元で通すことと役割が違う——赤を**作りにくくする**のが手元の実行、
作ってしまった赤に**気づく**のがこの警告とCIである。

## ソースを読む検査は、専用ディレクトリへ置く

置き場を決める軸は「何を守るか」ではなく、**そのテストが何を読むか**である。

- **リポジトリのソースをデータとして読む**（ASTやテキストとして走査し、コードは動かさない）
  ——素の`BaseModel`を使っていないか、web層がバッチをimportしていないか、未定義のCSSトークンを
  参照していないか等。これを下の専用ディレクトリへ置く
- **コードを動かして確かめる**——横断的な不変条件を守るものでも、対象を実際に動かすなら
  普通のテストであり、**対象の隣へ置く**（例: スタイル作り直しの前後でレイヤー状態が戻るかは
  MapViewを動かして見るため、`components/Map/`側に置く）

前者の置き場は次の2か所。

| 対象 | 置き場 |
|---|---|
| backend | `backend/tests/structure/` |
| frontend | `frontend/src/structure/` |

**普通のテストと混ぜない。** 検査する対象が1モジュールに紐づかないため、対象の隣へ置くと
どこにあるか分からなくなり、次に足す人が別の場所へ置く。まとめておけば、何が機械的に
守られているかを1か所で見られる。

書き方は他のテストと同じで、**母集団をソースから導く**（ファイルを手で名指ししない）。
許可リストが要るなら、**その列挙が古くなったときにテスト自身が落ちる**ようにする
（載っているのに実態が無い側も違反にする。`test_redis_skeleton.py`参照）。

## パターン1: レート制限テスト → rate_limiterを直接埋める

```python
from app.infrastructure import rate_limiter

def test_xxx_is_rate_limited_per_client():
    ...
    for _ in range(settings.xxx_rate_limit_per_minute - 1):
        rate_limiter.check_rate_limit("xxx:testclient", settings.xxx_rate_limit_per_minute)
    assert client.get(...).status_code == 200  # 境界の1回だけ実HTTP
    response = client.get(...)
    assert response.status_code == 429
```

`TestClient`の接続元`client_id`は常に`"testclient"`（`app/api/dependencies.py: client_id`参照、
`test_client_ip_behind_proxy.py`で検証済み）。キーのprefixは各routerの
`check_rate_limit(f"{prefix}:{client_id(request)}", ...)`呼び出しに合わせる。

実例: test_region_routes.py, test_weather_route.py, test_basemap_routes.py,
test_accident_routes.py, test_routes_preview.py, test_routes_generate.py

## パターン2: PostGIS統合テスト（road_graph_session）→ ファイル単位でエンジン・イベントループを共有

`conftest.py`の`road_graph_session`/`road_graph_repository`はテストファイル（モジュール）単位で
1本のDB接続・イベントループを使い回す設計（新規DB接続の確立自体に1〜2秒かかるため、テスト関数
ごとに新規作成すると規模の大きいファイルでテスト全体の時間を大きく押し上げる。ローカル環境での
実測、localhost/127.0.0.1どちらでも同程度でDNS起因ではない）。

新しいテストファイルでこれらのフィクスチャを使う場合:

1. ファイル冒頭に `pytestmark = pytest.mark.asyncio(loop_scope="module")` を付ける
   （同期テストが同じファイルに混在していても影響しない）。
2. ファイル内で自前の追加async fixtureを定義してroad_graph_session/road_graph_repositoryに
   依存させる場合は、その自前fixtureにも明示的に`loop_scope="module"`を付ける
   （`@pytest_asyncio.fixture(loop_scope="module")`）。省略すると
   `MultipleEventLoopsRequestedError`になる。
3. 素の`@pytest.fixture`でasync generatorを書かない。`@pytest_asyncio.fixture`を明示的に使う
   （前者は互換用の内部変換パスを通り、モジュールスコープのイベントループと衝突する）。

実例: test_road_graph_repository.py, test_health.py（db_status_test_engine）,
test_match_designations.py（designation_conn）, test_accident_repository.py

**xdist_group="postgis"（改善計画T233フォローアップ、pytest-xdist導入後は必須）**:
CIは`-n auto --dist loadgroup`でDB以外のテストを並列化している。road_graph_session系
フィクスチャを使うテスト（ファイルまたは個別テスト関数）には必ず
`pytest.mark.xdist_group(name="postgis")`と`pytest.mark.postgis`（`pytest.ini`の`markers`に
登録済み。`pytest -m "not postgis"`で実際にdeselectされる唯一の仕組み——ローカルDB未接続時の
実スキップは各fixtureの`try/except pytest.skip()`が別途担う）の両方を付け、`pytestmark`が
既にリストでなければ
`pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.xdist_group(name="postgis"), pytest.mark.postgis]`
の形にする。xdist_groupを付けないと、同じテストDBへ複数workerが同時接続し、
他ファイルのTRUNCATEでテストデータが消える形のflakyな失敗を起こしうる（postgisマーカーの
付け忘れは`pytest -m "not postgis"`が該当テストを除外し損ねるだけで実行結果自体は壊れないため、
気づかれにくい。改善計画T429で発覚: マーカー未登録のままこの説明だけが独り歩きし、
実態は12ファイル全てfixtureレベルの`try/except pytest.skip()`のみで`-m "not postgis"`は
1件もdeselectしていなかった）。

## パターン3: フロントエンドのテスト環境 → DOM不要ならnode環境

DOM（render/renderHook/window/document等）を使わない純ロジックのテストファイルは、
ファイル先頭へ`// @vitest-environment node`docblockを付けてnode環境に倒している。
DOM環境の構築コストはテストファイルごとにかかるため、対象外にできるファイルが増えるほど
実行時間が縮む（旧`vitest.config.mts`の`environmentMatchGlobs`による一括指定は、Vitest 4で
同オプションが廃止されコンパイルエラー・ランタイムでの黙殺の両方を引き起こしたため
改善計画T126で撤去済み。バージョン間で仕様が安定しているdocblock方式へ移行した）。
既定のDOM環境自体も改善計画T329でjsdomからhappy-domへ変更済み（テストスイート全体の
実行時間が約35%短縮。canvas.getContext("2d")が未実装でnullを返す等、既存テストが依存する
挙動はjsdomと同一であることを確認済み。個別ファイルで`// @vitest-environment jsdom`を
付ければ従来のjsdomへ戻せる）。

新規テストファイルがservices/lib配下やMap内の式・フィルタ関数のようにDOMに触れない場合、
このdocblockの追加を検討する。省略してもデフォルトのhappy-domのままなので壊れることはない
（速度だけの問題）。判断に迷ったら、そのテストファイルが
`render`/`renderHook`/`screen`/`document`/`window`のいずれかを使っているか確認する
——ただし**テストファイル自身だけでなく、importしている実装側の関数が内部で
`document.createElement`等を呼んでいないかも確認すること**（`windArrowIcon.ts`が
`document.createElement("canvas")`を使う実例。テストファイル単体では判断できない
「実装側の隠れたDOM依存」を見落とし、node環境化すると実行時エラーになる）。

## パターン4: フロントエンドのPlaywright（E2E）→ 本番同等サーバー・ローカルworkers=1

1. **webServerは本番と同じエントリポイントを使う。** `frontend/next.config.ts`は
   `output: "standalone"`（本番Dockerfileが`node server.js`で起動する構成）のため、
   `playwright.config.ts`のwebServerも`npm run build && npm run start:standalone`
   （`frontend/scripts/prepare-standalone.mjs`でDockerfileのCOPY相当を再現してから
   `node .next/standalone/server.js`を起動）を使う。以前は`next start`
   （`npm run start`）を使っていたが、standalone構成とは組み合わせ不可という警告が
   出ており、standalone構成固有の問題（静的アセット配置ずれ等）をE2Eが検知できない
   状態だった（T252併用導入の実機検証で発覚、2026-08-23）。
2. **ローカル実行はworkers=1に固定する。** `playwright.config.ts`の既定
   （CPU論理コア数ベースの並列worker）のまま実行すると、同一のwebServer（Next.js
   サーバー1プロセス）へ複数のヘッドレスChromiumが同時に地図（MapLibre GL・WASM）を
   読み込みに行き、ページ遷移・`beforeEach`フックが軒並み30秒タイムアウトする事象を
   複数回実測した（2026-08-23）。workers=1へ絞ると同条件で安定して全green。
   CIはGitHub Actions側のジョブ専有リソースを前提に対象外（`process.env.CI`判定）。

3. **「見たい画面まで進める段取り」は`e2e/fixtures.ts`のヘルパーを使い、テストごとに
   書き直さない。** モバイルはデスクトップと導線が別（下部タブバーとボトムシート）で、
   シートを開く・生成の完了を待つ書き方を外すとUIの中身を見る前に落ちる。
   `openMobileApp`（モック登録・390x812・goto）→`openMobileSheet`（タブを押して開く。
   ハイドレーション前のクリックは効かないため開くまで再試行する）→`generateRoutes`
   （距離指定→生成→完了待ち）の順に呼ぶ。保存される画面状態（レイヤーのON/OFF等）は
   クリックで作らず`seedStoredState`でlocalStorageへ与える。
4. **レイアウトの溢れは座標・幅を実測して押さえる。** 画面外へ出た要素もアクセシビリティ
   ツリーには残るため、role・名前で見つかることは「押せる」ことを意味しない。
   `scrollWidth`/`clientWidth`の比較と`boundingBox()`で確かめる（`e2e/mobile.spec.ts`の
   ヘッダー検査）。
5. **ロケータを当て推量で書かない。** 落ちたテストは`test-results/<テスト名>/
   error-context.md`へその時点の画面構造（role・アクセシブル名）を吐くので、
   実際の名前はそこで確かめる。

## パターン5: 外部クライアント・Redisのフェイクは共有モジュールから取る

`backend/tests/`直下の次のモジュールが、複数のテストで同じ形になるフェイクを持つ。
**新しいテストで同じものを書き写さず、ここからimportする**（ファイルごとに書き写すと、
上流の契約が変わったときの直し漏れがそのまま残る）。

| モジュール | 中身 | 使う場面 |
|---|---|---|
| `fake_tile_http.py` | `FakeResponse`・`FakeHttpClient` | タイル・バイナリをそのまま通すクライアント（`get(url)`だけを呼ぶもの） |
| `fake_api_http.py` | 同名2つ＋`FailingHttpClient`・`HttpStatusErrorHttpClient` | `simple_api_client`経由でJSON/CSVを引くクライアント（`get(url, params, timeout)`） |
| `fake_redis.py` | `FakeRedis`（`raise_on_get`/`raise_on_set`付き） | Redis cache-aside層。実Redis不要 |
| `admin_auth.py` | `AUTH_HEADERS`・`basic_auth_header()` | 管理画面API。認証情報を入れるのは`conftest.py`の`admin_credentials`フィクスチャ |
| `jma_area_fixtures.py` | 区域コード階層のサンプル＋`patch_area_lookup()` | 緯度経度→市区町村コード→area.jsonの順に引くサービス |

ファイル内の全テストが管理画面APIを叩く場合は、`admin_credentials`を毎テストの引数に
書く代わりに、autouseの薄いフィクスチャで受ける（`test_health.py`等）。

frontendは`frontend/src/testing/`が同じ役割を持つ。

| モジュール | 中身 | 使う場面 |
|---|---|---|
| `fetchMocks.ts` | `makeResponse()` | `vi.stubGlobal("fetch", ...)`へ渡すレスポンス |
| `emblaBrowserApis.ts` | `stubEmblaBrowserApis()` | Embla Carouselを含むコンポーネントの`beforeEach` |
| `imageDataPolyfill.ts` | `installImageDataPolyfill()` | canvasのフォールバックで`ImageData`を返す実装 |
| `axisDefinitionFixtures.ts` | `baseAxisDefinition()` | 軸スタジオのテストが土台に使う軸定義 |
| `routeFixtures.ts` | `makeRouteCandidate()` | ルート候補を組み立てるすべての場所（`e2e/fixtures.ts`も同じものを使う）。`RouteCandidate`は全フィールドが必須のため、置き場を分けるとフィールドが増えるたびに同じ数の差分が要る |
| `fakeDataStatusMap.ts` | `createFakeDataStatusMap()` | `computeLayerDataStatus`が読む3メソッドだけのフェイクmap |

## パターン6: 絞り込んだ母集団をループするテストは、空でないことを確かめる

実データ・生成物・定数表から条件で絞った一覧をループして要素ごとに検査する形は、
**母集団が0件になった瞬間に何も確かめないまま緑になる**。絞り込みの条件が実データ側の変化
（軸の設定変更・生成物の再取り込み・凡例の入れ替え）で当てはまらなくなっても、テストは
落ちずに黙る。

```python
picked = [m for m, s in SPECS.items() if isinstance(s, WayMaterialCoverageSpec)]
assert picked, "way材料のカバレッジ仕様が1件も無い"   # これが無いと下のループは空振りしうる
for material_id in picked:
    assert f" AS {material_id}" in sql
```

```ts
const expressionColors = COLOR_EXPRESSION.filter((i) => typeof i === "string" && i.startsWith("#"));
expect(expressionColors.length).toBeGreaterThan(0);
for (const color of expressionColors) { expect(legendColors.has(color)).toBe(true); }
```

この形を機械的に検出する仕組みは無い。空でないことの主張は**同じテストの中**に置く（別のテストにある主張は、このテストが
空振りしないことの根拠にならない）。

## パターン7: 環境変数に依存する挙動のテスト → 判断を純関数へ出し、テストは環境変数に触らない

frontendのvitestは`pool: "vmThreads"`で走るため、**`process.env`はテストファイルをまたいで
共有される**。モジュール状態と違い、あるファイルが立てた環境変数は並行実行中の別ファイルからも
見える。実装が環境変数を「呼び出しのたびに」読む設計（SSRでの参照を避けるために意図してそう
している）だと、別ファイルの期待値がその場で変わる——**単体では通るのにフルスイートでだけ
落ちるテスト**になり、しかも毎回同じ顔で落ちないため本物の退行を隠す。

`afterEach`で戻しても足りない。戻すまでの間に別ファイルが読むうえ、`process.env`ごと
差し替える（`process.env = { ...ORIGINAL }`）と`vi.stubEnv`の復元も壊れる。

**判断を、環境変数を引数で受ける純関数へ出す**。環境変数を読むのは分岐を持たない薄い関数だけに
し、テストはその純関数を呼ぶ（`lib/tileBaseUrl.ts: resolveTileBaseUrl`・
`lib/adminBasicAuth.ts: resolveAdminBasicAuth`）。

```ts
export function tileBaseUrl(): string {
  return resolveTileBaseUrl(process.env.NEXT_PUBLIC_TILE_BASE_URL, origin());
}
export function resolveTileBaseUrl(configured: string | undefined, origin: string | null): string { ... }
```

その値を**使う側**のテスト（URLの組み立て等）は、読み取り口のモジュールをモックして固定する。

```ts
vi.mock("@/lib/tileBaseUrl", () => ({ tileBaseUrl: () => "" }));
```

「テストが書き換える環境変数を、そのテスト自身の対象以外の実装も読んでいる」形と、
`process.env`ごとの差し替えを避ける。自分のテスト対象だけが読む環境変数
（`app/api/version/route.ts`の`RENDER_GIT_COMMIT`等）は、他へ波及しないため対象外。


## パターン8: テストが用意する状態は、本番で起こりうるものに限る

DBの制約・取込の順序から**作れない状態**をテストで作らない。作ると、その状態向けの分岐が
実装に残り続け、後で制約を足したときに一斉に落ちて「制約の方が悪い」と誤診される。

- **派生行を作るテストは、親を先に入れる**。区間（`road_edges`）は`osm_raw_ways`の派生で、
  `osm_way_id`はNOT NULL + FK。本番と同じ順（生wayを永続化してから、その派生のグラフを
  保存する）は`tests/road_graph_scaffolds.py: save_ways_and_graph`が1つ持つ——各テストで
  `save_raw_ways`→`save_graph`を写経しない。
- **値式が必ず値を返すものを「欠損」にしない**。真偽の材料は`COALESCE(条件, false)`で
  閉じるため、「材料が1つも無い区間」は作れない。その前提のテストは前提ごと消す
  （軸が算出できない状況を確かめたいなら、軸の集合を差し替えて表現する。
  `tests/test_evaluation_bulk.py`の`_only_axes`）。
- 制約を足した結果としてテストが大量に落ちたら、**テストの前提が本番と食い違っていた証拠**
  として読む（[T956](../records/tasks/T956.md)ではFK追加で45件が落ち、すべて親を入れていなかった）。
