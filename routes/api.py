from flask import Blueprint, request, jsonify, Response, send_file, abort
import os
import uuid
import subprocess
import yt_dlp
import time
import random
import logging
import threading
import re
import shutil
from services.cleanup import StreamWithCleanup, cleanup_expired_downloads, convert_to_txt
from services.cache import get_cached_media_info, cache_media_info

api_bp = Blueprint('api', __name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
TEMP_DIR = os.environ.get('TEMP_DIR', './temp')
DOWNLOAD_EXPIRY = int(os.environ.get('DOWNLOAD_EXPIRY', 3600))
MAX_CONCURRENT_DOWNLOADS = int(os.environ.get('MAX_CONCURRENT_DOWNLOADS', 3))

# Semaphore for limiting concurrent downloads
download_semaphore = threading.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# User agent rotation
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
]

def is_ffmpeg_installed():
    return shutil.which('ffmpeg') is not None

FFMPEG_AVAILABLE = is_ffmpeg_installed()
logger.info(f"FFmpeg available: {FFMPEG_AVAILABLE}")

@api_bp.route('/extract', methods=['POST'])
def extract_info():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({'status': 'error', 'message': 'URL is required'}), 400
    try:
        cached_info = get_cached_media_info(url)
        if cached_info:
            return jsonify(cached_info)

        ydl_opts = {
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
            'socket_timeout': 30,
            'user_agent': random.choice(USER_AGENTS)
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({'status': 'error', 'message': 'Could not extract info'}), 400
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
            cache_media_info(url, response_data)
            return jsonify(response_data)
    except Exception as e:
        logger.error(f"Error extracting info: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@api_bp.route('/download', methods=['POST'])
def download_media():
    data = request.json
    url = data.get('url')
    format_id = data.get('format_id')
    download_type = data.get('download_type', 'video')
    custom_name = data.get('custom_name', '')
    options = data.get('options', {})
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
            
            ydl_opts = {
                'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),
                'restrictfilenames': True,
                'nocheckcertificate': True,
                'geo_bypass': True,
                'extractor_retries': 3,
                'socket_timeout': 30,
                'user_agent': random.choice(USER_AGENTS),
                'merge_output_format': 'mp4'  # Pastikan output digabungkan ke mp4
            }
            
            subtitle_file = None
            warning = None
            
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

            # Handle subtitle options
            if subtitle_option == 1 and subtitle_lang:  # Audio Translation
                with yt_dlp.YoutubeDL({'skip_download': True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    audio_langs = set(fmt.get('language') for fmt in info.get('formats', []) if fmt.get('language') and fmt.get('acodec') != 'none')
                    if subtitle_lang in audio_langs:
                        # Prioritaskan audio dengan bahasa yang dipilih
                        ydl_opts['format'] = f"bestvideo+bestaudio[language={subtitle_lang}]"
                        if format_id:
                            ydl_opts['format'] = f"{format_id}+bestaudio[language={subtitle_lang}]"
                        # Tambahkan postprocessor untuk memastikan penggabungan
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
            
            elif subtitle_option == 2 and subtitle_lang:  # Text File
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
                
                if not info:
                    return jsonify({'status': 'error', 'message': 'Download failed'}), 500
                
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

@api_bp.route('/stream', methods=['POST'])
def stream_media():
    data = request.json
    url = data.get('url')
    format_id = data.get('format_id')
    download_type = data.get('download_type', 'video')
    
    if not url:
        return jsonify({'status': 'error', 'message': 'URL is required'}), 400
    
    try:
        with download_semaphore:
            def generate():
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'ignoreerrors': False,
                    'outtmpl': '-',  # Stream to stdout
                    'nocheckcertificate': True,
                    'geo_bypass': True,
                    'extractor_retries': 3,
                    'socket_timeout': 30,
                    'user_agent': random.choice(USER_AGENTS)
                }
                
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
                
                with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
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
            
            return Response(generate(), mimetype='application/octet-stream')
            
    except Exception as e:
        logger.error(f"Stream error: {str(e)}")
        return jsonify({'status': 'error', 'message': f'Stream failed: {str(e)}'}), 500

@api_bp.route('/file/<download_id>/<filename>', methods=['GET'])
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

@api_bp.route('/cleanup', methods=['POST'])
def manual_cleanup():
    try:
        cleanup_expired_downloads()
        return jsonify({'status': 'success', 'message': 'Cleanup completed'})
    except Exception as e:
        logger.error(f"Cleanup error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500