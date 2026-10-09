# デプロイ・DB同期の作業標準

コード変更と本番環境（DB・デプロイ）を揃えるために、作業の完了条件へ何を含めるかの決まり。モジュールの設計・実装の事実は
`docs/modules/*.md`が持つ。

## コミットと同時に揃えるもの

次は、変更と**同一コミットで**行う。

- **backend側のAPIルーター・Pydanticモデル・レジストリ・domain定数を変更したら**、
  `backend/scripts/export_openapi.py`→`cd frontend && npm run generate:api`を実行し、
  `git diff --exit-code -- frontend/src/types/generated/`がクリーンであることを確認する。
- **API・ドメイン概念・レイヤー種を新設するタスクは、完了条件へ
  docs/architecture/・docs/modules/の追従を既定で含める**。今のコードの動き（「現状」）はdocs/modules/が持ち、
  docs/architecture/は構造の約束と外部の制約を持つ（docs/architecture/README.md「書き分け」）。
- **既存の仕組みと技術的に別方式の新しい配信・レンダリング機構（例: タイル焼き込み済み
  ramp軸に対する、フィーチャーの鍵で値を配る`dedicated_way_value_layer`）を新設するときは、
  着手前に`docs/architecture/design-principles.md`の構造仕様3・8（1本道の追加点）がこの新しい機構にも
  適用されるかを点検し、適用されるなら軸ごとのファイル・関数・定数・propを新設しない
  汎用設計にする**。
- **MVT焼き込み値（CASE式・材料タグ・domain純関数）を変更したら**、生成物
  （region-tile-config.json）を再生成する（タイル世代そのものは焼き込みSQLから
  導出されるため手で上げない。`app/infrastructure/cache_identity.py`参照）。
- **評価軸（`axis_definitions`テーブル）の新規追加・削除・既存軸の`shape_params`調整は、
  すべて`axis_admin`のAPI（軸スタジオのGUI、または直接API呼び出し。新規追加=POST、
  削除=unpublish→DELETE、公開軸の調整=unpublish→PUT→republish）経由で行う。**
  **正本は本番DBだけ**で、リポジトリは軸の写しを持たない——スキーマはORMの宣言から
  `create_tables()`が作り、軸の中身は実行時の`GET /api/axis-catalog`がフロントへ配る。
  `create_tables()`はまっさらなDB向けで、本番の既存の表は宣言を変えても追従しない。差は人が本番で埋め、
  デプロイが入れ替えの後に測る（docs/architecture/tech-stack.md「デプロイの反映確認（backend/frontendで注入元が異なる）」の`schema_gap.py`）。
  ビルド時の生成物（`frontend/src/types/generated/`）はすべてコードの宣言から決まり、DBを読まない。
  完了扱いにする条件は下の「本番へ効かせたい軸定義の変更は、本番の管理APIへ入れる」。
- **既存DBの行データを新しいコードが読めなくなる変更（Pydanticモデルの破壊的変更等）を
  含む`backend/**`の変更は、本番DBのデータ移行を完了させてからmasterへ入れる（マージする）**。
  masterに入ってCI（`.github/workflows/ci.yml`）が通ると、backendは本番へ自動デプロイされ
  （コンテナを入れ替えるかの振り分けは`scripts/deploy_backend_gate.py`が正本）、自動のデプロイを止める仕組みは無い。
  旧形式のデータが残ったままだと、`refresh_axis_definitions`等のfail-fastで本番backendが起動しない。
  作業ブランチへのpushでは本番へ出ない。対応順序は事前に次のどちらかを選ぶ: 1) 本番DBのデータ移行を先に完了させてから
  マージする（移行がすぐできなければ、終わるまでmasterへ入れずに待つ）、2) 新旧両方の形式を一時的に許容する後方互換コードを
  経由して段階的に移行する。

## 派生データの作り直し

- 対象: 管理画面の「派生データの鮮度」が作り直し待ちを出したとき（古い理由がどれであっても打つのは同じ
  1コマンド。`app/batch/derive_cli.py`が段の順に作り直す単一の入口）。
- ルール: **本番VM（SSHで入る）で、稼働中のbackendコンテナではなく別のコンテナをメモリ上限付きで立てて**
  打つ（上限を超えても止まるのはバッチだけで、サービスは止まらない）:

  ```
  sudo docker run --rm --network=host --memory=4g \
    -v /home/ubuntu/ridecompass-cache-data:/app/data \
    --env-file /home/ubuntu/ridecompass-backend.env \
    ridecompass-backend:latest \
    python -m app.batch.derive_cli
  ```

