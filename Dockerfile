FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY static/ ./static/

# Create data directory for SQLite and logs
RUN mkdir -p /app/data

# Expose port
EXPOSE 8199

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8199"]
