import os
import shutil
import time
import logging
import re

logger = logging.getLogger(__name__)
TEMP_DIR = os.environ.get('TEMP_DIR', './temp')
DOWNLOAD_EXPIRY = int(os.environ.get('DOWNLOAD_EXPIRY', 3600))

class StreamWithCleanup:
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

def convert_to_txt(subtitle_file, output_file):
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

def is_ffmpeg_installed():
    return shutil.which('ffmpeg') is not None