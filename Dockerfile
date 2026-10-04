FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -m plfss
COPY plfss_service ./plfss_service
COPY public ./public
COPY reports/coverage.json ./reports/coverage.json
USER 10001:10001
ENV PLFSS_DATA=/data PORT=8080 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import json,urllib.request;assert json.load(urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3))['ready']"
CMD ["python","-m","plfss_service.web"]
