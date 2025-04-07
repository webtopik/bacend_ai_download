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

# Enhanced User Agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
]

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

def validate_cookies(cookies):
    """Validate if cookies are in Netscape format"""
    try:
        with open(cookies, 'r') as f:
            first_line = f.readline().strip()
            return first_line.startswith('# Netscape HTTP Cookie File') or \
                   any(line.count('\t') >= 6 for line in f)
    except:
        return False

def extract_with_cookies(url, user_cookies=None):
    """Enhanced cookie handling with validation"""
    ydl_opts_base = {
        'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',  # Cap at 1080p
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'writesubtitles': True,
        'listsubtitles': True,
        'ignoreerrors': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'extractor_retries': 3,
        'socket_timeout': 30,
        'user_agent': random.choice(USER_AGENTS),
        'http_chunk_size': 10485760,  # 10MB chunks
        'buffersize': 65536,
    }

    # Priority 1: Visitor's Cookies
    if user_cookies:
        ydl_opts = ydl_opts_base.copy()
        ydl_opts['http_headers'] = {'Cookie': user_cookies}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            logger.info("Success with user cookies")
            return info
        except Exception as e:
            logger.warning(f"User cookies failed: {str(e)}")

    # Priority 2: Local cookies.txt with validation
    if os.path.exists(COOKIE_FILE) and os.stat(COOKIE_FILE).st_size > 0:
        if validate_cookies(COOKIE_FILE):
            ydl_opts = ydl_opts_base.copy()
            ydl_opts['cookiefile'] = COOKIE_FILE
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                logger.info("Success with validated cookies.txt")
                return info
            except Exception as e:
                logger.warning(f"Valid cookies.txt failed: {str(e)}")
        else:
            logger.warning("Invalid cookies.txt format - skipping")

    # Priority 3: No Cookies
    ydl_opts = ydl_opts_base.copy()
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        logger.info("Success without cookies")
        return info
    except Exception as e:
        raise Exception(f"All fallbacks failed: {str(e)}")

