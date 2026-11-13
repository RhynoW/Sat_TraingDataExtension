# HuggingFace Space (docker SDK) — Streamlit 機動偵測儀表板 2026-09
FROM python:3.11-slim

# lightgbm 需 libgomp1；其餘為常見編譯/字型相依
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 fonts-noto-cjk && \
    rm -rf /var/lib/apt/lists/*

# 非 root 使用者（HF Spaces 慣例 uid 1000）
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_PORT=7860 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

EXPOSE 7860
CMD ["streamlit", "run", "app.py", \
     "--server.port=7860", "--server.address=0.0.0.0", \
     "--server.headless=true"]
