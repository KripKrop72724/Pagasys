# Use official lightweight Python image
FROM python:3.12-slim AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update \
 && apt-get install -y build-essential libpq-dev \
    libcairo2 libpango-1.0-0 libgdk-pixbuf2.0-0 libffi-dev \
 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app
RUN apt-get update \
 && apt-get install -y curl dnsutils \
    libcairo2 libpango-1.0-0 libgdk-pixbuf2.0-0 libffi-dev \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy project
COPY . .
RUN python manage.py collectstatic --noinput --verbosity 0 && chmod +x entrypoint.sh

# Expose default application port
EXPOSE 8000

# Run entrypoint and default command
ENTRYPOINT ["./entrypoint.sh"]
CMD gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${GUNICORN_WORKERS:-3} --timeout ${GUNICORN_TIMEOUT:-60}
