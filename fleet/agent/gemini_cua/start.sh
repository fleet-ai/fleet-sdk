#!/bin/bash
set -e

# Start virtual display if not headless
if [ "$HEADLESS" != "true" ]; then
    echo "Starting Xvfb virtual display..."
    Xvfb :99 -screen 0 ${SCREEN_WIDTH}x${SCREEN_HEIGHT}x24 &
    sleep 1
    
    echo "Starting fluxbox window manager..."
    fluxbox &
    sleep 1
    
    echo "Starting VNC server on port $VNC_PORT..."
    x11vnc -display :99 -forever -shared -rfbport $VNC_PORT -nopw &
    sleep 1
    
    echo "Starting noVNC on port $NOVNC_PORT..."
    websockify --web=/usr/share/novnc/ $NOVNC_PORT localhost:$VNC_PORT &
    sleep 1
    
    echo ""
    echo "=========================================="
    echo "  Browser visible at: http://localhost:$NOVNC_PORT/vnc.html"
    echo "=========================================="
    echo ""
fi

# Start the MCP server (standalone script, imports from installed fleet-python)
exec python mcp_server/main.py
