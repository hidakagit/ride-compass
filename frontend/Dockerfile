# build段とrun段で別のNodeが混ざらないよう、版はここ1箇所で持つ。
ARG NODE_VERSION=22

FROM node:${NODE_VERSION}-slim AS build
WORKDIR /app
# .npmrcのengine-strictにより、このイメージのNodeがpackage.jsonのenginesを満たさなければ
# npm ciが失敗する（FROMとenginesの食い違いをビルド時に止める）。
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:${NODE_VERSION}-slim AS run
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