- 住所の区画の段は、住所の生データ（`abr`）の取込が無いと止まり、作り直し全体が何も入れ替えない。初めて流す前と住所を取り直すときは、
  同じ別のコンテナで取得と取込を先に打つ（手順は[data-sources.md](../architecture/data-sources.md)「住所の区画の元データ」）。
- 同じ入口が、作り直した表から道路網全体の配列（ルート生成が読む。`data/road_network/`）を作ってから
  表を入れ替える（配列は本番で数分）。**`/app/data`のマウントを外さない**——外すと配列がコンテナと一緒に
  消え、表だけが入れ替わってルート生成は古い配列を読み続ける。途中で落ちたとき（配列を作れなかったときを
  含む）は何も入れ替わらず、backendは前の表と配列を読み続けるので、原因を直して打ち直す。
- 分布の前後: 作り直すたびに、上のコマンドを打つ前と終わった後に、派生の表の全部の値の列の分布を本番で測る
  （開発機の`backend`から`python scripts/run_probe.py scripts/derived_distribution.py`。`--column`を付けなければ
  全部の派生の表の全部の値の列を1回で測る）。前と後の出力を、作り直しを頼んだタスクの issue にコメントで書く。
  前後で大きく動いた列があれば、その作り直しに含まれた変更（前の作り直しの後に master へ入った、派生の値に届く変更）を疑う。
  落ちた絞り込み・二重に数えた値はエラーにもテストの失敗にもならず値の偏りとしてだけ現れるので、値を変えるつもりのない変更もこの記録で確かめる。
- 取込（`app.batch.ingest_cli`）は派生の表・派生の世代・道路網の配列を変えない。地図のタイルは生データも
  直接読むため、成功した取込は配信するタイルの世代を進める（読み直しのTTLの後から、全系統のタイルを
  新しい生データで焼き直す）。取り込んだら続けて派生を最初から作り直す。
- 作り直しは、どの取込から作ったかを全ソースぶん（表`derived_source_runs`）、どの列の表を作ったかを派生の表ごと
  （表`derived_columns`）に記録する。取込と作り直しは同時に走らない（後から始めた方が止まる。終わってから打ち直す）。
  途中の段から流す`--from`は、生データか派生の表の列が前の作り直しの記録から変わっていれば止まる（`--from`を外して最初から流す）。
  仕組みは[静的道路属性](../modules/backend/static-road-attributes.md)「派生」。
- 手元の端末から打たない（見えるのは開発用のDBで、本番は変わらない）。

## backendを先に出した窓では、frontendが新しい材料を知らない

- 対象: 材料（`material_catalog`）・一次属性・レジストリを増やす変更。
- ルール: backendをデプロイしてからfrontendをデプロイするまでの間、軸スタジオで新しい材料を使う軸を触らない。
  両方のデプロイが終わったことを確認してから編集する。
- なぜ: その間はfrontend側のカタログにその材料が無く、画面はエラーを出さずに材料を「組み合わせる軸」の側として扱うので、
  保存すると**軸の中身が変わって書き戻る**。

## 本番へ効かせたい軸定義の変更は、本番の管理APIへ入れる

- 対象: `axis_admin`のAPI（各環境の軸スタジオGUI、直接API呼び出し、または下の道具）経由で
  `axis_definitions`等のDB行データを変更する全ての作業。
- ルール: **DBは環境ごとに独立していて、その環境の管理画面がそのDBをメンテナンスする**。
  開発DBだけ変えてタスクを完了扱いにしない——本番へ効かせるなら本番の軸スタジオか、次の道具で行う。
  環境間で内容を転送する仕組みは持たず、リポジトリは軸の写しを持たない。
- 変える中身が決まっている変更（タスクで値を決めた軸の書き換え・追加・削除）は、軸1本の定義のJSONを作り、
  `backend/scripts/axis_apply.py`で入れる
  （仕組みは[axis-studio.md](../modules/backend/axis-studio.md)「軸の定義をファイルから本番へ入れる」）:

  ```
  python scripts/axis_apply.py <JSONのパス>               # 差を出すだけ
  python scripts/axis_apply.py <JSONのパス> --apply <指紋>  # 書く
  python scripts/axis_apply.py --delete <axis_id> [--apply <指紋>]
  ```

  道具は本番の管理APIを読み書きするので、担当は打たず、開発機の対話のセッションがユーザーがチャットで言ったときだけ打つ
  （[flow.md](flow.md)「開発機の対話のセッション」の「本番へ書く」）。差（項目ごとの「前 → 後」）と指紋をチャットで見せ、書くよう言われてから、同じ指紋で書く。宛先と認証情報は
  `backend/.env.oracle.local`の`BACKEND_ORIGIN`（本番backendの直接のオリジン）・`ADMIN_BASIC_AUTH_USERNAME`・
  `ADMIN_BASIC_AUTH_PASSWORD`に置く。JSONは1回当てたら役目を終えるもので、リポジトリへは置かず（記録はタスクの issue に書く）、
  本番の写しとして直し続けない（次に変えるときは本番の今の定義から新しいJSONを作る）。
