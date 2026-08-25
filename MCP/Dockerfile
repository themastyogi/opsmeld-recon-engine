# Production Dockerfile for Opsmeld Reconciliation Engine & Data Trust
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy repository source files
COPY . .

EXPOSE 8000

# Start Opsmeld server
CMD ["python", "server.py"]
