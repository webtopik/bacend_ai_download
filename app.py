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
import platform
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
DOWNLOAD_EXPIRY = int(os.environ.get('DOWNLOAD_EXPIRY', 3600))  # Files expire after 1 hour
MAX_CONCURRENT_DOWNLOADS = int(os.environ.get('MAX_CONCURRENT_DOWNLOADS', 3))  # Limit concurrent downloads

# Create temp directory if it doesn't exist
os.makedirs(TEMP_DIR, exist_ok=True)

# Semaphore for limiting concurrent downloads
download_semaphore = threading.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# User agents untuk rotasi
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
]

# Daftar proxy
PROXIES = [
    'http://38.248.239.69:80',
    'http://52.201.245.219:20202',
    'http://99.79.64.51:20201',
    'http://56.155.29.90:20201',
    'http://13.214.35.84:20201',
    'http://54.73.154.213:20201',
    'http://13.250.172.255:20202',
    'http://161.35.70.249:8080',
    'http://15.157.64.188:20201',
    'http://51.17.85.72:20201',
    'http://13.214.188.109:20202',
    'http://51.44.176.151:20202',
    'http://3.128.90.134:20201',
    'http://13.251.1.82:20202',
    'http://54.173.153.36:20202',
    'http://18.207.97.58:20201',
    'http://13.214.122.121:20202',
    'http://18.138.124.192:20202',
    'http://15.157.63.239:20202',
    'http://18.182.43.188:20201',
    'http://98.81.33.66:20002',
    'http://18.230.71.1:20202',
    'http://43.159.152.105:13001',
    'http://185.175.110.232:3128',
    'http://34.143.143.61:7777',
    'http://133.18.234.13:80',
    'http://15.235.53.20:28003',
    'http://91.107.189.187:80',
    'http://179.61.174.4:80',
    'http://38.38.250.120:8080',
    'http://188.68.52.244:80',
    'http://43.153.36.22:3334',
    'http://43.159.139.163:13001',
    'http://4.145.89.88:8080',
    'http://46.47.197.210:3128',
    'http://170.106.197.21:13001',
    'http://43.159.134.4:13001',
    'http://43.130.44.212:13001',
    'http://43.159.130.175:13001',
    'http://43.130.59.122:13001',
    'http://43.135.174.65:13001',
    'http://170.106.195.109:13001',
    'http://49.51.204.163:13001',
    'http://49.51.198.19:13001',
    'http://43.153.8.65:13001',
    'http://170.106.196.80:13001',
    'http://144.139.210.56:80',
    'http://43.135.136.212:13001',
    'http://49.51.180.75:13001',
    'http://43.153.113.33:13001',
    'http://49.51.250.156:13001',
    'http://43.153.103.91:13001',
    'http://49.51.229.252:13001',
    'http://14.39.239.241:50763',
    'http://170.106.84.182:13001',
    'http://43.153.48.116:13001',
    'http://43.135.132.101:13001',
    'http://49.51.197.183:13001',
    'http://43.130.28.33:13001',
    'http://43.153.99.158:13001',
    'http://54.38.181.125:80',
    'http://43.130.62.137:13001',
    'http://43.135.161.247:13001',
    'http://43.135.162.60:13001',
    'http://43.153.45.169:13001',
    'http://81.169.213.169:8888',
    'http://43.130.14.101:13001',
    'http://43.159.139.120:13001',
    'http://170.106.192.56:13001',
    'http://5.189.190.187:8090',
    'http://43.129.201.43:443',
    'http://15.237.115.153:20201',
    'http://18.140.233.10:20202',
    'http://170.106.193.157:13001',
    'http://43.153.76.64:13001',
    'http://170.106.104.64:13001',
    'http://134.209.29.120:80',
    'http://45.140.143.77:18080',
    'http://43.159.133.199:13001',
    'http://43.153.27.172:13001',
    'http://43.153.69.25:13001',
    'http://43.130.56.110:13001',
    'http://43.153.23.242:13001',
    'http://18.133.187.220:1080',
    'http://170.106.173.107:13001',
    'http://107.150.105.176:8001',
    'http://188.34.160.26:6699',
    'http://43.130.58.145:13001',
    'http://49.51.73.95:13001',
    'http://43.153.94.8:13001',
    'http://43.153.106.210:13001',
    'http://43.130.15.214:13001',
    'http://170.106.170.3:13001',
    'http://84.39.112.144:3128',
    'http://43.159.152.237:13001',
    'http://173.234.15.62:8888',
    'http://43.153.4.121:13001',
    'http://162.223.90.130:80',
    'http://129.226.155.235:8080',
    'http://38.152.72.198:2335',
    'http://211.234.125.5:443',
    'http://38.159.229.97:999',
    'http://36.93.120.95:8080',
    'http://134.35.206.89:8080',
    'http://65.38.96.106:3128',
    'http://103.209.38.133:81',
    'http://43.159.132.166:13001',
    'http://18.223.25.15:80',
    'http://15.235.10.31:28003',
    'http://13.36.113.81:3128',
    'http://43.153.34.75:13001',
    'http://43.130.16.61:13001',
    'http://43.159.134.243:13001',
    'http://170.106.174.148:13001',
    'http://43.153.112.28:13001',
    'http://170.106.186.103:13001',
    'http://43.135.145.242:13001',
    'http://170.106.76.17:13001',
    'http://43.135.142.6:13001',
    'http://170.106.198.41:13001',
    'http://43.135.129.244:13001',
    'http://43.153.95.171:13001',
    'http://43.135.176.22:13001',
    'http://43.153.113.65:13001',
    'http://43.153.44.254:13001',
    'http://146.56.142.114:1080',
    'http://170.106.114.25:13001',
    'http://170.106.83.59:13001',
    'http://43.130.29.151:13001',
    'http://43.153.105.141:13001',
    'http://3.12.144.146:3128',
    'http://43.130.33.54:13001',
    'http://43.153.121.25:13001',
    'http://43.135.158.192:13001',
    'http://42.117.214.127:10001',
    'http://3.141.217.225:80',
    'http://49.51.206.38:13001',
    'http://43.135.150.45:13001',
    'http://43.153.22.138:13001',
    'http://43.153.69.199:13001',
    'http://64.176.35.119:7891',
    'http://43.153.78.139:13001',
    'http://170.106.84.125:13001',
    'http://43.153.92.57:13001',
    'http://43.153.98.70:13001',
    'http://43.153.112.164:13001',
    'http://43.153.8.210:13001',
    'http://43.159.130.134:13001',
    'http://103.82.38.220:8888',
    'http://154.65.39.7:80',
    'http://38.152.72.231:2335',
    'http://5.135.103.166:80',
    'http://47.254.88.250:13001',
    'http://43.155.196.88:9090',
    'http://43.130.12.5:13001',
    'http://43.159.142.191:13001',
    'http://43.135.137.249:13001',
    'http://43.130.15.85:13001',
    'http://170.106.153.160:13001',
    'http://170.106.151.90:13001',
    'http://49.51.49.70:13001',
    'http://43.159.145.108:13001',
    'http://43.135.158.86:13001',
    'http://49.51.200.62:13001',
    'http://47.243.113.74:5555',
    'http://43.135.186.62:13001',
    'http://43.153.79.36:13001',
    'http://43.135.180.61:13001',
    'http://43.153.48.134:13001',
    'http://43.135.139.25:13001',
    'http://43.153.76.230:13001',
    'http://49.51.191.97:13001',
    'http://170.106.172.59:13001',
    'http://43.153.88.167:13001',
    'http://43.153.62.242:13001',
    'http://43.153.92.210:13001',
    'http://43.153.102.53:13001',
    'http://43.153.103.58:13001',
    'http://49.51.73.96:13001',
    'http://64.176.41.252:30001',
    'http://195.35.2.231:80',
    'http://43.153.7.172:13001',
    'http://173.44.141.43:8080',
    'http://103.213.218.96:12254',
    'http://198.74.51.79:8888',
    'http://43.159.137.110:13001',
    'http://170.106.181.112:13001',
    'http://212.69.114.161:8080',
    'http://125.26.165.245:8080',
    'http://200.98.201.13:25000',
    'http://51.15.241.34:3128',
    'http://13.37.59.99:3128',
    'http://43.135.129.37:13001',
    'http://43.130.33.67:13001',
    'http://170.106.171.100:13001',
    'http://43.153.12.131:13001',
    'http://43.135.147.227:13001',
    'http://43.153.74.136:13001',
    'http://43.153.99.175:13001',
    'http://43.135.164.4:13001',
    'http://43.153.25.42:13001',
    'http://43.153.100.6:13001',
    'http://43.153.98.107:13001',
    'http://43.153.103.42:13001',
    'http://43.153.11.118:13001',
    'http://43.153.2.82:13001',
    'http://34.81.160.132:80',
    'http://15.236.186.15:45554',
    'http://15.152.54.90:20202',
    'http://13.38.176.104:3128',
    'http://193.42.118.143:8080',
    'http://43.135.136.234:13001',
    'http://43.153.45.4:13001',
    'http://43.153.1.164:13001',
    'http://3.126.147.182:80',
    'http://35.72.118.126:80',
    'http://35.79.120.242:3128',
    'http://3.127.62.252:80',
    'http://18.185.169.150:3128',
    'http://46.51.249.135:3128',
    'http://54.233.119.172:3128',
    'http://3.78.92.159:3128',
    'http://170.106.158.82:13001',
    'http://63.33.226.53:80',
    'http://18.144.153.151:3128',
    'http://18.142.74.251:80',
    'http://18.229.62.3:3128',
    'http://15.223.105.115:80',
    'http://54.150.100.19:3128',
    'http://16.171.219.242:3128',
    'http://15.164.128.155:3128',
    'http://51.20.29.120:3128',
    'http://51.17.39.65:1080',
    'http://13.246.215.127:3128',
    'http://13.48.163.100:3128',
    'http://13.54.47.197:80',
    'http://13.125.98.173:3128',
    'http://13.55.184.26:1080',
    'http://13.51.231.191:3128',
    'http://54.248.242.183:3128',
    'http://51.17.26.160:3128',
    'http://13.114.112.160:80',
    'http://51.16.199.206:3128',
    'http://13.246.209.48:1080',
    'http://13.246.184.110:3128',
    'http://52.65.193.254:3128',
    'http://3.97.176.251:3128',
    'http://43.153.21.33:13001',
    'http://43.153.75.63:13001',
    'http://203.115.101.61:82',
    'http://88.99.211.112:8120',
    'http://43.153.88.171:13001',
    'http://3.87.47.184:3128',
    'http://43.153.16.91:13001',
    'http://104.225.220.233:80',
    'http://43.159.148.136:13001',
    'http://116.102.44.18:10026',
    'http://110.136.112.15:8080',
    'http://223.25.110.120:1095',
    'http://50.237.153.241:8081',
    'http://172.188.122.92:80',
    'http://165.232.129.150:80',
    'http://43.135.139.98:13001',
    'http://43.153.18.46:13001',
    'http://170.106.65.42:13001',
    'http://43.135.177.135:13001',
    'http://43.135.154.71:13001',
    'http://54.177.187.64:80',
    'http://54.66.27.238:3128',
    'http://15.152.14.140:3128',
    'http://52.74.70.59:3128',
    'http://13.49.84.200:3128',
    'http://13.208.144.135:3128',
    'http://54.179.47.255:80',
    'http://13.247.19.136:80',
    'http://15.165.52.176:3128',
    'http://54.255.94.130:3128',
    'http://51.17.38.108:3128',
    'http://54.179.117.3:80',
    'http://54.94.204.20:80',
    'http://51.17.27.173:3128',
    'http://18.229.214.109:3128',
    'http://15.168.57.13:3128',
    'http://52.220.248.1:3128',
    'http://3.39.135.31:3128',
    'http://13.56.47.50:3128',
    'http://13.247.14.165:80',
    'http://3.130.65.162:3128',
    'http://43.135.164.2:13001',
    'http://203.115.101.55:82',
    'http://170.106.168.100:13001',
    'http://189.22.234.39:80',
    'http://159.69.57.20:8880',
    'http://43.153.91.13:13001',
    'http://43.153.4.199:13001',
    'http://194.158.203.14:80',
    'http://43.135.147.140:13001',
    'http://176.9.239.181:80',
    'http://93.127.215.97:80'
]

