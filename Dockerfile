FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && mkdir -p /data && chown pwuser:pwuser /data
COPY --chown=pwuser:pwuser app.py core.py crawler.py adtraction.py ./
COPY --chown=pwuser:pwuser templates ./templates
USER pwuser
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8788
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8788/healthz',timeout=3)" || exit 1
CMD ["python", "app.py"]
