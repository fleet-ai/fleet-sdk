# MCP Server - Browser control in Docker with optional VNC
FROM python:3.11-slim

# Install dependencies for Chromium and VNC
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Chromium dependencies
    wget fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libatspi2.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 \
    libnspr4 libnss3 libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 \
    libxrandr2 xdg-utils \
    # VNC and display for headful mode
    xvfb x11vnc fluxbox \
    # noVNC for web-based viewing
    novnc websockify \
    # Utilities
    procps net-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps (includes fleet-python for utils like fleet.utils.playwright)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install chromium

# Copy MCP server files (standalone scripts that import from installed fleet-python)
COPY mcp_server/ ./mcp_server/

# Copy start script
COPY start.sh .
RUN chmod +x start.sh

# Environment
ENV PORT=8765 \
    SCREEN_WIDTH=1366 \
    SCREEN_HEIGHT=768 \
    HEADLESS=true \
    VNC_PORT=5900 \
    NOVNC_PORT=6080 \
    DISPLAY=:99

# Expose ports: MCP server, VNC, noVNC
EXPOSE 8765 5900 6080

# Start script handles display setup
CMD ["./start.sh"]
