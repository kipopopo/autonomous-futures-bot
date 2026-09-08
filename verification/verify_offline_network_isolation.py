"""Empirical test verifying offline network isolation across 50 target tests."""

import socket
import sys
import pytest

socket_attempts = []
orig_connect = socket.socket.connect
orig_connect_ex = socket.socket.connect_ex
orig_create_connection = socket.create_connection
orig_getaddrinfo = socket.getaddrinfo

def blocked_connect(self, address):
    socket_attempts.append(("connect", address))
    raise RuntimeError(f"BLOCKED_NETWORK_SOCKET_CONNECT: {address}")

def blocked_connect_ex(self, address):
    socket_attempts.append(("connect_ex", address))
    return 111  # ECONNREFUSED

def blocked_create_connection(address, *args, **kwargs):
    socket_attempts.append(("create_connection", address))
    raise RuntimeError(f"BLOCKED_NETWORK_CREATE_CONNECTION: {address}")

def blocked_getaddrinfo(host, port, *args, **kwargs):
    socket_attempts.append(("getaddrinfo", (host, port)))
    raise RuntimeError(f"BLOCKED_NETWORK_GETADDRINFO: {host}:{port}")

# Oracle self-check
socket.socket.connect = blocked_connect
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("8.8.8.8", 53))
except RuntimeError as e:
    assert "BLOCKED_NETWORK_SOCKET_CONNECT" in str(e)
    assert len(socket_attempts) == 1
    socket_attempts.clear()
    print("ORACLE_SELF_TEST_PASSED")

# Hook network primitives
socket.socket.connect = blocked_connect
socket.socket.connect_ex = blocked_connect_ex
socket.create_connection = blocked_create_connection
socket.getaddrinfo = blocked_getaddrinfo

exit_code = pytest.main([
    "-o", "testpaths=tests",
    "tests/unit/test_google_ai_studio_cycle_integration.py",
    "tests/integration/test_run_autonomous_cycle_cli.py",
    "-v",
    "--tb=short"
])

print(f"\n==========================================")
print(f"TOTAL_SOCKET_ATTEMPTS: {len(socket_attempts)}")
for kind, target in socket_attempts:
    print(f"ATTEMPT: {kind} -> {target}")
print(f"PYTEST_EXIT_CODE: {exit_code}")
print(f"==========================================")

if len(socket_attempts) != 0 or exit_code != 0:
    sys.exit(1)
sys.exit(0)
