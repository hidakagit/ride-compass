---
name: production-data
description: "本番の派生データを作り直す・本番へ軸定義の変更を入れる・管理データのバックアップを登録する・本番DBを失ったときに戻す手順。本番のデータに触る作業の前に使う。"
---

## 派生データの作り直し

- 対象: 管理画面の「派生データの鮮度」が作り直し待ちを出したとき（古い理由がどれであっても打つのは同じ
  1コマンド。`app/batch/derive_cli.py`が段の順に作り直す単一の入口）。
- ルール: **本番VM（SSHで入る）で、稼働中のbackendコンテナではなく別のコンテナをメモリ上限付きで立てて**
  打つ:

  ```
  sudo docker run --rm --network=host --memory=4g \
    -v /home/ubuntu/ridecompass-cache-data:/app/data \
    --env-file /home/ubuntu/ridecompass-backend.env \
    ridecompass-backend:latest \
    python -m app.batch.derive_cli
  ```

- 住所の区画の段は、住所の生データ（`abr`）の取込が無いと止まり、作り直し全体が何も入れ替えない。初めて流す前と住所を取り直すときは、
  同じ別のコンテナで取得と取込を先に打つ（手順は[data-sources.md](../../../docs/architecture/data-sources.md)「住所の区画の元データ」）。

- **`/app/data`のマウントを外さない**（同じ入口が道路網全体の配列`data/road_network/`を作ってから表を入れ替える。配列は本番で数分かかる）。
  途中で落ちたとき（配列を作れなかったときを含む）は何も入れ替わらないので、原因を直して打ち直す。
- 取込（`app.batch.ingest_cli`）は派生の表・派生の世代・道路網の配列を変えない。取り込んだら続けて派生を作り直す。
- 作り直しは、入力（読むソースの取込・前の段・較正値・書く表の列・段のコード・実行環境の版）が前回の作り直しと同じ段を
  流さず、ログに「段 <名前> を飛ばした」と出す。全部の段が同じなら何も入れ替えずに終える。段を選んで流す口は無く、
  どの場面（取り直した・段のやり方を変えた・較正値を変えた・列を足した）でも上の1コマンドを打つ。
- 取込と作り直しは同時に走らない（後から始めた方が止まる。終わってから打ち直す）。
  仕組みは[静的道路属性](../../../docs/modules/backend/static-road-attributes.md)「派生」。

## 本番へ効かせたい軸定義の変更は、本番の管理APIへ入れる

- 対象: `axis_admin`のAPI（各環境の軸スタジオGUI、直接API呼び出し、または下の道具）経由で
  `axis_definitions`等のDB行データを変更する全ての作業。
- ルール: **DBは環境ごとに独立していて、その環境の管理画面がそのDBをメンテナンスする**。
  開発DBだけ変えてタスクを完了扱いにしない
  ——本番へ効かせるなら本番の軸スタジオか、次の道具で行う。環境間で内容を転送する仕組みは持たない。
  **リポジトリは軸の写しを持たない**ため、再ダンプの手順は無い。
- 変える中身が決まっている変更（タスクで値を決めた軸の書き換え・追加・削除）は、軸1本の定義のJSONを作り、
  `backend/scripts/axis_apply.py`で入れる
  （仕組みは[axis-studio.md](../../../docs/modules/backend/axis-studio.md)「軸の定義をファイルから本番へ入れる」）:

  ```
  python scripts/axis_apply.py <JSONのパス>               # 差を出すだけ
  python scripts/axis_apply.py <JSONのパス> --apply <指紋>  # 書く
  python scripts/axis_apply.py --delete <axis_id> [--apply <指紋>]
  ```

  担当は打たず、開発機の対話のセッションがユーザーがチャットで言ったときだけ打つ
  （[dev-session/SKILL.md](../dev-session/SKILL.md)「本番へ書く」）。差（項目ごとの「前 → 後」）と指紋をチャットで見せ、書くよう言われてから、同じ指紋で書く。宛先と認証情報は
  `backend/.env.oracle.local`の`BACKEND_ORIGIN`（本番backendの直接のオリジン）・`ADMIN_BASIC_AUTH_USERNAME`・
  `ADMIN_BASIC_AUTH_PASSWORD`に置く。JSONは`docs/records/`へ置かない（記録はタスクの issue に書く）。
  本番の写しとして直し続けない（次に変えるときは本番の今の定義から新しいJSONを作る）。
- 完了の条件: 道具が「反映を確かめました」を出したこと。
  画面で変えたときは、本番の`GET /api/axis-catalog`で変えた軸を確かめる。

## 付録

作業の前には読まない。一度きりの準備（登録）と、災害時の手順。

### 管理データのバックアップ

- 対象: 取り直せない管理データ（軸の定義・較正値の上書き等。ORMで`IRREPLACEABLE`の印を持つ表）。
  仕組みは[横断基盤](../../../docs/modules/backend/cross-cutting-infrastructure.md)「取り直せない管理データのバックアップ」。
- ルール: 本番VMのsystemdのtimerが毎日03:17（日本時間）に、その表を`pg_dump`してOracle Cloud Object Storageの
  非公開バケットへ`admin-data/<UTCの時刻>.dump`として置く。バケットにはライフサイクルの規則で直近30日だけを残す
  （消すのはObject Storageの規則）。置けたら時刻を書き、backendの`/health`が
  `admin_data_backup_age_hours`（最後に置けてからの時間）を返す。読んで知らせる見張りは無い。
  **VMを作り直したら、下の登録の1.〜4.をやり直す**。
- 登録（1回。Oracle Cloudのコンソールと、VMにSSHで入って打つ）:
  1. バケットを作る: コンソールの Storage → Buckets で、ホームリージョンに
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
     （場所の書き方は公式の文書「Policy Syntax」の Location）。5.も同じ。ルートを`compartment`で書くと、コンソールが
     `Compartment {<ルートの名前>} does not exist or is not part of the policy compartment subtree`で断る。
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
  5. 30日より古いものを消す: Object Storageのサービスにバケットのオブジェクトを扱う権限を与える
     （公式の文書「Using Object Lifecycle Policies」）。Identity → Policies で、**テナンシのルートのコンパートメント**に
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
- 戻る材料: 生データは取り直し、派生データは生データから作り直す。管理データは上の「管理データのバックアップ」が
  バケットに置いた`pg_dump`のファイルから戻す。
- 戻すファイルを取る: コンソールの Storage → Buckets → バケット → `admin-data/`で、一番新しいオブジェクトを
  ダウンロードし、`scp`でVMの`/tmp/admin-data.dump`へ送る。
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
     `-v /home/ubuntu/ridecompass-raster:/app/raster:ro`も足す（ラスタはDBと別にVMに置き、`deploy-backend.yml`が取得してbackendへ同じ形で載せる）
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
- 管理データの表だけを誤操作で壊したとき: 2.と4.だけを行う。
- 4.より前に2.を済ませる（backendは軸が0行だと起動しない。[axis-studio.md](../../../docs/modules/backend/axis-studio.md)「まっさらなDBに軸の行は入らない」）。
