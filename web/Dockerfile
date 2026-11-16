FROM node:22-slim AS base
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
# 中国大陆加速：--build-arg NPM_REGISTRY=https://registry.npmmirror.com
ARG NPM_REGISTRY=https://registry.npmjs.org

RUN corepack enable && corepack prepare pnpm@10 --activate
RUN pnpm config set registry ${NPM_REGISTRY}

WORKDIR /app

# ── 依赖层（利用缓存）──
COPY package.json ./
RUN pnpm install --no-frozen-lockfile

# ── 构建 ──
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# ⚠️ rewrites 在 build 时求值并写死，运行时改环境变量无效，
#    所以 CONTROL_URL 必须在此刻传入。
ARG CONTROL_URL=http://ag-control:8000
ENV CONTROL_URL=${CONTROL_URL}
RUN pnpm build

# ── 运行 ──
FROM node:22-slim AS runner
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

RUN adduser --disabled-password --uid 1001 --gecos "" nextjs 2>/dev/null || \
    adduser --disabled-password --uid 1001 nextjs

COPY --from=base /app/.next/standalone ./
COPY --from=base /app/.next/static ./.next/static
COPY --from=base /app/public ./public

USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0

CMD ["node", "server.js"]
