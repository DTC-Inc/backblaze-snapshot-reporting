FROM python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create a non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt ./requirements.txt
RUN apt-get update && apt-get install -y curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories needed by the app and set permissions
RUN mkdir -p /data/snapshots /data/cache && \
    mkdir -p /home/appuser/.local/lib/python3.9/site-packages && \
    mkdir -p /home/appuser/.cache/pip && \
    chown -R appuser:appuser /home/appuser && \
    chmod -R 755 /home/appuser

# Set Python path for user installed packages
ENV PYTHONPATH=/app:${PYTHONPATH}
ENV PATH=/home/appuser/.local/bin:${PATH}

# Create entry point script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh && \
    chown -R appuser:appuser /app /docker-entrypoint.sh

# Note: We don't chown /data here since it will be mounted as a volume
# and the entrypoint script will handle permissions

# Set up volume for persistent data
VOLUME ["/data"]

# Switch to non-root user
USER appuser

# Set environment variables
ENV DATABASE_URI=sqlite:////data/backblaze_snapshots.db \
    SNAPSHOT_CACHE_DIR=/data/cache \
    PYTHONPATH=/app

# Expose port
EXPOSE 5000

# Run the application
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--pythonpath", "/app", "app.app:app"]
