FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN addgroup --system hpoint && adduser --system --ingroup hpoint hpoint
COPY requirements.txt requirements-media.txt requirements-exports.txt ./
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.2" \
    && python -m pip install --no-cache-dir -r requirements.txt
COPY . ./
RUN chown -R hpoint:hpoint /app
USER hpoint

EXPOSE 8080
CMD ["python", "run.py"]
