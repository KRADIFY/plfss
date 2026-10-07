FROM nos-deniers-demo:20261005-gateway
USER 0
# A fresh public directory in this new image; the source image is preserved.
RUN python -c "import shutil; shutil.rmtree('/app/public')"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY server.py /app/server.py
COPY public /app/public
USER 10001:10001
EXPOSE 8080
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8080"]
