from flask import Flask, request, jsonify, send_file, abort, Response
from flask_cors import CORS
import os
import uuid
import subprocess
import shutil
import logging
import yt_dlp
import time
import random
import threading
import re
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Configuration
TEMP_DIR = os.environ.get('TEMP_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp'))
DOWNLOAD_EXPIRY = int(os.environ.get('DOWNLOAD_EXPIRY', 3600))  # 1 hour
MAX_CONCURRENT_DOWNLOADS = int(os.environ.get('MAX_CONCURRENT_DOWNLOADS', 3))
COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')

# Create temp directory if it doesn't exist
os.makedirs(TEMP_DIR, exist_ok=True)
download_semaphore = threading.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# User agents untuk rotasi
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
]

# Daftar proxy (ganti dengan proxy valid)
PROXIES = [
    'http://188.68.52.244:80',
    'http://43.153.101.244:13001',
    'http://170.106.136.235:13001',
    'http://213.32.31.88:80'
]

MAX_PROXY_ATTEMPTS = 3
PROXY_STATUS = defaultdict(lambda: {'success': 0, 'fail': 0, 'last_fail': 0})
PROXY_TIMEOUT = 600  # 10 menit

class StreamWithCleanup:
    """Custom stream class that cleans up files after streaming"""
    def __init__(self, file_path):
        self.file_path = file_path
        self.file = open(file_path, 'rb')
    
    def __iter__(self):
        return self
    
    def __next__(self):
        chunk = self.file.read(8192)
        if not chunk:
            self.file.close()
            self.cleanup()
            raise StopIteration
        return chunk
    
    def cleanup(self):
        try:
            if os.path.exists(self.file_path):
                os.remove(self.file_path)
                dir_path = os.path.dirname(self.file_path)
                if os.path.exists(dir_path) and not os.listdir(dir_path):
                    os.rmdir(dir_path)
        except Exception as e:
            logger.error(f"Cleanup error: {str(e)}")

def is_ffmpeg_installed():
    return shutil.which('ffmpeg') is not None

FFMPEG_AVAILABLE = is_ffmpeg_installed()
logger.info(f"FFmpeg available: {FFMPEG_AVAILABLE}")

def cleanup_expired_downloads():
    current_time = time.time()
    for download_id in os.listdir(TEMP_DIR):
        download_path = os.path.join(TEMP_DIR, download_id)
        if os.path.isdir(download_path):
            if current_time - os.path.getmtime(download_path) > DOWNLOAD_EXPIRY:
                try:
                    shutil.rmtree(download_path)
                    logger.info(f"Cleaned up expired download: {download_id}")
                except Exception as e:
                    logger.error(f"Error cleaning up {download_id}: {str(e)}")

cleanup_expired_downloads()

def convert_to_txt(subtitle_file, output_file):
    """Convert subtitle file (vtt/srt) to plain text (.txt)"""
    try:
        with open(subtitle_file, 'r', encoding='utf-8') as f:
            content = f.read()
        lines = content.split('\n')
        cleaned_lines = []
        for line in lines:
            if line.strip() and not re.match(r'^\d+$', line) and not '-->' in line and not line.startswith('WEBVTT'):
                cleaned_lines.append(line.strip())
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(cleaned_lines))
        return True
    except Exception as e:
        logger.error(f"Error converting subtitle to txt: {str(e)}")
        return False

def extract_with_cookies(url, user_cookies=None, proxy=None):
    """Helper function to try user cookies first, then fallback to cookies.txt with proxy"""
    ydl_opts_base = {
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'writesubtitles': True,
        'listsubtitles': True,
        'ignoreerrors': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'extractor_retries': 3,
        'socket_timeout': 10,
        'user_agent': random.choice(USER_AGENTS),
    }
    if proxy:
        ydl_opts_base['proxy'] = proxy

    # Step 1: Try with user cookies if provided
    if user_cookies:
        ydl_opts = ydl_opts_base.copy()
        ydl_opts['http_headers'] = {'Cookie': user_cookies}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            logger.info(f"Success with user cookies (proxy: {proxy or 'none'})")
            return info
        except Exception as e:
            logger.warning(f"User cookies failed (proxy: {proxy or 'none'}): {str(e)}")

    # Step 2: Fallback to cookies.txt if it exists
    if os.path.exists(COOKIE_FILE):
        ydl_opts = ydl_opts_base.copy()
        ydl_opts['cookiefile'] = COOKIE_FILE
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            logger.info(f"Success with cookies.txt (proxy: {proxy or 'none'})")
            return info
        except Exception as e:
            logger.warning(f"cookies.txt failed (proxy: {proxy or 'none'}): {str(e)}")

    # Step 3: Try without cookies as last resort
    ydl_opts = ydl_opts_base.copy()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    logger.info(f"Success without cookies (proxy: {proxy or 'none'})")
    return info

