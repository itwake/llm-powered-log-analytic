FROM mirror.gcr.io/library/node:24-alpine

WORKDIR /app
RUN corepack enable
COPY package.json pnpm-workspace.yaml ./
COPY apps/web ./apps/web
RUN pnpm install --frozen-lockfile=false
EXPOSE 3000
CMD ["pnpm", "--filter", "@logan/web", "dev", "--hostname", "0.0.0.0"]
