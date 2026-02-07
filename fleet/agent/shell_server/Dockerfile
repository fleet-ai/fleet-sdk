# Shell Server - MCP server with bash and file tools for Harbor integration
FROM python:3.11-slim

# Install common shell utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core utilities
    bash coreutils findutils grep sed gawk \
    # Networking
    curl wget net-tools \
    # Build tools (for pip packages that need compilation)
    build-essential \
    # Git for repo operations
    git \
    # Process management
    procps \
    # Archive tools
    tar gzip bzip2 unzip \
    # Text editors
    vim nano \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy MCP server files
COPY tools.py main.py ./

# Create working directory for agent operations
RUN mkdir -p /workspace && chmod 777 /workspace

# Environment
ENV PORT=8765 \
    SHELL_WORKDIR=/workspace

# Expose MCP server port
EXPOSE 8765

# Start the shell server
CMD ["python", "main.py"]
