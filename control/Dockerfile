ARG PIP_INDEX_URL=https://pypi.org/simple
FROM python:3.14-slim

ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
# 同时装 dev 依赖，使镜像可直接跑测试（个人项目，不必拆分镜像）
RUN pip install --upgrade pip && \
    python - <<'PY'
import tomllib, subprocess, sys
with open('pyproject.toml','rb') as f:
    proj = tomllib.load(f)
deps = list(proj['project']['dependencies'])
deps += list(proj['project'].get('optional-dependencies', {}).get('dev', []))
subprocess.check_call([sys.executable, '-m', 'pip', 'install', *deps])
PY

COPY app ./app
COPY tests ./tests

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
