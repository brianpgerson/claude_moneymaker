FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (better caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY moneymaker/ moneymaker/

# Create data directory for SQLite
RUN mkdir -p /app/data

# Expose status page port
EXPOSE 8080

# Run the bot
CMD ["moneymaker", "run"]
