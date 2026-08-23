# ---------- 阶段 1：构建前端 ----------
FROM node:18-alpine AS frontend
WORKDIR /app/web
COPY web/package*.json ./
RUN npm install
COPY web/ ./
RUN npm run build

# ---------- 阶段 2：Python 后端 ----------
FROM python:3.13-slim
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn

COPY src/ ./src/
COPY scripts/ ./scripts/

# 前端构建产物（来自阶段 1）
COPY --from=frontend /app/web/dist ./web/dist

EXPOSE 8000

# 首次启动会增量入库（仅嵌入新增/变更文档）；chroma 数据通过卷持久化
# 注意：ingest.py 内使用 `from src...` 绝对导入，需将 /app 加入 PYTHONPATH
# 端口可由 PORT 环境变量覆盖（默认 8000），便于与本地调试端口错开避免冲突
CMD ["sh", "-c", "PYTHONPATH=/app python scripts/ingest.py && uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
