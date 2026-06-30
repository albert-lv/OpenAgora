# Code Colosseum dashboard.
# Multi-stage build: Vite builder -> nginx static host.
FROM node:20-slim AS builder

WORKDIR /app
COPY examples/code-colosseum/dashboard/package.json examples/code-colosseum/dashboard/package-lock.json* ./
RUN npm install

COPY examples/code-colosseum/dashboard ./
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY examples/code-colosseum/dashboard/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
