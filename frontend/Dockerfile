# Build the React app, then serve the static files with nginx.
# nginx.conf is mounted from deploy/ by docker-compose.yml.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# openssl makes the demo's self-signed HTTPS certificate on first start (docker/self-signed-cert.sh).
RUN apk add --no-cache openssl
COPY --chmod=755 docker/self-signed-cert.sh /docker-entrypoint.d/05-self-signed-cert.sh
COPY --from=build /app/dist /usr/share/nginx/html
