#!/usr/bin/env bash
# Oracle Cloud（本番PostGIS DBホスト）のリソース状況・費用を確認する運用スクリプト。
#
# 発端: 2026-08-20、先週（2026-08-15）に大量のインスタンス／ブートボリュームが誤生成される
# 事故があったことが判明。影響範囲を調査した結果、以下が確認できた（2026-08-20時点）:
#   - 2026-08-15に40個のブートボリュームが生成されていた（コスト請求履歴で確認、
#     Compute自体の課金は0円＝Always Free枠内のVM.Standard.A1.Flexだった）
#   - 現在はいずれも削除済みで、正規のリソース（インスタンス1台・ブートボリューム1個・
#     データ用ブロックボリューム1個）のみが残っている
#   - 事故による金銭的影響は約41円（2026-08-01〜20の合計、Block Storageの日割り課金のみ）
#     と軽微だった
# このスクリプトは、同種の問題（誤操作・スクリプトのバグ・自動化ツールの暴走等による
# リソースの大量生成）を早期に発見するための定型確認手段として作成した。
#
# 実行方法（リポジトリルートから）: bash scripts/check-oracle-cloud.sh
# 前提: OCI CLIが設定済み（~/.oci/config に有効な認証情報があること）。
#
# 「正常時のベースライン」はRideCompass本番DB構成（VM.Standard.A1.Flexインスタンス1台・
# ブートボリューム1個・データ用ブロックボリューム1個、予約済みパブリックIPは0
# ※インスタンス自体のエフェメラルなパブリックIPとは別物）。これを超える件数が
# 出た場合は異常（誤操作・スクリプトバグ等による大量生成の可能性）として警告する。

set -euo pipefail

export PYTHONIOENCODING=utf-8
TENANCY=$(grep '^tenancy=' ~/.oci/config | cut -d= -f2)
EXPECTED_COUNT=1

# oci CLIの出力はstderrへ警告（APIキーの安全性に関する定型メッセージ）を出すため、
# JSONを汚さないよう常に2>/dev/nullで捨てる（エラー自体はコマンドの終了コードで検知する）。
# public-ip list --scope REGION は0件のとき実機確認でstdoutが完全に空になる既知の挙動
# （exit 0・エラー無しだがJSON自体が出ない）があったため、空入力は0件として扱う。
json_count() {
  node -e "let d='';process.stdin.on('data',c=>d+=c);process.stdin.on('end',()=>console.log(d.trim() ? JSON.parse(d).data.length : 0))"
}

echo "=== Oracle Cloudリソース状況確認 $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo

echo "--- 実行中インスタンス ---"
INSTANCES_JSON=$(oci compute instance list --compartment-id "$TENANCY" --all \
  --query "data[?\"lifecycle-state\"=='RUNNING']" 2>/dev/null)
INSTANCE_COUNT=$(echo "$INSTANCES_JSON" | node -e "let d='';process.stdin.on('data',c=>d+=c);process.stdin.on('end',()=>console.log(JSON.parse(d).length))")
echo "$INSTANCES_JSON" | node -e "
let d='';process.stdin.on('data',c=>d+=c);
process.stdin.on('end',()=>{
  JSON.parse(d).forEach(i => console.log(' -', i['display-name'], i['shape'], i['time-created']));
});"
echo "件数: $INSTANCE_COUNT"
echo

echo "--- ブートボリューム ---"
BOOTVOLS_JSON=$(oci bv boot-volume list --compartment-id "$TENANCY" --all 2>/dev/null)
BOOTVOL_COUNT=$(echo "$BOOTVOLS_JSON" | json_count)
echo "$BOOTVOLS_JSON" | node -e "
let d='';process.stdin.on('data',c=>d+=c);
process.stdin.on('end',()=>{
  JSON.parse(d).data.forEach(i => console.log(' -', i['display-name'], i['size-in-gbs']+'GB', i['lifecycle-state']));
});"
echo "件数: $BOOTVOL_COUNT"
echo

echo "--- ブロックボリューム（データ用） ---"
VOLS_JSON=$(oci bv volume list --compartment-id "$TENANCY" --all 2>/dev/null)
VOL_COUNT=$(echo "$VOLS_JSON" | json_count)
echo "$VOLS_JSON" | node -e "
let d='';process.stdin.on('data',c=>d+=c);
process.stdin.on('end',()=>{
  JSON.parse(d).data.forEach(i => console.log(' -', i['display-name'], i['size-in-gbs']+'GB', i['lifecycle-state']));
});"
echo "件数: $VOL_COUNT"
echo

echo "--- 予約済みパブリックIP（インスタンス自体のエフェメラルIPとは別） ---"
PUBIPS_JSON=$(oci network public-ip list --compartment-id "$TENANCY" --scope REGION --all 2>/dev/null)
PUBIP_COUNT=$(echo "$PUBIPS_JSON" | json_count)
echo "件数: $PUBIP_COUNT"
echo

echo "--- 今月の費用（サービス別、円） ---"
MONTH_START=$(date -u +%Y-%m-01T00:00:00Z)
MONTH_END=$(date -u +%Y-%m-%dT00:00:00Z)
oci usage-api usage-summary request-summarized-usages \
  --tenant-id "$TENANCY" --granularity DAILY \
  --time-usage-started "$MONTH_START" --time-usage-ended "$MONTH_END" \
  --query-type COST --group-by '["service"]' 2>/dev/null | node -e "
let d='';process.stdin.on('data',c=>d+=c);
process.stdin.on('end',()=>{
  const items = JSON.parse(d).data.items;
  const byService = {};
  let total = 0;
  for (const i of items) {
    byService[i.service] = (byService[i.service]||0) + (i['computed-amount']||0);
    total += i['computed-amount']||0;
  }
  Object.entries(byService).sort((a,b)=>b[1]-a[1]).forEach(([s,c])=>console.log(' -', s+':', c.toFixed(2)));
  console.log('合計:', total.toFixed(2), '円（今月分、日割り集計）');
});"
echo

echo "=== 判定 ==="
ANOMALY=0
if [ "$INSTANCE_COUNT" -gt "$EXPECTED_COUNT" ]; then
  echo "[警告] 実行中インスタンスが想定（${EXPECTED_COUNT}台）を超えています: ${INSTANCE_COUNT}台"
  ANOMALY=1
fi
if [ "$BOOTVOL_COUNT" -gt "$EXPECTED_COUNT" ]; then
  echo "[警告] ブートボリュームが想定（${EXPECTED_COUNT}個）を超えています: ${BOOTVOL_COUNT}個"
  ANOMALY=1
fi
if [ "$VOL_COUNT" -gt "$EXPECTED_COUNT" ]; then
  echo "[警告] ブロックボリュームが想定（${EXPECTED_COUNT}個）を超えています: ${VOL_COUNT}個"
  ANOMALY=1
fi
if [ "$PUBIP_COUNT" -gt 0 ]; then
  echo "[警告] 予約済みパブリックIPが存在します（想定は0個）: ${PUBIP_COUNT}個"
  ANOMALY=1
fi
if [ "$ANOMALY" -eq 0 ]; then
  echo "異常なし（インスタンス・ボリュームとも想定どおり）"
fi
