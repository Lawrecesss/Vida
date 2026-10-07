# syntax=docker/dockerfile:1

# Build context is frontend/ — this service shares nothing with the SDK but the
# HTTP contract, which is the point of splitting them.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


# Development target: the source arrives as a bind mount from compose.dev.yaml,
# so nothing is copied in. node_modules stays the image's, behind an anonymous
# volume, because a host install (or the absence of one) must not shadow it.
FROM deps AS dev
ENV NEXT_TELEMETRY_DISABLED=1
EXPOSE 3000
CMD ["npm", "run", "dev"]


FROM deps AS builder
WORKDIR /app
COPY . .

# NEXT_PUBLIC_* is inlined into the client bundle at build time, never read at
# runtime. Every fetch in app/ runs in the browser (the pages are "use client"),
# so this has to be a URL the *browser* can reach — the published host port, not
# a Compose service name.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build


FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# `output: "standalone"` in next.config.ts traces what the server actually
# imports into .next/standalone, which is why this stage installs no packages:
# the traced subset ships with the build. Static assets are not traced, hence
# the two extra copies.
COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1

CMD ["node", "server.js"]
