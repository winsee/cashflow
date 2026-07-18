# 现金流助手 — 单镜像交付（前端静态资源内嵌，离线可用）
# 构建（仓库根目录）：docker build -f deploy/Dockerfile -t cashflow .
FROM node:22-slim AS webbuild
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install --no-fund --no-audit
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv
COPY server/pyproject.toml ./
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic jsonschema qrcode python-multipart
COPY server/app ./app
COPY server/data ./data
COPY --from=webbuild /web/dist ./webdist
ENV CASHFLOW_DB=/data/cashflow.db \
    CASHFLOW_WEB_DIST=/srv/webdist \
    CASHFLOW_MANUAL_DIR=/srv/manual_pages
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
