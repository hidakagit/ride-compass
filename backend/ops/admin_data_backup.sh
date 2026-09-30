#!/bin/bash
# 取り直せない管理データの表をpg_dumpで書き出し、Object Storageの非公開バケットへ置く。
# 本番VMのsystemd（ridecompass-admin-data-backup.service）がrootで毎日打つ。登録と戻し方は
# docs/conventions/deployment-sync.md「管理データのバックアップ」。
#
# 環境変数（/etc/ridecompass/admin-data-backup.env）: OCI_NAMESPACE・BACKUP_BUCKET
set -euo pipefail

: "${OCI_NAMESPACE:?}" "${BACKUP_BUCKET:?}"
work_dir=${RUNTIME_DIRECTORY:?systemdのRuntimeDirectory=の下で動かす}

# 書き出す表とDB名は、デプロイ済みのコードの宣言から取る。
args=$(docker run --rm --env-file /home/ubuntu/ridecompass-backend.env \
  ridecompass-backend:latest python scripts/admin_data_dump_args.py)
mapfile -t dump_args <<< "$args"

# pg_dumpはホストのものを使う。サーバーと同じPGDGの版で入っているため、版が必ず揃う
# （pg_dumpは自分より新しいメジャー版のサーバーからは書き出さない）。
name="admin-data/$(date -u +%Y%m%dT%H%M%SZ).dump"
file="$work_dir/backup.dump"
runuser -u postgres -- pg_dump --format=custom --strict-names "${dump_args[@]}" > "$file"
# 置く前に、戻せる形のアーカイブであることを確かめる。
pg_restore --list "$file" > /dev/null

# 認証はインスタンス・プリンシパル（鍵をVMに置かない）。--forceは上書きの確認（HeadObject）を省くだけで、
# 上書き・読み出し・削除はバケットの権限（OBJECT_CREATEだけ）が許さない。
# 公開イメージは空の設定（資格なし）で取る。rootのDockerの設定にghcr.ioの失効した資格が残っていると、
# ghcr.ioは公開イメージでも拒否する（denied）。
anon_config="$work_dir/docker-config"
mkdir -p "$anon_config"
docker --config "$anon_config" run --rm --network=host -v "$work_dir:/backup:ro" ghcr.io/oracle/oci-cli:latest \
  --auth instance_principal os object put \
  --namespace "$OCI_NAMESPACE" --bucket-name "$BACKUP_BUCKET" \
  --name "$name" --file /backup/backup.dump --force > /dev/null

echo "管理データを置きました object=$name bytes=$(stat -c %s "$file") ${dump_args[*]}"