@app.route('/api/extract', methods=['POST'])
def extract_info():
    data = request.json
    url = data.get('url')
    user_cookies = data.get('cookies', '')
    
    if not url:
        return jsonify({'status': 'error', 'message': 'URL is required'}), 400
    
    try:
        now = time.time()
        proxies_sorted = sorted(
            PROXIES,
            key=lambda p: (-PROXY_STATUS[p]['success'] / max(PROXY_STATUS[p]['fail'] + 1, 1), 
                          PROXY_STATUS[p]['last_fail'] if PROXY_STATUS[p]['last_fail'] + PROXY_TIMEOUT > now else 0)
        )

        info = None
        last_error = None
        
        for i, proxy in enumerate(proxies_sorted[:MAX_PROXY_ATTEMPTS]):
            logger.info(f"Trying proxy {i+1}/{MAX_PROXY_ATTEMPTS}: {proxy}")
            try:
                info = extract_with_cookies(url, user_cookies, proxy)
                if info:
                    PROXY_STATUS[proxy]['success'] += 1
                    logger.info(f"Success with proxy: {proxy}")
                    break
            except Exception as e:
                PROXY_STATUS[proxy]['fail'] += 1
                PROXY_STATUS[proxy]['last_fail'] = now
                last_error = str(e)
                logger.warning(f"Proxy {proxy} failed: {last_error}")
                continue
        
        if not info:
            return jsonify({'status': 'error', 'message': f"Failed to extract info after trying {MAX_PROXY_ATTEMPTS} proxies: {last_error or 'Unknown error'}"}), 400
        
        has_subtitles = bool(info.get('subtitles'))
        subtitle_languages = list(info.get('subtitles', {}).keys()) if has_subtitles else []
        
        response_data = {
            'status': 'success',
            'data': {
                'title': info.get('title', 'Unknown Title'),
                'duration': info.get('duration'),
                'thumbnail': info.get('thumbnail'),
                'formats': info.get('formats', []),
                'ffmpeg_available': FFMPEG_AVAILABLE,
                'has_subtitles': has_subtitles,
                'subtitle_languages': subtitle_languages
            }
        }
        
        return jsonify(response_data)
    except Exception as e:
        logger.error(f"Error extracting info: {str(e)}")
        return jsonify({'status': 'error', 'message': f'Error: {str(e)}'}), 500

