# 现金流助手 — 单镜像交付（前端静态资源内嵌，离线可用）
# 构建（仓库根目录）：docker build -t cashflow .
# 不带本地 OCR 的精简镜像：docker build --build-arg WITH_OCR=0 -t cashflow:slim .
FROM node:22-slim AS webbuild
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install --no-fund --no-audit
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv
ARG WITH_OCR=1
COPY server/pyproject.toml ./
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic jsonschema qrcode python-multipart cryptography
# 本地 OCR（M3）：装依赖并预下载 PaddleOCR 模型进镜像（离线可用）
RUN if [ "$WITH_OCR" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/* && \
      pip install --no-cache-dir paddleocr "paddlepaddle>=3.0,<3.1" rapidfuzz ; \
    fi
COPY server/app ./app
RUN if [ "$WITH_OCR" = "1" ]; then python -m app.recognize.local_ocr --warmup ; fi
COPY server/data ./data
COPY server/manual_pages ./manual_pages
COPY --from=webbuild /web/dist ./webdist
ENV CASHFLOW_DB=/data/cashflow.db \
    CASHFLOW_WEB_DIST=/srv/webdist \
    CASHFLOW_MANUAL_DIR=/srv/manual_pages
VOLUME ["/data"]
# 只跑 HTTP 8000；云端 TLS 由反向代理终止（CASHFLOW_HTTPS=off）
EXPOSE 8000
CMD ["python", "-m", "app.serve"]
