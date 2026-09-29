# ---------------------------------------------------------------------------
# CampusConnect Frontend — Multi-Stage Production Build
# Stage 1: Build static bundle with Node.js
# Stage 2: Serve with lightweight, unprivileged Nginx
# ---------------------------------------------------------------------------

# Stage 1: Build
FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
ENV VITE_API_BASE_URL=""
RUN npm run build

# Stage 2: Production Nginx
FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx-frontend.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
