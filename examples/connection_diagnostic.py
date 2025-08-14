#!/usr/bin/env python3
"""
Fleet SDK Connection Diagnostic Tool

This script helps diagnose network connectivity issues when make() hangs.
It tests each step of the connection process individually.
"""

import socket
import time
import httpx
import logging
from fleet.config import REGION_BASE_URL

def test_dns_resolution(hostname):
    """Test DNS resolution for a hostname."""
    print(f"\n🔍 Testing DNS resolution for {hostname}...")
    try:
        start = time.time()
        ip = socket.gethostbyname(hostname)
        duration = time.time() - start
        print(f"✅ DNS: {hostname} -> {ip} ({duration:.3f}s)")
        return ip
    except Exception as e:
        duration = time.time() - start
        print(f"❌ DNS failed after {duration:.3f}s: {e}")
        return None

def test_socket_connection(hostname, port, timeout=10):
    """Test raw socket connection."""
    print(f"\n🔌 Testing socket connection to {hostname}:{port}...")
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((hostname, port))
        duration = time.time() - start
        print(f"✅ Socket: Connected to {hostname}:{port} ({duration:.3f}s)")
        sock.close()
        return True
    except Exception as e:
        duration = time.time() - start
        print(f"❌ Socket failed after {duration:.3f}s: {e}")
        return False

def test_http_connection(url, timeout=30):
    """Test HTTP connection with httpx."""
    print(f"\n🌐 Testing HTTP connection to {url}...")
    try:
        start = time.time()
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url + "/health", timeout=timeout)
        duration = time.time() - start
        print(f"✅ HTTP: {response.status_code} from {url} ({duration:.3f}s)")
        return True
    except Exception as e:
        duration = time.time() - start
        print(f"❌ HTTP failed after {duration:.3f}s: {e}")
        return False

def test_fleet_endpoint(region=None):
    """Test Fleet API endpoint connectivity."""
    if region:
        base_url = REGION_BASE_URL.get(region)
        if not base_url:
            print(f"❌ Unknown region: {region}")
            return False
    else:
        from fleet.config import GLOBAL_BASE_URL
        base_url = GLOBAL_BASE_URL
    
    print(f"\n🚀 Testing Fleet endpoint: {base_url}")
    
    # Parse URL
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    hostname = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    
    # Test each step
    ip = test_dns_resolution(hostname)
    if not ip:
        return False
    
    socket_ok = test_socket_connection(ip, port)
    if not socket_ok:
        return False
    
    http_ok = test_http_connection(base_url)
    return http_ok

def main():
    print("Fleet SDK Connection Diagnostic Tool")
    print("=" * 40)
    
    # Test the region you're using
    region = "us-west-1"  # Change this to match your region
    print(f"Testing region: {region}")
    
    success = test_fleet_endpoint(region)
    
    if success:
        print(f"\n✅ All connectivity tests passed for {region}!")
        print("The issue may be with authentication or request content.")
    else:
        print(f"\n❌ Connectivity issues detected for {region}")
        print("Possible causes:")
        print("  • Firewall blocking connections")
        print("  • VPN or proxy interference")  
        print("  • Network routing issues")
        print("  • Fleet service outage")
    
    # Also test global endpoint
    print("\n" + "="*40)
    print("Testing global endpoint (localhost)...")
    success_global = test_fleet_endpoint(None)
    
    if success_global:
        print("\n✅ Local endpoint works - try using localhost in config")
    else:
        print("\n❌ Local endpoint also fails")

if __name__ == "__main__":
    main()
