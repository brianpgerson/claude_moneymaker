FROM python:3.11-slim

WORKDIR /app

# Copy project files and install
COPY pyproject.toml README.md ./
COPY moneymaker/ moneymaker/
RUN pip install --no-cache-dir .

# Create data directory for SQLite
RUN mkdir -p /app/data

# Expose status page port
EXPOSE 8080

# Run the bot
CMD ["moneymaker", "run"]
