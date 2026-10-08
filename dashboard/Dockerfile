# SPA estática servida pelo próprio servidor de API (FastAPI/StaticFiles)
# ou por qualquer web server; o build emite apenas HTML/JS/CSS em dist/.
FROM node:20-alpine AS builder

# URL da API que o BROWSER alcança (não o nome de serviço do compose).
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
# SPA: qualquer path cai no index.html para o router client-side resolver.
COPY <<'EOF' /etc/nginx/conf.d/default.conf
server {
  listen 3000;
  root /usr/share/nginx/html;
  index index.html;
  location / {
    try_files $uri $uri/ /index.html;
  }
}
EOF
EXPOSE 3000