@app.route('/api/download', methods=['POST'])
def download_media():
    data = request.json
    url = data.get('url')
    format_id = data.get('format_id')
    download_type = data.get('download_type', 'video')
    custom_name = data.get('custom_name', '')
    options = data.get('options', {})
    user_cookies = data.get('cookies', '')
    
    subtitle_option = options.get('subtitle_option', 0)
    subtitle_lang = options.get('subtitle_lang')
    
    if not url:
        return jsonify({'status': 'error', 'message': 'URL is required'}), 400
    
    if (subtitle_option in [1, 2]) and not FFMPEG_AVAILABLE:
        return jsonify({'status': 'error', 'message': 'FFmpeg is required for subtitle options'}), 400
    
    try:
        with download_semaphore:
            download_id = str(uuid.uuid4())
            download_dir = os.path.join(TEMP_DIR, download_id)
            os.makedirs(download_dir, exist_ok=True)
            
            ydl_opts_base = {
                'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),
                'restrictfilenames': True,
                'nocheckcertificate': True,
                'geo_bypass': True,
                'extractor_retries': 3,
                'socket_timeout': 10,
                'user_agent': random.choice(USER_AGENTS),
                'merge_output_format': 'mp4',
            }
            
            subtitle_file = None
            warning = None

            now = time.time()
            proxies_sorted = sorted(
                PROXIES,
                key=lambda p: (-PROXY_STATUS[p]['success'] / max(PROXY_STATUS[p]['fail'] + 1, 1), 
                              PROXY_STATUS[p]['last_fail'] if PROXY_STATUS[p]['last_fail'] + PROXY_TIMEOUT > now else 0)
            )

            info = None
            last_error = None
            
            for i, proxy in enumerate(proxies_sorted[:MAX_PROXY_ATTEMPTS]):
                logger.info(f"Trying proxy {i+1}/{MAX_PROXY_ATTEMPTS} for download: {proxy}")
                ydl_opts = ydl_opts_base.copy()
                ydl_opts['proxy'] = proxy
                
                try:
                    if download_type == 'audio' and FFMPEG_AVAILABLE:
                        ydl_opts['format'] = 'bestaudio/best'
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }]
                        file_extension = 'mp3'
                    else:
                        ydl_opts['format'] = f"{format_id}+bestaudio/best" if format_id else 'bestvideo+bestaudio/best'
                        file_extension = 'mp4'

                    # Apply cookies logic
                    if user_cookies:
                        ydl_opts['http_headers'] = {'Cookie': user_cookies}
                    elif os.path.exists(COOKIE_FILE):
                        ydl_opts['cookiefile'] = COOKIE_FILE

                    if subtitle_option == 1 and subtitle_lang:
                        temp_ydl_opts = {'skip_download': True, 'proxy': proxy}
                        if user_cookies:
                            temp_ydl_opts['http_headers'] = {'Cookie': user_cookies}
                        elif os.path.exists(COOKIE_FILE):
                            temp_ydl_opts['cookiefile'] = COOKIE_FILE
                        with yt_dlp.YoutubeDL(temp_ydl_opts) as ydl:
                            info = ydl.extract_info(url, download=False)
                            audio_langs = set(fmt.get('language') for fmt in info.get('formats', []) if fmt.get('language') and fmt.get('acodec') != 'none')
                            if subtitle_lang in audio_langs:
                                ydl_opts['format'] = f"bestvideo+bestaudio[language={subtitle_lang}]"
                                if format_id:
                                    ydl_opts['format'] = f"{format_id}+bestaudio[language={subtitle_lang}]"
                                ydl_opts['postprocessors'] = [{
                                    'key': 'FFmpegVideoConvertor',
                                    'preferedformat': 'mp4'
                                }]
                            else:
                                warning = f"Tidak ada audio dalam bahasa {subtitle_lang}"
                                ydl_opts['format'] = f"{format_id}+bestaudio/best" if format_id else 'bestvideo+bestaudio/best'
                                ydl_opts['postprocessors'] = [{
                                    'key': 'FFmpegVideoConvertor',
                                    'preferedformat': 'mp4'
                                }]
                    
                    elif subtitle_option == 2 and subtitle_lang:
                        ydl_opts['writesubtitles'] = True
                        ydl_opts['subtitleslangs'] = [subtitle_lang]
                        ydl_opts['subtitlesformat'] = 'vtt'
                        ydl_opts['format'] = f"{format_id}+bestaudio/best" if format_id else 'bestvideo+bestaudio/best'
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegVideoConvertor',
                            'preferedformat': 'mp4'
                        }]
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        if info:
                            PROXY_STATUS[proxy]['success'] += 1
                            logger.info(f"Download success with proxy: {proxy}")
                            break
                except Exception as e:
                    PROXY_STATUS[proxy]['fail'] += 1
                    PROXY_STATUS[proxy]['last_fail'] = now
                    last_error = str(e)
                    logger.warning(f"Proxy {proxy} failed for download: {last_error}")
                    continue
            
            if not info:
                return jsonify({'status': 'error', 'message': f"Download failed after trying {MAX_PROXY_ATTEMPTS} proxies: {last_error or 'Unknown error'}"}), 500
            
            file_extension = info.get('ext', file_extension)
            downloaded_files = [f for f in os.listdir(download_dir) if os.path.isfile(os.path.join(download_dir, f))]
            
            if not downloaded_files:
                return jsonify({'status': 'error', 'message': 'No files were downloaded'}), 500
            
            media_file = next((f for f in downloaded_files if f.endswith(f'.{file_extension}')), downloaded_files[0])
            
            if subtitle_option == 2 and subtitle_lang:
                subtitle_vtt = next((f for f in downloaded_files if f.endswith(f'.{subtitle_lang}.vtt')), None)
                if subtitle_vtt:
                    subtitle_txt = f"{os.path.splitext(media_file)[0]}.txt"
                    if convert_to_txt(os.path.join(download_dir, subtitle_vtt), os.path.join(download_dir, subtitle_txt)):
                        subtitle_file = subtitle_txt
                        os.remove(os.path.join(download_dir, subtitle_vtt))
                    else:
                        warning = "Failed to convert subtitle to text file"
                else:
                    warning = f"Tidak ada subtitle dalam bahasa {subtitle_lang}"
            
            if custom_name:
                new_media_file = f"{custom_name}.{file_extension}"
                os.rename(os.path.join(download_dir, media_file), os.path.join(download_dir, new_media_file))
                media_file = new_media_file
                if subtitle_file:
                    new_subtitle_file = f"{custom_name}.txt"
                    os.rename(os.path.join(download_dir, subtitle_file), os.path.join(download_dir, new_subtitle_file))
                    subtitle_file = new_subtitle_file
            
            response = {
                'status': 'success',
                'download_id': download_id,
                'filename': media_file,
                'subtitle_filename': subtitle_file if subtitle_option == 2 else None,
                'warning': warning
            }
            
            return jsonify(response)
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        return jsonify({'status': 'error', 'message': f'Download failed: {str(e)}'}), 500

