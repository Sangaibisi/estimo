# Build context is apps/web: docker build -f apps/web/Dockerfile apps/web
# ADR-0006: containers are the only supported runtime.
#
# The browser-visible API origin is NOT baked at build time — set ESTIMO_API_URL on
# the container and the root layout injects it per request (see app/layout.tsx).

FROM node:24-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build


FROM node:24-alpine
LABEL org.opencontainers.image.source="https://github.com/Sangaibisi/estimo" \
      org.opencontainers.image.licenses="Apache-2.0"
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
# `output: "standalone"` emits a self-contained server with pruned node_modules.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
USER node
CMD ["node", "server.js"]
