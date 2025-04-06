import time

_cache = {}

def get_cached_media_info(url):
    if url in _cache and time.time() - _cache[url]['timestamp'] < 3600:
        return _cache[url]['data']
    return None

def cache_media_info(url, data):
    _cache[url] = {
        'data': data,
        'timestamp': time.time()
    }