@app.route('/api/stream', methods=['POST'])
def stream_media():
    data = request.json
    url = data.get('url')
    format_id = data.get('format_id')
    download_type = data.get('download_type', 'video')
    user_cookies = data.get('cookies', '')
    
    if not url:
        return jsonify({'status': 'error', 'message': 'URL is required'}), 400
    
    try:
        with download_semaphore:
            ydl_opts_base = {
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': False,
                'outtmpl': '-',
                'nocheckcertificate': True,
                'geo_bypass': True,
                'extractor_retries': 3,
                'socket_timeout': 10,
                'user_agent': random.choice(USER_AGENTS),
            }

            now = time.time()
            proxies_sorted = sorted(
                PROXIES,
                key=lambda p: (-PROXY_STATUS[p]['success'] / max(PROXY_STATUS[p]['fail'] + 1, 1), 
                              PROXY_STATUS[p]['last_fail'] if PROXY_STATUS[p]['last_fail'] + PROXY_TIMEOUT > now else 0)
            )

            def generate():
                info = None
                last_error = None
                
                for i, proxy in enumerate(proxies_sorted[:MAX_PROXY_ATTEMPTS]):
                    ydl_opts = ydl_opts_base.copy()
                    ydl_opts['proxy'] = proxy
                    logger.info(f"Trying proxy {i+1}/{MAX_PROXY_ATTEMPTS} for stream: {proxy}")
                    
                    try:
                        if download_type == 'audio' and FFMPEG_AVAILABLE:
                            ydl_opts['format'] = 'bestaudio/best'
                            ydl_opts['postprocessors'] = [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }]
                            content_type = 'audio/mpeg'
                            extension = 'mp3'
                        else:
                            ydl_opts['format'] = f"{format_id}+bestaudio/best" if format_id else 'bestvideo+bestaudio/best'
                            content_type = 'video/mp4'
                            extension = 'mp4'
                        
                        # Apply cookies logic
                        if user_cookies:
                            ydl_opts['http_headers'] = {'Cookie': user_cookies}
                        elif os.path.exists(COOKIE_FILE):
                            ydl_opts['cookiefile'] = COOKIE_FILE
                        
                        temp_ydl_opts = {'quiet': True, 'skip_download': True, 'proxy': proxy}
                        if user_cookies:
                            temp_ydl_opts['http_headers'] = {'Cookie': user_cookies}
                        elif os.path.exists(COOKIE_FILE):
                            temp_ydl_opts['cookiefile'] = COOKIE_FILE
                        with yt_dlp.YoutubeDL(temp_ydl_opts) as ydl:
                            info = ydl.extract_info(url, download=False)
                            title = info.get('title', 'download').replace('/', '_')
                            filename = f"{title}.{extension}"
                        
                        process = subprocess.Popen(
                            ['yt-dlp', '-f', ydl_opts['format'], '-o', '-', '--proxy', proxy, url],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE
                        )
                        
                        for chunk in iter(lambda: process.stdout.read(8192), b''):
                            yield chunk
                        
                        process.stdout.close()
                        process.wait()
                        PROXY_STATUS[proxy]['success'] += 1
                        logger.info(f"Stream success with proxy: {proxy}")
                        break
                    except Exception as e:
                        PROXY_STATUS[proxy]['fail'] += 1
                        PROXY_STATUS[proxy]['last_fail'] = now
                        last_error = str(e)
                        logger.warning(f"Proxy {proxy} failed for stream: {last_error}")
                        continue
                
                if not info:
                    raise Exception(f"Stream failed after trying {MAX_PROXY_ATTEMPTS} proxies: {last_error or 'Unknown error'}")
            
            return Response(generate(), mimetype='application/octet-stream')
    except Exception as e:
        logger.error(f"Stream error: {str(e)}")
        return jsonify({'status': 'error', 'message': f'Stream failed: {str(e)}'}), 500

