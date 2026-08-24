FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Set environment variables for OpsMeld server
ENV PYTHONPATH=/app/MCP
ENV PORT=8000

EXPOSE 8000

# Server launcher command
CMD ["python", "MCP/server.py"]