- 完了の条件: 道具が「反映を確かめました」を出したこと（管理APIと公開の軸カタログの両方で見ている）。
  画面で変えたときは、本番の`GET /api/axis-catalog`で変えた軸を確かめる。

## 付録

作業の前には読まない。一度きりの準備（登録）と、災害時の手順。

### 管理データのバックアップ

- 対象: 取り直せない管理データ（軸の定義・較正値の上書き等。ORMで`IRREPLACEABLE`の印を持つ表）。
  仕組みは[横断基盤](../modules/backend/cross-cutting-infrastructure.md)「取り直せない管理データのバックアップ」。
- ルール: 本番VMのsystemdのtimerが毎日03:17（日本時間）に、その表を`pg_dump`してOracle Cloud Object Storageの
  非公開バケットへ`admin-data/<UTCの時刻>.dump`として置く。バケットにはライフサイクルの規則で直近30日だけを残す
  （VMには消す権限が無いので、消すのはObject Storageの規則）。置けたら時刻を書き、backendの`/health`が
  `admin_data_backup_age_hours`（最後に置けてからの時間）を返す。これを読んで知らせる見張りは無い。
  **VMを作り直したら、下の登録の1.〜4.をやり直す**（timerの登録とバケットへ書く権限は、VMとそのインスタンスのOCIDに付く）。
- 登録（1回。Oracle Cloudのコンソールと、VMにSSHで入って打つ）:
  1. バケットを作る: コンソールの Storage → Buckets で、ホームリージョン（無料枠はホームリージョンだけ）に
     標準の層・既定の見え方（公開しない）で作る（例: `ridecompass-admin-data`）。ネームスペースは同じ画面か、
     テナンシの詳細の「Object Storage namespace」に出る。
  2. VMを動的グループに入れる: Identity → Dynamic groups で、ルール`instance.id = '<VMのインスタンスのOCID>'`
     の動的グループを作る（例: `ridecompass-vm`。OCIDはコンソールのインスタンスの詳細に出る）。
  3. 書く権限を1つだけ与える: Identity → Policies で、バケットのあるコンパートメントに次の1文のポリシーを作る。
     ```
     Allow dynamic-group ridecompass-vm to manage objects in compartment <コンパートメント名> where all {target.bucket.name='ridecompass-admin-data', request.permission='OBJECT_CREATE'}
     ```
     動的グループをDefault以外のアイデンティティ・ドメインに作ったときは、`dynamic-group '<ドメイン名>'/'ridecompass-vm'`と書く。
     バケットがテナンシのルートのコンパートメントにあるときは、`in compartment <コンパートメント名>`の代わりに`in tenancy`と書く
     （ルートは`compartment`で名指せない。場所の書き方は公式の文書「Policy Syntax」の Location）。5.も同じ。
  4. VMで設定ファイルを置き、ユニットを登録し、1回打って確かめてからtimerを有効にする（ユニットはデプロイが
     揃える作業コピーのものを`systemctl link`で指す）:
     ```
     sudo mkdir -p /etc/ridecompass
     printf 'OCI_NAMESPACE=%s\nBACKUP_BUCKET=%s\n' '<ネームスペース>' 'ridecompass-admin-data' | sudo tee /etc/ridecompass/admin-data-backup.env
     sudo systemctl link /home/ubuntu/ridecompass-repo/backend/ops/ridecompass-admin-data-backup.service \
       /home/ubuntu/ridecompass-repo/backend/ops/ridecompass-admin-data-backup.timer
     sudo systemctl start ridecompass-admin-data-backup.service
     sudo journalctl -u ridecompass-admin-data-backup.service -n 30 --no-pager
     sudo systemctl enable --now ridecompass-admin-data-backup.timer
     systemctl list-timers ridecompass-admin-data-backup.timer
     ```
     `journalctl`の最後に「管理データを置きました object=admin-data/…」が出て、コンソールのバケットにそのオブジェクトが
     見え、`curl -fsS http://localhost:8000/health`の`admin_data_backup_age_hours`が0.0なら済み。
  5. 30日より古いものを消す: Object Storageの規則は、Object Storageのサービスにバケットのオブジェクトを扱う権限が無いと
     動かない（公式の文書「Using Object Lifecycle Policies」）。Identity → Policies で、**テナンシのルートのコンパートメント**に
     次の1文のポリシーを作る（`<リージョン>`はバケットのあるリージョンの識別子。例: `ap-tokyo-1`）。
     ```
     Allow service objectstorage-<リージョン> to manage object-family in compartment <コンパートメント名>
     ```
     バケットがルートのコンパートメントにあるときは、3.と同じく`in tenancy`と書く。
     続けて Storage → Buckets → バケット → Policies の「Lifecycle policy rules」で Create Rule を押し、Lifecycle action を
     Delete・日数を30・Object name filters の prefix を`admin-data/`にして作る。規則が効き始めるまで最大24時間かかる（同じ文書）。