@app.route('/api/batch', methods=['POST'])
def batch_process():
    data = request.json
    urls = data.get('urls', [])
    user_cookies = data.get('cookies', '')
    
    if not urls:
        return jsonify({'status': 'error', 'message': 'No URLs provided'}), 400
    
    results = []
    count = 0
    
    now = time.time()
    proxies_sorted = sorted(
        PROXIES,
        key=lambda p: (-PROXY_STATUS[p]['success'] / max(PROXY_STATUS[p]['fail'] + 1, 1), 
                      PROXY_STATUS[p]['last_fail'] if PROXY_STATUS[p]['last_fail'] + PROXY_TIMEOUT > now else 0)
    )
    
    for url in urls:
        info = None
        last_error = None
        
        for i, proxy in enumerate(proxies_sorted[:MAX_PROXY_ATTEMPTS]):
            try:
                info = extract_with_cookies(url, user_cookies, proxy)
                if info:
                    PROXY_STATUS[proxy]['success'] += 1
                    count += 1
                    results.append({
                        'status': 'ready',
                        'url': url,
                        'title': info.get('title', 'Unknown Title'),
                        'type': 'video' if info.get('formats', []) else 'unknown'
                    })
                    break
            except Exception as e:
                PROXY_STATUS[proxy]['fail'] += 1
                PROXY_STATUS[proxy]['last_fail'] = now
                last_error = str(e)
                continue
        
        if not info:
            results.append({
                'status': 'error',
                'url': url,
                'error': last_error or 'Failed to extract info'
            })
    
    return jsonify({
        'status': 'success',
        'count': count,
        'results': results
    })

@app.route('/api/file/<download_id>/<filename>', methods=['GET'])
def serve_file(download_id, filename):
    file_path = os.path.join(TEMP_DIR, download_id, filename)
    
    if not os.path.exists(file_path):
        abort(404, description="File not found")
    
    try:
        return Response(
            StreamWithCleanup(file_path),
            mimetype='application/octet-stream',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )
    except Exception as e:
        logger.error(f"Error serving file: {str(e)}")
        abort(500, description="Error serving file")

@app.route('/api/cleanup', methods=['POST'])
def manual_cleanup():
    try:
        cleanup_expired_downloads()
        return jsonify({'status': 'success', 'message': 'Cleanup completed'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'ok',
        'ffmpeg_available': FFMPEG_AVAILABLE,
        'temp_dir_size': sum(os.path.getsize(os.path.join(TEMP_DIR, f)) for f in os.listdir(TEMP_DIR) if os.path.isfile(os.path.join(TEMP_DIR, f)))
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, threaded=True)
