"""Network utility functions shared across services."""
import os
import socket
import time
from .logs import build_logger
from .runtime_state_cache import runtime_state_cache_get, runtime_state_cache_set

log = build_logger("ServiceRunner")


def get_lan_ip():
    """
    Get LAN IP by checking which interface would route to an external host.

    This creates a UDP socket and "connects" to an external IP (no data is sent),
    then checks which local IP was selected for the connection.

    Returns:
        str: The LAN IP address, or None if it cannot be determined
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "0.0.0.0"


def is_port_available(host, port):
    """
    Check if a port is available for binding.

    Args:
        host: The host address to check
        port: The port number to check

    Returns:
        bool: True if the port is available, False otherwise
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def find_available_port(host, start_port, end_port):
    """
    Find an available port in the given range.

    Args:
        host: The host address to bind to
        start_port: Start of port range (inclusive)
        end_port: End of port range (inclusive)

    Returns:
        int: An available port, or 0 if none found (let OS assign)
    """
    for port in range(start_port, end_port + 1):
        if is_port_available(host, port):
            return port
    return 0

def get_cached_port(cfg, key, host):
    """
    Get a port for the service. If it exists in a config, use that. If it doesn't, try to retrieve it
    from a cache in CWD for this service. If it also doesn't, try to get a free port from 4201 to 4299.
    If all fails, returns 0 (which will assign a random free port)
    """
    if cfg.get(key) is not None:
        return cfg[key]

    cached = runtime_state_cache_get(key)
    if cached:
        if is_port_available(host, cached):
            return cached
        # Give it a bit of extra time, our previous instance may still be holding to the port
        for i in range(1, 5):
            log.info("Cached port %s is not available, will wait to see if it gets freed up...", cached)
            time.sleep(1)
            if is_port_available(host, cached):
                log.info("Using cached port %s", cached)
                return cached
        log.info("Cached port %s is not available anymore, will select random port", cached)

    for port in range(4201, 4300):
        if is_port_available(host, port):
            runtime_state_cache_set(key, port)
            return port

    log.warning("No free port found in range 4201-4299, falling back to OS-assigned port")
    return 0


def is_safe_path(basedir, path, follow_symlinks=False):
    """
    Validates that a file path is safe and within the allowed base directory.

    Prevents path traversal attacks by resolving the full path and verifying
    it stays within the base directory.

    Args:
        basedir: The allowed base directory (must be absolute)
        path: The requested file path (relative to basedir)
        follow_symlinks: False means that symlinks outside of the basedir are allowed, use with caution

    Returns:
        The safe absolute path if valid

    Raises:
        ValueError: If the path escapes the base directory
    """
    if follow_symlinks:
        basedir = os.path.realpath(basedir)
        matchpath = os.path.realpath(os.path.join(basedir, path))
    else:
        basedir = os.path.abspath(basedir)
        matchpath = os.path.abspath(os.path.join(basedir, path))

    # Check if the resolved path is within the base directory
    if not matchpath.startswith(basedir + os.sep) and matchpath != basedir:
        raise ValueError(f"Path traversal attempt detected: {path}")

    return matchpath
