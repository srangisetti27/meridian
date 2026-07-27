# Meridian Pipeline Intelligence — container image
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so this layer caches across code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code, data, and theme config
COPY config.py data_loader.py analytics.py question_router.py \
     llm_layer.py observability.py app.py ./
COPY data/ data/
COPY .streamlit/ .streamlit/
COPY tests/ tests/

# The engine must reconcile before the image is considered good:
# a build with data that fails validation should not ship.
RUN python -m pytest tests/ -q

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; \
      urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.headless=true"]
