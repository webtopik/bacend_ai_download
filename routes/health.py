from flask import Blueprint, jsonify
import os
from services.cleanup import is_ffmpeg_installed

health_bp = Blueprint('health', __name__)

TEMP_DIR = os.environ.get('TEMP_DIR', './temp')
FFMPEG_AVAILABLE = is_ffmpeg_installed()

@health_bp.route('/health', methods=['GET'])
def health_check():
    temp_size = sum(os.path.getsize(os.path.join(TEMP_DIR, f)) for f in os.listdir(TEMP_DIR) if os.path.isfile(os.path.join(TEMP_DIR, f)))
    return jsonify({
        'status': 'ok',
        'ffmpeg_available': FFMPEG_AVAILABLE,
        'temp_dir_size': temp_size
    })