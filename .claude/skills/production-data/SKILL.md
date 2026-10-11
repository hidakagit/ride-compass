---
name: production-data
description: "本番の派生データを作り直す・本番へ軸定義の変更を入れる・DBのバックアップを登録する・本番DBを失ったときに戻す手順。本番のデータに触る作業の前に使う。"
---

この手順のうち本番へ書く操作（本番VM・本番DB・本番の管理APIへ打つもの）は、開発機の対話のセッションが
`.claude/skills/dev-session/SKILL.md`の「本番へ書く」のとおり打つ。担当は打たない。

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
  本番へ効かせるなら本番の軸スタジオか、次の道具で行う。環境間で内容を転送する仕組みは持たない。
  **リポジトリは軸の写しを持たない**ため、再ダンプの手順は無い。
- 変える中身が決まっている変更（タスクで値を決めた軸の書き換え・追加・削除）は、軸1本の定義のJSONを作り、
  `backend/scripts/axis_apply.py`で入れる
  （仕組みは[axis-studio.md](../../../docs/modules/backend/axis-studio.md)「軸の定義をファイルから本番へ入れる」）:

  ```
  python scripts/axis_apply.py <JSONのパス>               # 差を出すだけ
  python scripts/axis_apply.py <JSONのパス> --apply <指紋>  # 書く
  python scripts/axis_apply.py --delete <axis_id> [--apply <指紋>]
  ```

  差（項目ごとの「前 → 後」）と指紋をチャットで見せ、書くよう言われてから、同じ指紋で書く。宛先と認証情報は
  `backend/.env.oracle.local`の`BACKEND_ORIGIN`（本番backendの直接のオリジン）・`ADMIN_BASIC_AUTH_USERNAME`・
  `ADMIN_BASIC_AUTH_PASSWORD`に置く。
  本番の写しとして直し続けない（次に変えるときは本番の今の定義から新しいJSONを作る）。
- 書けたかの確かめ: 道具が「反映を確かめました」を出したこと。
  画面で変えたときは、本番の`GET /api/axis-catalog`で変えた軸を確かめる。

## 付録

作業の前には読まない。一度きりの準備（登録）と、災害時の手順。

### DBのバックアップ

- 対象: 本番DBの全体（管理画面で積み上げた軸の定義・較正値の上書き、生データ・派生データ）。
  仕組みは[横断基盤](../../../docs/modules/backend/cross-cutting-infrastructure.md)「本番DBのバックアップ」。
- ルール: 本番VMのsystemdのtimerが毎日03:17（日本時間）に、DBの全体を`pg_dump`（custom形式・圧縮あり）して、
  Oracle Cloud Object Storageの非公開バケットへ`db/<UTCの時刻>.dump`として置き、前の回のものを消す。残すのは、バケットに
  1個（無料の枠の10GBに1個だけ入る）と、VMのDBのディスクの`/mnt/pgdata/ridecompass-backup/latest.dump`に1個。
  置けたら時刻を書き、backendの`/health`が`admin_data_backup_age_hours`（最後に置けてからの時間）を返す。
  **VMを作り直したら、下の登録の1.〜5.をやり直す**。
