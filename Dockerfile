FROM python:3.12-slim

WORKDIR /app

# Create user with UID 568 (TrueNAS apps user)
RUN groupadd -g 568 afterwatch && \
    useradd -u 568 -g 568 -m -s /bin/bash afterwatch

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY static/ ./static/

# Create data directory and set ownership
RUN mkdir -p /app/data && \
    chown -R 568:568 /app

# Switch to non-root user
USER 568

# Expose port
EXPOSE 8199

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8199"]