MAX_PROXY_ATTEMPTS = 3
PROXY_STATUS = defaultdict(lambda: {'success': 0, 'fail': 0, 'last_fail': 0})  # Cache status proxy
PROXY_TIMEOUT = 600  # 10 menit, proxy yang gagal diabaikan sementara

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
        
        # Remove VTT/SRT formatting
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

@app.route('/api/extract', methods=['POST'])
def extract_info():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'status': 'error', 'message': 'URL is required'}), 400
    
    try:
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
            'cookiefile': os.path.join(os.path.dirname(__file__), 'cookies.txt')
        }

        # Urutkan proxy berdasarkan rasio sukses dan waktu kegagalan terakhir
        now = time()
        proxies_sorted = sorted(
            PROXIES,
            key=lambda p: (-PROXY_STATUS[p]['success'] / max(PROXY_STATUS[p]['fail'] + 1, 1), 
                          PROXY_STATUS[p]['last_fail'] if PROXY_STATUS[p]['last_fail'] + PROXY_TIMEOUT > now else 0)
        )

        info = None
        last_error = None
        
        for i, proxy in enumerate(proxies_sorted[:MAX_PROXY_ATTEMPTS]):
            ydl_opts = ydl_opts_base.copy()
            ydl_opts['proxy'] = proxy
            logger.info(f"Trying proxy {i+1}/{MAX_PROXY_ATTEMPTS}: {proxy}")
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
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
                'cookiefile': os.path.join(os.path.dirname(__file__), 'cookies.txt')
            }
            
            subtitle_file = None
            warning = None

            # Urutkan proxy berdasarkan rasio sukses dan waktu kegagalan terakhir
            now = time()
            proxies_sorted = sorted(
                PROXIES,
                key=lambda p: (-PROXY_STATUS[p]['success'] / max(PROXY_STATUS[p]['fail'] + 1, 1), 
                              PROXY_STATUS[p]['last_fail'] if PROXY_STATUS[p]['last_fail'] + PROXY_TIMEOUT > now else 0)
            )

            info = None
            last_error = None
            
            for i, proxy in enumerate(proxies_sorted[:MAX_PROXY_ATTEMPTS]):
                ydl_opts = ydl_opts_base.copy()
                ydl_opts['proxy'] = proxy
                logger.info(f"Trying proxy {i+1}/{MAX_PROXY_ATTEMPTS} for download: {proxy}")
                
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

                    # Handle subtitle options
                    if subtitle_option == 1 and subtitle_lang:  # Audio Translation
                        with yt_dlp.YoutubeDL({'skip_download': True, 'cookiefile': ydl_opts['cookiefile'], 'proxy': proxy}) as ydl:
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
    
    if not url:
        return jsonify({'status': 'error', 'message': 'URL is required'}), 400
    
    try:
        with download_semaphore:
            ydl_opts_base = {
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': False,
                'outtmpl': '-',  # Stream to stdout
                'nocheckcertificate': True,
                'geo_bypass': True,
                'extractor_retries': 3,
                'socket_timeout': 10,
                'user_agent': random.choice(USER_AGENTS),
                'cookiefile': os.path.join(os.path.dirname(__file__), 'cookies.txt')
            }

            # Urutkan proxy
            now = time()
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
                        
                        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'cookiefile': ydl_opts['cookiefile'], 'proxy': proxy}) as ydl:
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
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
