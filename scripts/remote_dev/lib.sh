# クラウドのセッション（Claude Code on the web）の開発環境を用意する処理。
# setup.sh（環境の初回だけ走り、終了時のファイルシステムが保存される）と
# session_start.sh（毎セッションの開始時に走る）の両方から読む。
#
# 依存（backendのvenv・frontendのnode_modules）は、lockfileのダイジェストごとにリポジトリの
# 外（$RC_CACHE）へ作る。セッションはリポジトリを新しくcloneして始まるため、リポジトリの中に
# 置いたものは保存されたファイルシステムから引き継がれる保証が無い。リポジトリ側へは
# リンク（venv）かハードリンクの写し（node_modules）を置くだけにする。

RC_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RC_CACHE="${RC_CACHE:-/opt/ridecompass-dev}"
RC_PYTHON="${RC_PYTHON:-python3.12}"
RC_TIMES="$(mktemp)"

rc_log() { printf '[remote_dev %s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }

# 所要を秒で測り、段ごとの結果を$RC_TIMESへ1行ずつ書く（背景で並べて走らせても集められる）。
rc_timed() {
  local label="$1"; shift
  local started=$SECONDS
  if "$@"; then
    echo "$label=ok($((SECONDS - started))s)" >> "$RC_TIMES"
  else
    echo "$label=失敗($((SECONDS - started))s)" >> "$RC_TIMES"
    return 1
  fi
}

rc_summary() { sort "$RC_TIMES" | tr '\n' ' '; rm -f "$RC_TIMES"; }

rc_digest() { cat "$@" | sha256sum | cut -c1-16; }

rc_backend_digest() {
  { "$RC_PYTHON" -V; cat "$RC_REPO"/backend/requirements*.txt; } | sha256sum | cut -c1-16
}

rc_frontend_digest() {
  { node -v; cat "$RC_REPO"/frontend/package.json "$RC_REPO"/frontend/package-lock.json "$RC_REPO"/frontend/.npmrc; } \
    | sha256sum | cut -c1-16
}

# backend/.venv をダイジェストごとのvenvへのリンクにする（無ければ作る）。
rc_ensure_backend() {
  local digest venv link="$RC_REPO/backend/.venv"
  digest="$(rc_backend_digest)"
  venv="$RC_CACHE/venv-$digest"
  if [ ! -f "$venv/.complete" ]; then
    rc_log "backendの依存を入れる（$venv）"
    rm -rf "$venv"
    "$RC_PYTHON" -m venv "$venv" || return 1
    "$venv/bin/pip" install -q --disable-pip-version-check \
      -r "$RC_REPO/backend/requirements-batch.txt" -r "$RC_REPO/backend/requirements-dev.txt" || return 1
    touch "$venv/.complete"
  fi
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    rc_log "backend/.venv が実体のディレクトリなので触らない"
  else
    ln -sfn "$venv" "$link"
  fi
  find "$RC_CACHE" -maxdepth 1 -name 'venv-*' ! -name "venv-$digest" -exec rm -rf {} + 2>/dev/null
  return 0
}

# frontend/node_modules をダイジェストごとの導入結果の写しにする（無ければ作る）。
# 写しはハードリンクで作るので数秒で終わる。
rc_ensure_frontend() {
  local digest dir target="$RC_REPO/frontend/node_modules"
  digest="$(rc_frontend_digest)"
  dir="$RC_CACHE/frontend-$digest"
  if [ ! -f "$dir/.complete" ]; then
    rc_log "frontendの依存を入れる（$dir）"
    rm -rf "$dir"
    mkdir -p "$dir" || return 1
    cp "$RC_REPO"/frontend/package.json "$RC_REPO"/frontend/package-lock.json "$RC_REPO"/frontend/.npmrc "$dir"/
    (cd "$dir" && npm_config_update_notifier=false npm ci --no-audit --no-fund --loglevel=error >&2) || return 1
    touch "$dir/.complete"
  fi
  if [ "$(cat "$target/.ridecompass-digest" 2>/dev/null)" != "$digest" ]; then
    rm -rf "$target"
    cp -al "$dir/node_modules" "$target" 2>/dev/null || cp -a "$dir/node_modules" "$target" || return 1
    echo "$digest" > "$target/.ridecompass-digest"
  fi
  find "$RC_CACHE" -maxdepth 1 -name 'frontend-*' ! -name "frontend-$digest" -exec rm -rf {} + 2>/dev/null
  return 0
}

rc_ensure_dockerd() {
  docker info >/dev/null 2>&1 && return 0
  rc_log "dockerdを起動する"
  setsid nohup dockerd >/var/log/ridecompass-dockerd.log 2>&1 < /dev/null &
  local i
  for i in $(seq 1 60); do
    docker info >/dev/null 2>&1 && return 0
    sleep 0.5
  done
  rc_log "dockerdが起動しない（/var/log/ridecompass-dockerd.log）"
  return 1
}

rc_compose() { docker compose -f "$RC_REPO/docker-compose.yml" "$@"; }

# DBとRedisのイメージを手元に揃える。Docker Hubは接続元ごとの取得上限で429を返すことが
# あるため、同じイメージを配るGoogleのミラーへ切り替えて取り、元の名前を付け直す。
rc_pull_images() {
  local image
  for image in $(rc_compose config --images postgres redis); do
    docker image inspect "$image" >/dev/null 2>&1 && continue
    case "$image" in */*) mirror="mirror.gcr.io/$image" ;; *) mirror="mirror.gcr.io/library/$image" ;; esac
    docker pull -q "$image" >/dev/null 2>&1 \
      || { docker pull -q "$mirror" >/dev/null && docker tag "$mirror" "$image"; } \
      || return 1
  done
}

rc_db() { rc_ensure_dockerd && rc_start_services; }

rc_images() { rc_ensure_dockerd && rc_pull_images; }

# postgres・redisを起動し、テストの複製元になる共有DB（conftest.pyのSHARED_TEST_DATABASE）を用意する。
rc_start_services() {
  rc_pull_images || return 1
  rc_compose up -d --wait postgres redis >/dev/null 2>&1 || { rc_compose ps -a >&2; return 1; }
  rc_compose exec -T postgres sh -c \
    'psql -U ridecompass -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '\''ridecompass_test'\''" | grep -q 1 \
     || createdb -U ridecompass ridecompass_test'
}
