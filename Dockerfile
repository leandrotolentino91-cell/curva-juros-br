# Usado pelo Hugging Face Spaces (SDK "Docker"). O Streamlit Community Cloud ignora este arquivo.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 CURVA_CACHE_DIR=/tmp/cache_curvas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 7860
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.enableXsrfProtection=false"]