@app.route('/api/extract', methods=['POST'])
def extract_info():
    data = request.json
    url = data.get('url')
    user_cookies = data.get('cookies', '')
    
    if not url:
        return jsonify({'status': 'error', 'message': 'URL is required'}), 400
    
    try:
        info = extract_with_cookies(url, user_cookies)
        
        if not info:
            return jsonify({'status': 'error', 'message': 'Failed to extract info'}), 400
        
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
                'subtitle_languages': subtitle_languages,
                'filesize_approx': info.get('filesize_approx')
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
                'socket_timeout': 30,
                'user_agent': random.choice(USER_AGENTS),
                'merge_output_format': 'mp4',
                'http_chunk_size': 10485760,  # 10MB chunks
                'buffersize': 65536,
                'throttled_rate': '2M',  # Limit download speed
                'retries': 10,
                'fragment_retries': 10,
                'continuedl': True,
                'noprogress': True,
            }

            # Apply resolution cap if not specified
            if not format_id:
                ydl_opts_base['format'] = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
            
            subtitle_file = None
            warning = None
            info = None
            last_error = None
            
            # Enhanced download attempts with proper error handling
            for attempt in range(3):  # Max 3 attempts
                try:
                    # Priority 1: User cookies
                    if user_cookies and attempt == 0:
                        ydl_opts = ydl_opts_base.copy()
                        ydl_opts['http_headers'] = {'Cookie': user_cookies}
                        logger.info("Attempting download with user cookies")
                    
                    # Priority 2: cookies.txt
                    elif os.path.exists(COOKIE_FILE) and os.stat(COOKIE_FILE).st_size > 0 and validate_cookies(COOKIE_FILE) and attempt <= 1:
                        ydl_opts = ydl_opts_base.copy()
                        ydl_opts['cookiefile'] = COOKIE_FILE
                        logger.info("Attempting download with cookies.txt")
                    
                    # Priority 3: No cookies
                    else:
                        ydl_opts = ydl_opts_base.copy()
                        logger.info("Attempting download without cookies")
                    
                    # Configure download type
                    if download_type == 'audio' and FFMPEG_AVAILABLE:
                        ydl_opts['format'] = 'bestaudio/best'
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }]
                        file_extension = 'mp3'
                    else:
                        if not format_id:
                            ydl_opts['format'] = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
                        else:
                            ydl_opts['format'] = f"{format_id}+bestaudio/best"
                        file_extension = 'mp4'

                    # Handle subtitles
                    if subtitle_option == 1 and subtitle_lang:
                        ydl_opts['format'] = f"bestvideo+bestaudio[language={subtitle_lang}]/best"
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegVideoConvertor',
                            'preferedformat': 'mp4'
                        }]
                    elif subtitle_option == 2 and subtitle_lang:
                        ydl_opts['writesubtitles'] = True
                        ydl_opts['subtitleslangs'] = [subtitle_lang]
                        ydl_opts['subtitlesformat'] = 'vtt'

                    # Execute download
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                    
                    logger.info(f"Download successful on attempt {attempt + 1}")
                    break
                
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"Attempt {attempt + 1} failed: {last_error}")
                    time.sleep(2)  # Brief delay between attempts
                    continue

            if not info:
                return jsonify({'status': 'error', 'message': f"Download failed after all attempts: {last_error or 'Unknown error'}"}), 500
            
            # Process downloaded files
            file_extension = info.get('ext', file_extension)
            downloaded_files = [f for f in os.listdir(download_dir) if os.path.isfile(os.path.join(download_dir, f))]
            
            if not downloaded_files:
                return jsonify({'status': 'error', 'message': 'No files were downloaded'}), 500
            
            media_file = next((f for f in downloaded_files if f.endswith(f'.{file_extension}')), downloaded_files[0])
            
            # Handle subtitles if requested
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
                    warning = f"No subtitles available in {subtitle_lang}"

            # Apply custom filename if specified
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
                'warning': warning,
                'filesize': os.path.getsize(os.path.join(download_dir, media_file))
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

            def generate():
                info = None
                last_error = None
                
                # Step 1: Try with user cookies
                if user_cookies:
                    ydl_opts = ydl_opts_base.copy()
                    ydl_opts['http_headers'] = {'Cookie': user_cookies}
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
                        
                        temp_ydl_opts = {'quiet': True, 'skip_download': True, 'http_headers': {'Cookie': user_cookies}}
                        with yt_dlp.YoutubeDL(temp_ydl_opts) as ydl:
                            info = ydl.extract_info(url, download=False)
                            title = info.get('title', 'download').replace('/', '_')
                            filename = f"{title}.{extension}"
                        
                        process = subprocess.Popen(
                            ['yt-dlp', '-f', ydl_opts['format'], '-o', '-', url],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE
                        )
                        
                        for chunk in iter(lambda: process.stdout.read(8192), b''):
                            yield chunk
                        
                        process.stdout.close()
                        process.wait()
                        logger.info("Stream success with user cookies")
                        return
                    except Exception as e:
                        last_error = str(e)
                        logger.warning(f"User cookies failed for stream: {last_error}")

                # Step 2: Fallback to cookies.txt
                if os.path.exists(COOKIE_FILE) and os.stat(COOKIE_FILE).st_size > 0:
                    ydl_opts = ydl_opts_base.copy()
                    ydl_opts['cookiefile'] = COOKIE_FILE
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
                        
                        temp_ydl_opts = {'quiet': True, 'skip_download': True, 'cookiefile': COOKIE_FILE}
                        with yt_dlp.YoutubeDL(temp_ydl_opts) as ydl:
                            info = ydl.extract_info(url, download=False)
                            title = info.get('title', 'download').replace('/', '_')
                            filename = f"{title}.{extension}"
                        
                        process = subprocess.Popen(
                            ['yt-dlp', '-f', ydl_opts['format'], '-o', '-', url],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE
                        )
                        
                        for chunk in iter(lambda: process.stdout.read(8192), b''):
                            yield chunk
                        
                        process.stdout.close()
                        process.wait()
                        logger.info("Stream success with backend cookies.txt")
                        return
                    except Exception as e:
                        last_error = str(e)
                        logger.warning(f"Backend cookies.txt failed for stream: {last_error}")

                # Step 3: Try without cookies
                ydl_opts = ydl_opts_base.copy()
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
                    
                    temp_ydl_opts = {'quiet': True, 'skip_download': True}
                    with yt_dlp.YoutubeDL(temp_ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        title = info.get('title', 'download').replace('/', '_')
                        filename = f"{title}.{extension}"
                    
                    process = subprocess.Popen(
                        ['yt-dlp', '-f', ydl_opts['format'], '-o', '-', url],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    
                    for chunk in iter(lambda: process.stdout.read(8192), b''):
                        yield chunk
                    
                    process.stdout.close()
                    process.wait()
                    logger.info("Stream success without cookies")
                    return
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"Stream failed without cookies: {last_error}")
                
                if not info:
                    raise Exception(f"Stream failed after all cookie attempts: {last_error or 'Unknown error'}")
            
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
    
    for url in urls:
        try:
            info = extract_with_cookies(url, user_cookies)
            if info:
                count += 1
                results.append({
                    'status': 'ready',
                    'url': url,
                    'title': info.get('title', 'Unknown Title'),
                    'type': 'video' if info.get('formats', []) else 'unknown'
                })
        except Exception as e:
            results.append({
                'status': 'error',
                'url': url,
                'error': str(e)
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
