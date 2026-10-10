# build段とrun段で別のNodeが混ざらないよう、版はここ1箇所で持つ。
ARG NODE_VERSION=22

FROM node:${NODE_VERSION}-slim AS build
WORKDIR /app
# .npmrcのengine-strictにより、このイメージのNodeがpackage.jsonのenginesを満たさなければ
# npm ciが失敗する（FROMとenginesの食い違いをビルド時に止める）。
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .
# ビルドのときにJSとrewritesへ埋め込む宛先。本番の像はdeploy-frontend.ymlが渡す。渡さないビルド（docker-compose）では
# 空の値を環境から外し、コードの既定の値に落とす（空の文字列は`??`の既定に落ちない）。
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_TILE_BASE_URL
ARG BACKEND_INTERNAL_URL
RUN for name in NEXT_PUBLIC_API_URL NEXT_PUBLIC_TILE_BASE_URL BACKEND_INTERNAL_URL; do \
      [ -n "$(printenv "$name")" ] || unset "$name"; \
    done; \
    npm run build

FROM node:${NODE_VERSION}-slim AS run
WORKDIR /app
ENV NODE_ENV=production
# standaloneのserver.jsは環境変数HOSTNAMEの宛先で待ち受ける。コンテナではHOSTNAMEがコンテナの名前になり、
# 外（Renderの転送）から届かなくなるので、全部の宛先で待ち受けさせる。
ENV HOSTNAME=0.0.0.0
# 像に入れたコミット。/api/versionが返し、デプロイの反映の確かめに使う。渡さないビルドでは空。
ARG GIT_COMMIT
ENV GIT_COMMIT=${GIT_COMMIT}
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