- 登録（1回。Oracle Cloudのコンソールと、VMにSSHで入って打つ）:
  1. バケットを作る: コンソールの Storage → Buckets で、ホームリージョンに
     標準の層・既定の見え方（公開しない）で作る（例: `ridecompass-admin-data`）。ネームスペースは同じ画面か、
     テナンシの詳細の「Object Storage namespace」に出る。
  2. VMを動的グループに入れる: Identity → Dynamic groups で、ルール`instance.id = '<VMのインスタンスのOCID>'`
     の動的グループを作る（例: `ridecompass-vm`。OCIDはコンソールのインスタンスの詳細に出る）。
  3. そのバケットのオブジェクトの一覧・作成・削除だけを許す: Identity → Policies で、バケットのあるコンパートメントに次の3文のポリシーを作る。
     ```
     Allow dynamic-group ridecompass-vm to manage objects in compartment <コンパートメント名> where all {target.bucket.name='ridecompass-admin-data', request.permission='OBJECT_INSPECT'}
     Allow dynamic-group ridecompass-vm to manage objects in compartment <コンパートメント名> where all {target.bucket.name='ridecompass-admin-data', request.permission='OBJECT_CREATE'}
     Allow dynamic-group ridecompass-vm to manage objects in compartment <コンパートメント名> where all {target.bucket.name='ridecompass-admin-data', request.permission='OBJECT_DELETE'}
     ```
     動的グループをDefault以外のアイデンティティ・ドメインに作ったときは、`dynamic-group '<ドメイン名>'/'ridecompass-vm'`と書く。
     バケットがテナンシのルートのコンパートメントにあるときは、`in compartment <コンパートメント名>`の代わりに`in tenancy`と書く
     （場所の書き方は公式の文書「Policy Syntax」の Location）。4.も同じ。ルートを`compartment`で書くと、コンソールが
     `Compartment {<ルートの名前>} does not exist or is not part of the policy compartment subtree`で断る。
  4. 送りかけで残った部分を消す: 大きな書き出しは分割して送られ、送る途中で落ちると、送り終えた部分が枠を使ったまま残る。
     Object Storageのサービスにバケットのオブジェクトを扱う権限を与え（公式の文書「Using Object Lifecycle Policies」）、
     Identity → Policies で、**テナンシのルートのコンパートメント**に次の1文のポリシーを作る（`<リージョン>`はバケットのある
     リージョンの識別子。例: `ap-tokyo-1`）。
     ```
     Allow service objectstorage-<リージョン> to manage object-family in compartment <コンパートメント名>
     ```
     続けて Storage → Buckets → バケット → Policies の「Lifecycle policy rules」で Create Rule を押し、Lifecycle target を
     Uncommitted multipart uploads・Lifecycle action を Delete・日数を1にして作る。規則が効き始めるまで最大24時間かかる（同じ文書）。
  5. VMで設定ファイルを置き、ユニットを登録し、1回打って確かめてからtimerを有効にする（ユニットはデプロイが
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
     1回は30分ほどかかる。`journalctl`の最後に「DBの全体を置きました object=db/…」が出て、コンソールのバケットにそのオブジェクトが
     1個だけ見え、`curl -fsS http://localhost:8000/health`の`admin_data_backup_age_hours`が0.0なら済み。
- 動いているかを見る: backendの`/health`の`admin_data_backup_age_hours`。詳しくはVMで`systemctl list-timers ridecompass-admin-data-backup.timer`
  （前回・次回）と`sudo journalctl -u ridecompass-admin-data-backup.service --since -2d`。

### 本番DBを失ったとき

- 対象: 本番DB（またはVMごと）を失った・誤操作で壊したとき。
- 戻る材料: 上の「DBのバックアップ」の書き出し1個。戻すと、DBは書き出した時点の全体（管理データ・生データ・派生データ）になる。
  それより後の管理画面の変更と取込は戻らないので、要るならやり直す。
- 戻すファイルを取る: VMが残っていれば`/mnt/pgdata/ridecompass-backup/latest.dump`を使う。VMを失ったときは、コンソールの
  Storage → Buckets → バケット → `db/`のオブジェクトをダウンロードし、`scp`で新しいVMのDBのディスク（例: `/mnt/pgdata/restore.dump`）へ送る。
- 戻す順番（本番VMで。DB名・利用者は`/home/ubuntu/ridecompass-backend.env`の`DATABASE_URL`のもの）:
  1. backendを止める: `sudo docker stop ridecompass-backend`（コンテナが無ければ飛ばす）
  2. DBが無ければ、利用者とDBを作る（利用者は書き出しに入らない）:
     ```
     sudo -u postgres createuser --pwprompt <利用者>
     sudo -u postgres createdb --owner=<利用者> <DB名>
     ```
  3. 戻す（表を作り直して行を入れる。数十分かかる）:
     ```
     sudo chmod 644 <ファイル>
     sudo -u postgres pg_restore --clean --if-exists --jobs=4 --dbname=<DB名> <ファイル>
     ```
  4. 書き出しのあとに派生を作り直していたら、道路網の配列の置き場（`/home/ubuntu/ridecompass-cache-data/road_network/`の中）を消す
     （戻したDBより新しい世代の置き場が残ると、backendはそれを読む）。
  5. `deploy-backend.yml`を`workflow_dispatch`で打つ（ラスタを取り、道路網の配列が無ければ作り、backendを起動する）。
     戻ったことを確かめる:
     ```
     curl -fsS http://localhost:8000/health
     curl -fsS http://localhost:8000/api/axis-catalog | head -c 300
     sudo docker logs --tail 50 ridecompass-backend 2>&1 | grep -E '軸定義|AxisDefinitionSyncError|TuningOverrideError'
     ```
     `/health`が応答し、ログに「軸定義をDBから読み込みました axes=<戻した軸の数>」が出ていれば済み。
  6. VMを作り直したときは、上の「DBのバックアップ」の登録の5.をやり直す。
