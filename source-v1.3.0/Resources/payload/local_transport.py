"""Bypass proxies only for literal loopback endpoints; retain remote proxy policy."""
import ipaddress
import urllib.request
from urllib.parse import urlsplit

LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def is_loopback(url):
    host = (urlsplit(url).hostname or '').lower().rstrip('.')
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

def urlopen(request, **kwargs):
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    if is_loopback(url):
        return LOCAL_OPENER.open(request, **kwargs)
    return urllib.request.urlopen(request, **kwargs)

def websocket_options(url):
    return {'proxy': None} if is_loopback(url) else {}
