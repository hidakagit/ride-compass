# デプロイ・DB同期の作業標準

コード変更と本番環境（DB・デプロイ）の同期に関する作業標準をまとめる。
CLAUDE.md「コミット時の同期ルール」から参照される。個々のモジュールの設計・実装事実は
ここに書かない（`docs/modules/*.md`が正）。ここに書くのは「作業として何を完了条件に
含めるべきか」という運用ルールのみ。

本番DBを失ったときの作り直しは下の「本番DBを失ったとき」、派生データの作り直しは
「派生データの作り直し」。

軸定義を軸スタジオに何をさせるかは
[axis-definition-maintenance-split.md](../records/decisions/axis-definition-maintenance-split.md)。

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

- 作り直しの最後に、同じ入口が道路網全体の配列（ルート生成が読む。`data/road_network/`）を作る
  （本番で数分）。**`/app/data`のマウントを外さない**——外すと配列がコンテナと一緒に消え、ルート生成は
  古い配列を読み続ける。配列だけ作れなかったときは終了コードが1になるので、
  `python scripts/build_road_network.py`を同じ形のコンテナで打ち直す。
- なぜ: 手元の端末で打つと、そこから見えるのは開発用のDBで、本番は古いまま変わらない。稼働中のbackendの
  コンテナの中で走らせると、そのコンテナのメモリ上限まで使い切ったときにコンテナごとOOM killされ、
  サービス全体が止まる。別のコンテナを`--memory`付きで立てれば、上限を超えても止まるのはバッチだけで済む。

## 本番DBを失ったとき

- 対象: 本番DB（またはVMごと）を失った・管理データの表を誤操作で壊したとき。
- 戻る材料: 生データは外部に正本があり取り直せる。派生データは生データから作り直せる。**取り直せないのは
  管理データ（軸の定義・較正値の上書き等）だけ**で、これは`scripts/admin_data_backup.py dump`が書き出した
  JSON（管理データのバックアップ）から戻す。書き出しはアプリが起動できない中身では失敗するので、書き出した
  JSONは書き出した時点のコードでは戻せる。軸の形を変えるコードの変更の後は、戻すときの検算で止まりうる
  （止まれば何も書かれない。[横断基盤](../modules/backend/cross-cutting-infrastructure.md)
  「取り直せない管理データのバックアップ」）。
- 手元へ書き出す（VMにSSHで入れるとき）:

  ```
  ssh <VM> "sudo docker run --rm --network=host --env-file /home/ubuntu/ridecompass-backend.env \
    ridecompass-backend:latest python scripts/admin_data_backup.py dump" > admin-data.json
  ```

- 作り直しの順番（本番VMでは、上の「派生データの作り直し」と同じ形の使い捨てのコンテナで打つ。
  JSONは`-v <置いた場所>:/tmp/admin-data.json:ro`で渡す）:
  1. スキーマを作る: `python scripts/bootstrap_database.py --to schema`（拡張が無ければ、何をスーパーユーザーで
     打てばよいかを言って止まる）
  2. 管理データを戻す: `python scripts/admin_data_backup.py restore /tmp/admin-data.json`
  3. 取り込んで派生を作る: `python scripts/bootstrap_database.py --from ingest`（外部ソースのファイルは先に
     手元へ写しておく。何を写すかは`bootstrap_database.py`の冒頭）
  4. backendのコンテナを起動し直す（軸と較正値は起動時に読む）
- 管理データの表だけを誤操作で壊したとき: 2.を`--replace`付きで打ち（同じトランザクションの中で消して
  から入れる）、4.だけを行う。
- なぜこの順か: 2.は表があれば通り、取込・派生とは互いに読まない。backendは軸が0行だと起動しない
  （[axis-studio.md](../modules/backend/axis-studio.md)「まっさらなDBに軸の行は入らない」）ので、4.より前に
  2.を済ませる。

## backendを先に出した窓では、frontendが新しい材料を知らない

- 対象: 材料（`material_catalog`）・一次属性・レジストリを増やす変更。
- ルール: backendをデプロイしてからfrontendをデプロイするまでの間、**新しい材料を使う軸の
  編集画面は別物として開く**——frontend側のカタログにその材料が無いため、材料として引けず
  「組み合わせる軸」の側へ倒れる。窓の間は軸スタジオでその軸を触らない。両方のデプロイが
  終わったことを確認してから編集する。
- なぜ黙って起きるか: 画面はエラーを出さない（引けない材料は「無い」として扱われる）ため、
  開いた人には壊れて見えず、保存すると**軸の中身が変わって書き戻る**。

## 本番へ効かせたい軸定義の変更は、本番の管理画面で行う

- 対象: `axis_admin`のAPI（各環境の軸スタジオGUI、または直接API呼び出し）経由で
  `axis_definitions`等のDB行データを変更する全ての作業。
- ルール: **DBは環境ごとに独立していて、その環境の管理画面がそのDBをメンテナンスする**。
  開発DBへの変更は開発環境にしか効かないため、開発DBだけ変えてタスクを完了扱いにしない
  ——本番へ効かせるなら本番の軸スタジオで行う。環境間で内容を転送する仕組みは持たない
  （上記の決定文書参照）。**リポジトリは軸の写しを持たない**ため、再ダンプの手順は無い。
- 背景: 開発DBのみ反映してタスクを完了扱いにした結果、本番だけ古い軸定義のまま取り残される
  反映漏れが繰り返し発生した実績（T294・T353・T360・T396・T440系列[T455で発覚・修正]・
  T458[過去`[x]`タスクの監査で発覚・修正]、計6回）。
