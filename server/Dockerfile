# fd-lex-api 服务端镜像 — FastAPI + uvicorn。
# 发布通道：GitHub Actions -> TCR（.github/workflows/image.yml，配方 docs/IMAGE-RELEASE.md）。
# 硬性要求（IMAGE-RELEASE 六步清单）：上游源为默认（美国 runner 绕道国内镜像会把
# 构建拖成小时级），国内镜像源一律 ARG 且默认空。
FROM python:3.12-slim

ARG PIP_INDEX_URL=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY fd_lex_api ./fd_lex_api
# 迁移工件随镜像走：生产 PG 迁移以 initContainer 执行 alembic upgrade head
# （schema 唯一事实源=迁移链；METERING_AUTO_CREATE_TABLES 生产置 false）。
COPY alembic.ini ./
COPY alembic ./alembic

# [mongo] extra：audit 流直读/推送摄取两路都可用（REGISTRY_MONGO_* 或 /internal/metering/events）。
RUN if [ -n "$PIP_INDEX_URL" ]; then pip install --no-cache-dir -i "$PIP_INDEX_URL" '.[mongo]'; else pip install --no-cache-dir '.[mongo]'; fi \
 && useradd -m -u 1000 appuser

USER appuser

EXPOSE 8000

CMD ["uvicorn", "fd_lex_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