- 動いているかを見る: backendの`/health`の`admin_data_backup_age_hours`。詳しくはVMで`systemctl list-timers ridecompass-admin-data-backup.timer`
  （前回・次回）と`sudo journalctl -u ridecompass-admin-data-backup.service --since -2d`。
- `backend/ops/`のユニットの中身を変えたコミットがデプロイされたら、VMで`sudo systemctl daemon-reload`を打つ
  （シェルの中身は次の回から新しいものが読まれる）。

### 本番DBを失ったとき

- 対象: 本番DB（またはVMごと）を失った・管理データの表を誤操作で壊したとき。
- 戻る材料: 生データは外部に正本があり取り直せる。派生データは生データから作り直せる。**取り直せないのは
  管理データだけ**で、これは上の「管理データのバックアップ」がバケットに置いた`pg_dump`のファイルから戻す。
- 戻すファイルを取る: コンソールの Storage → Buckets → バケット → `admin-data/`で、一番新しいオブジェクトを
  ダウンロードし、`scp`でVMの`/tmp/admin-data.dump`へ送る（VMにはバケットを読む権限を与えていない）。
- 作り直しの順番（本番VMで。1.と3.は上の「派生データの作り直し」と同じ形の使い捨てのコンテナで打つ）:
  1. スキーマを作る: `python scripts/bootstrap_database.py --to schema`（拡張が無ければ、何をスーパーユーザーで
     打てばよいかを言って止まる）
  2. 管理データを戻す（ホストで。DB名は`/home/ubuntu/ridecompass-backend.env`の`DATABASE_URL`の最後の部分）:
     ```
     sudo chmod 644 /tmp/admin-data.dump
     sudo -u postgres pg_restore --clean --if-exists --single-transaction --dbname=<DB名> /tmp/admin-data.dump
     ```
  3. 取り込んで派生を作る: `python scripts/bootstrap_database.py --from ingest`（外部ソースのファイルは先に
     手元へ写しておく。何を写すかは`bootstrap_database.py`の冒頭）。このコンテナには
     `-v /home/ubuntu/ridecompass-raster:/app/raster:ro`も足す——土地被覆の取込はラスタを読み、
     ラスタはDBと別にVMに置く（`deploy-backend.yml`が取得してbackendへ同じ形で載せる）
  4. backendのコンテナを起動し直し（`sudo docker restart ridecompass-backend`、コンテナが無ければ
     `deploy-backend.yml`を`workflow_dispatch`で打つ）、戻ったことを確かめる:
     ```
     curl -fsS http://localhost:8000/health
     curl -fsS http://localhost:8000/api/axis-catalog | head -c 300
     sudo docker logs --tail 50 ridecompass-backend 2>&1 | grep -E '軸定義|AxisDefinitionSyncError|TuningOverrideError'
     ```
     `/health`が応答し、ログに「軸定義をDBから読み込みました axes=<戻した軸の数>」が出ていれば済み。軸・較正値が
     アプリの検査に通らなければ起動が止まり（`AxisDefinitionSyncError`等）、`/health`は応答しない——そのときは
     1つ前の日のファイルで2.からやり直す。
- 管理データの表だけを誤操作で壊したとき: 2.と4.だけを行う（2.は表を消して作り直してから入れるのを1つの
  トランザクションで行うので、途中で落ちれば何も変わらない）。
- 順番の理由: 2.は表を作り直すので1.の後でも通り、取込・派生とは互いに読まない。backendは軸が0行だと起動しない
  （[axis-studio.md](../modules/backend/axis-studio.md)「まっさらなDBに軸の行は入らない」）ので、4.より前に2.を済ませる。
