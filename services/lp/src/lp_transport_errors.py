"""Recognize temporary resolver failures without relaxing official-host or TLS checks."""
import socket
from urllib.error import URLError


def transient_dns(error):
    if isinstance(error, URLError):
        return transient_dns(error.reason)
    return isinstance(error, socket.gaierror) and error.errno in {
        socket.EAI_AGAIN, socket.EAI_NONAME, 8,  # macOS EAI_NONAME
    }
