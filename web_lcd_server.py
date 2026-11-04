#!/usr/bin/env python3
"""
Web LCD Server - Synced with physical LCD via shared state files
Reads LCD state from run/lcd_state.json (written by lcd_manager.py)
Writes button presses to run/web_button.json (read by lcd_manager.py)
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.core.config import config_section  # noqa: E402

app = Flask(__name__)

# Only the box's own pages (docs site on :8000, web companion on :8080) may call
# this API from a browser — not any website a learner happens to visit.
WEB_CFG = config_section("web")
ALLOWED_ORIGINS = WEB_CFG.get("lcd_api_origins") or [re.compile(r"^https?://[^/]+:(8000|8080)$")]
CORS(app, origins=ALLOWED_ORIGINS)
#: Set "web": {"lcd_remote_control": false} to make the web LCD read-only.
REMOTE_CONTROL = bool(WEB_CFG.get("lcd_remote_control", True))

SHARED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'run')
LCD_STATE_FILE = os.path.join(SHARED_DIR, 'lcd_state.json')
WEB_BUTTON_FILE = os.path.join(SHARED_DIR, 'web_button.json')

# Button name to number mapping (matches lcd_manager.py)
BUTTON_MAP = {
    'select': 1,
    'up': 2,
    'down': 3,
    'right': 4,
    'left': 5,
}

os.makedirs(SHARED_DIR, exist_ok=True)


def read_lcd_state():
    """Read current LCD state from shared file"""
    try:
        if os.path.exists(LCD_STATE_FILE):
            with open(LCD_STATE_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {'line1': '', 'line2': ''}


def write_web_button(button_num):
    """Write a button press for zerorange.py to pick up"""
    try:
        tmp = WEB_BUTTON_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'button': button_num}, f)
        os.replace(tmp, WEB_BUTTON_FILE)
    except Exception as e:
        print(f"Error writing button: {e}")


@app.route('/api/lcd/state', methods=['GET'])
def get_state():
    """Return current LCD state from physical display"""
    return jsonify(read_lcd_state())


@app.route('/api/lcd/button', methods=['POST'])
def button_press():
    """Send a button press to the physical app via shared file"""
    if not REMOTE_CONTROL:
        return jsonify({'success': False, 'error': 'remote control disabled'}), 403
    # JSON only: a cross-site <form> cannot send application/json without a CORS preflight
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'expected JSON body'}), 415
    button = data.get('button', '')

    button_num = BUTTON_MAP.get(button)
    if button_num:
        write_web_button(button_num)
        print(f"Web button: {button} -> btn {button_num}")

    # Small delay then return current state
    time.sleep(0.2)

    return jsonify({
        'success': True,
        'state': read_lcd_state()
    })


@app.route('/')
def index():
    """API info page"""
    return jsonify({
        'name': 'ZeroRange LCD API',
        'version': '2.0',
        'endpoints': {
            'GET /api/lcd/state': 'Get current LCD state (synced with physical display)',
            'POST /api/lcd/button': 'Send button press to physical app (body: {button: "up|down|left|right|select"})'
        }
    })


if __name__ == '__main__':
    print("=" * 60)
    print("ZeroRange Web LCD Server v2.0 (synced)")
    print("=" * 60)
    print(f"Shared state: {LCD_STATE_FILE}")
    print(f"Button file:  {WEB_BUTTON_FILE}")
    print("\nAPI server on http://0.0.0.0:5000")
    print("=" * 60)

    print(f"Remote control: {'enabled' if REMOTE_CONTROL else 'disabled'}")
    app.run(host='0.0.0.0', port=5000, debug=False)
