#!/bin/bash
# 本番DBの全体をpg_dumpで書き出し、Object Storageの非公開バケットへ1個だけ置く。
# 本番VMのsystemd（ridecompass-admin-data-backup.service）がrootで毎日打つ。登録と戻し方は
# .claude/skills/production-data/SKILL.md「DBのバックアップ」「本番DBを失ったとき」。
#
# 環境変数（/etc/ridecompass/admin-data-backup.env）: OCI_NAMESPACE・BACKUP_BUCKET
set -euo pipefail

: "${OCI_NAMESPACE:?}" "${BACKUP_BUCKET:?}"

# 書き出しはDBのディスクの、PostgreSQLのdata_directoryの外に置く。OSのディスクと/runには入らない大きさになる。
# 前の回の書き出しは次の回まで残し、バケットへ置けなかった回も手元から送り直せるようにする。
backup_dir=/mnt/pgdata/ridecompass-backup
# 圧縮は可逆なものから、本番で書き出して一番小さく収まったもの（pg_dumpの--compressの書き方）。
compress=zstd
# バケットに置くのは常に1個で、無料の枠（10GB）に収める。超えるなら置かずに落ちる。
# 枠との差は、規則で消えるのを待つ古い置き物と、送りかけのまま残る部分の分。
max_bytes=9500000000

mkdir -p "$backup_dir"
# DB名は、デプロイ済みのbackendと同じ接続先の設定から取る（接続先・利用者・パスワードは出さない——
# ホストのpg_dumpはpostgresユーザーのpeer認証で同じDBへつなぐ）。
db_name=$(docker run --rm --env-file /home/ubuntu/ridecompass-backend.env ridecompass-backend:latest \
  python -c 'from sqlalchemy.engine import make_url; from app.config import settings; print(make_url(settings.database_url).database)')

# 書き出す前に、書き出しが入る空きを確かめる。書き出しは圧縮してもDBより大きくはならない。
db_bytes=$(runuser -u postgres -- psql --dbname="$db_name" --tuples-only --no-align \
  --command='SELECT pg_database_size(current_database())')
free_bytes=$(df --output=avail --block-size=1 "$backup_dir" | tail -n 1)
if (( free_bytes < db_bytes )); then
  echo "DBのディスクの空きがDBの大きさより少ないので書き出しません free=$free_bytes db=$db_bytes" >&2
  exit 1
fi

# pg_dumpはホストのものを使う。サーバーと同じPGDGの版で入っているため、版が必ず揃う
# （pg_dumpは自分より新しいメジャー版のサーバーからは書き出さない）。
next="$backup_dir/next.dump"
runuser -u postgres -- pg_dump --format=custom --compress="$compress" --dbname="$db_name" > "$next"
# 置く前に、戻せる形のアーカイブであることを確かめる。
pg_restore --list "$next" > /dev/null
bytes=$(stat -c %s "$next")
if (( bytes > max_bytes )); then
  echo "書き出しがバケットの枠に収まらないので置きません bytes=$bytes max=$max_bytes" >&2
  exit 1
fi

# 認証はインスタンス・プリンシパル（鍵をVMに置かない）。VMに許すのはこのバケットのオブジェクトの一覧・作成・削除だけ。
# 公開イメージは空の設定（資格なし）で取る。rootのDockerの設定にghcr.ioの失効した資格が残っていると、
# ghcr.ioは公開イメージでも拒否する（denied）。
anon_config="$backup_dir/docker-config"
mkdir -p "$anon_config"
oci() {
  docker --config "$anon_config" run --rm --network=host -v "$backup_dir:/backup:ro" ghcr.io/oracle/oci-cli:latest \
    --auth instance_principal "$@"
}

# 枠に2個は入らないので、前の回のものを消してから置く。確かめの通った書き出しが手元にあるので、
# ここから先で落ちても手元から送り直せる。
oci os object bulk-delete --namespace "$OCI_NAMESPACE" --bucket-name "$BACKUP_BUCKET" --prefix db/ --force > /dev/null
mv "$next" "$backup_dir/latest.dump"
name="db/$(date -u +%Y%m%dT%H%M%SZ).dump"
oci os object put --namespace "$OCI_NAMESPACE" --bucket-name "$BACKUP_BUCKET" \
  --name "$name" --file /backup/latest.dump --force > /dev/null

# 置けた時刻を、backendのコンテナが`data/`として見るディレクトリへ書く。止まっても知らせが来ないため、
# `/health`が経過時間を返し、それを読んで気づく（名前は`app/infrastructure/admin_data_backup.py: MARKER_PATH`と揃える）。
marker=/home/ubuntu/ridecompass-cache-data/admin_data_backup_at
date -u +%Y-%m-%dT%H:%M:%S+00:00 > "$marker.tmp"
mv "$marker.tmp" "$marker"

echo "DBの全体を置きました object=$name bytes=$bytes db=$db_name compress=$compress"
