import os
import sys
import time
import json
import uuid
import sqlite3
import asyncio
import threading
import webbrowser
import hashlib
import random
import re
import base64
import io
from functools import wraps
from typing import Optional, List, Dict, Union, Any
from PIL import Image, ImageDraw, ImageFilter

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory, Response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import discord

def _patched_create_app(self, name: str, team_id=None):
    payload = {'name': name}
    if team_id is not None:
        payload['team_id'] = team_id
    return self.request(discord.http.Route('POST', '/applications'), json=payload)
discord.http.HTTPClient.create_app = _patched_create_app

def _safe_http_del(self):
    pass
discord.http.HTTPClient.__del__ = _safe_http_del

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'database.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'discord_rpc_master_secret_key_fixed')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

UPLOAD_PATH_MAP = {}
KNOWN_ASSET_ICONS = {
    'vscode': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/vscode/vscode-original.svg',
    'python': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/python/python-original.svg',
    'git': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/git/git-original.svg',
    'docker': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/docker/docker-original.svg',
    'js': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/javascript/javascript-original.svg',
    'ts': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/typescript/typescript-original.svg',
    'jsx': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/react/react-original.svg',
    'tsx': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/react/react-original.svg',
    'html': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/html5/html5-original.svg',
    'css': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/css3/css3-original.svg',
    'c': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/c/c-original.svg',
    'cpp': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/cplusplus/cplusplus-original.svg',
    'csharp': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/csharp/csharp-original.svg',
    'java': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/java/java-original.svg',
    'rust': 'https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/rust/rust-original.svg',
    'go': 'https://cdn.jsdelivr.net/gh/devicons/devicon/icons/go/go-original.svg'
}

LOG_BUFFER = []
MAX_LOG_ENTRIES = 120

QUEST_LOG_BUFFER = []
QUEST_LOG_LOCK = threading.Lock()
MAX_QUEST_LOG_ENTRIES = 200

def log_event(message: str, level: str='info'):
    timestamp = time.strftime('%H:%M:%S')
    entry = {'time': timestamp, 'message': str(message), 'level': level}
    LOG_BUFFER.append(entry)
    if len(LOG_BUFFER) > MAX_LOG_ENTRIES:
        LOG_BUFFER.pop(0)
    print(f'[{timestamp}] [{level.upper()}] {message}')

def quest_log(message: str, level: str = 'info'):
    timestamp = time.strftime('%H:%M:%S')
    entry = {'time': timestamp, 'message': str(message), 'level': level}
    with QUEST_LOG_LOCK:
        QUEST_LOG_BUFFER.append(entry)
        if len(QUEST_LOG_BUFFER) > MAX_QUEST_LOG_ENTRIES:
            QUEST_LOG_BUFFER.pop(0)
    print(f'[QUEST][{timestamp}] [{level.upper()}] {message}')

log_event('Hệ thống Discord RPC Master v2.2 đã sẵn sàng hoạt động.', 'info')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                discord_token TEXT DEFAULT '',
                discord_id TEXT DEFAULT '',
                discord_username TEXT DEFAULT '',
                discord_avatar TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                config TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute("PRAGMA table_info(users)")
        cols = [r['name'] for r in cursor.fetchall()]
        for col_name in ['discord_token', 'discord_id', 'discord_username', 'discord_avatar', 'config']:
            if col_name not in cols:
                try:
                    cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} TEXT DEFAULT ''")
                except Exception:
                    pass
        
        # Tạo tài khoản mặc định admin / 123456 nếu chưa có
        cursor.execute('SELECT * FROM users WHERE username = ?', ('admin',))
        if not cursor.fetchone():
            default_pass = generate_password_hash('123456')
            cursor.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', ('admin', default_pass))
            conn.commit()
            print('[Hệ thống] Đã tự động tạo tài khoản mặc định: admin / 123456')
        conn.commit()

init_db()

def generate_slide_captcha():
    width, height = 320, 160
    piece_w, piece_h = 44, 44
    bg_img = None
    try:
        urls = [
            'https://picsum.photos/320/160?random=' + str(random.randint(1, 9999)),
            'https://picsum.photos/320/160'
        ]
        url = random.choice(urls)
        res = requests.get(url, timeout=2.5)
        if res.status_code == 200:
            bg_img = Image.open(io.BytesIO(res.content)).convert('RGBA')
            if bg_img.size != (width, height):
                bg_img = bg_img.resize((width, height), Image.Resampling.LANCZOS)
    except Exception:
        bg_img = None

    if bg_img is None:
        bg_img = Image.new('RGBA', (width, height), (15, 23, 42, 255))
        draw = ImageDraw.Draw(bg_img)
        for y in range(height):
            r = int(15 + (45 - 15) * (y / height))
            g = int(23 + (15 - 23) * (y / height))
            b = int(42 + (90 - 42) * (y / height))
            draw.line([(0, y), (width, y)], fill=(r, g, b, 255))
        for i in range(0, width, 24):
            draw.line([(i, 0), (i, height)], fill=(99, 102, 241, 40), width=1)
        for j in range(0, height, 20):
            draw.line([(0, j), (width, j)], fill=(6, 182, 212, 40), width=1)
        for _ in range(8):
            cx = random.randint(20, width - 20)
            cy = random.randint(20, height - 20)
            rad = random.randint(15, 45)
            draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=(129, 140, 248, 80), width=2)
            draw.text((cx - 10, cy - 8), "#RPC", fill=(56, 189, 248, 120))

    target_x = random.randint(80, width - piece_w - 20)
    target_y = random.randint(15, height - piece_h - 15)

    session['slide_target_x'] = target_x
    session['slide_target_y'] = target_y
    session['slide_verified'] = False

    mask = Image.new('L', (piece_w, piece_h), 0)
    m_draw = ImageDraw.Draw(mask)
    m_draw.rounded_rectangle([0, 0, piece_w - 1, piece_h - 1], radius=7, fill=255)

    crop = bg_img.crop((target_x, target_y, target_x + piece_w, target_y + piece_h))
    piece_img = Image.new('RGBA', (piece_w, piece_h), (0, 0, 0, 0))
    piece_img.paste(crop, (0, 0), mask)

    p_draw = ImageDraw.Draw(piece_img)
    p_draw.rounded_rectangle([0, 0, piece_w - 1, piece_h - 1], radius=7, outline=(99, 102, 241, 255), width=2)

    hole = Image.new('RGBA', (piece_w, piece_h), (0, 0, 0, 215))
    bg_img.paste(hole, (target_x, target_y), mask)
    bg_draw = ImageDraw.Draw(bg_img)
    bg_draw.rounded_rectangle([target_x, target_y, target_x + piece_w - 1, target_y + piece_h - 1], radius=7, outline=(255, 255, 255, 180), width=2)

    bg_buffer = io.BytesIO()
    bg_img.convert('RGB').save(bg_buffer, format='JPEG', quality=88)
    bg_base64 = base64.b64encode(bg_buffer.getvalue()).decode('utf-8')

    piece_buffer = io.BytesIO()
    piece_img.save(piece_buffer, format='PNG')
    piece_base64 = base64.b64encode(piece_buffer.getvalue()).decode('utf-8')

    return {
        'bg_image': f"data:image/jpeg;base64,{bg_base64}",
        'piece_image': f"data:image/png;base64,{piece_base64}",
        'target_y': target_y,
        'piece_width': piece_w,
        'piece_height': piece_h,
        'bg_width': width,
        'bg_height': height
    }

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Vui lòng đăng nhập để tiếp tục.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class DiscordRPCWorker:
    def __init__(self):
        self.client = None
        self.loop = None
        self.thread = None
        self._active_loop = None
        self._active_client = None
        self._run_id = 0
        self.status = 'stopped'
        self.error_message = None
        self.user_tag = None
        self.user_id = None
        self.start_timestamp = None
        self.current_config = None
        self._managed_app = None
        self._last_name_edit_time = 0
        self._last_icon_edit_time = 0
        self._asset_cache = {}
        self._name_edit_cooldown = 30
        self._lock = threading.Lock()

    def get_status_data(self):
        with self._lock:
            elapsed = 0
            if self.start_timestamp and self.status == 'running':
                elapsed = int(time.time() - self.start_timestamp)
            return {'status': self.status, 'error_message': self.error_message, 'user_tag': self.user_tag, 'user_id': self.user_id, 'elapsed_seconds': elapsed, 'config': self.current_config}

    def start(self, config):
        self.stop()
        with self._lock:
            self._run_id += 1
            current_run_id = self._run_id
            self.status = 'connecting'
            self.error_message = None
            self.current_config = config
            self.start_timestamp = time.time()
            self.thread = threading.Thread(target=self._run_thread, args=(config, current_run_id), daemon=True)
            self.thread.start()

    def update_presence(self, config):
        with self._lock:
            loop = self._active_loop
            client = self._active_client
            if self.status != 'running' or not client or client.is_closed() or not loop:
                self.start(config)
                return True
            self.current_config = config
            future = asyncio.run_coroutine_threadsafe(self._apply_presence(config), loop)
        future.result(timeout=6.0)
        return True

    async def _apply_presence(self, config):
        activity = await self._build_activity(config)
        status_choice = config.get('userStatus', 'online')
        discord_status = getattr(discord.Status, status_choice, discord.Status.online)
        if self.client and not self.client.is_closed():
            await self.client.change_presence(status=discord_status, activity=activity)
            log_event(f'Đã cập nhật trạng thái Rich Presence ({discord_status.value}) thành công.', 'success')

    def stop(self):
        with self._lock:
            if self.status == 'stopped' and (not self.thread or not self.thread.is_alive()):
                return True
            self.status = 'stopping'

        loop = None
        client = None
        thread = None
        with self._lock:
            loop = self._active_loop
            client = self._active_client
            thread = self.thread

        if loop and client and not client.is_closed() and loop.is_running():
            try:
                fut = asyncio.run_coroutine_threadsafe(self._safe_close_client(client, loop), loop)
                fut.result(timeout=3.0)
            except Exception:
                pass

        if loop and loop.is_running():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass

        if thread and thread.is_alive() and threading.current_thread() != thread:
            thread.join(timeout=4.0)

        with self._lock:
            self.status = 'stopped'
            self.user_tag = None
            self.user_id = None
            self.start_timestamp = None
            self._active_loop = None
            self._active_client = None
            self.client = None
            self.loop = None
            self.thread = None

        log_event('Đã dừng và ngắt kết nối an toàn với Discord Gateway.', 'warning')
        return True

    async def _safe_close_client(self, client, loop):
        try:
            if client and not client.is_closed():
                try:
                    await client.change_presence(activity=None, status=discord.Status.invisible)
                except BaseException:
                    pass
                await client.close()
        except BaseException:
            pass
        finally:
            try:
                tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task(loop) and not t.done()]
                for t in tasks:
                    t.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            except BaseException:
                pass

    async def _get_or_create_managed_app(self, desired_name: str, preferred_app_id: Optional[str]=None):
        tag_prefix = '[RPC Master]'
        try:
            my_apps = await self.client.applications()
            if preferred_app_id:
                clean_pref = str(preferred_app_id).strip()
                for app in my_apps:
                    if str(app.id) == clean_pref:
                        log_event(f'Sử dụng chính xác ứng dụng theo App ID: {app.name} ({app.id})', 'info')
                        self._managed_app = app
                        return app
            if desired_name:
                for app in my_apps:
                    if app.name.lower() == desired_name.lower():
                        log_event(f"Tìm thấy ứng dụng trùng tên '{desired_name}': {app.name} ({app.id})", 'info')
                        self._managed_app = app
                        return app
            for app in my_apps:
                desc = getattr(app, 'description', '') or ''
                if tag_prefix in desc or app.name == 'DiscordRPC Master':
                    log_event(f'Tìm thấy ứng dụng đã quản lý: {app.name} ({app.id})', 'info')
                    self._managed_app = app
                    return app
            if my_apps:
                app = my_apps[0]
                log_event(f'Tự động sử dụng ứng dụng có sẵn trên tài khoản: {app.name} ({app.id})', 'info')
                self._managed_app = app
                return app
        except Exception as e:
            log_event(f'Lỗi khi duyệt danh sách ứng dụng: {e}', 'warning')
        
        app_name = desired_name if desired_name else 'DiscordRPC Master'
        try:
            log_event(f"Đang tự động tạo Application mới '{app_name}' trên Discord Developer Portal...", 'info')
            new_app = await self.client.create_application(app_name)
            try:
                await new_app.edit(description='[RPC Master] Tự động quản lý Rich Presence bởi Discord RPC Master')
            except Exception:
                pass
            self._managed_app = new_app
            log_event(f'Tạo thành công Application: {new_app.name} ({new_app.id})', 'success')
            return new_app
        except Exception as e:
            if 'captcha' in str(e).lower():
                log_event('Discord yêu cầu xác thực Captcha khi tạo ứng dụng qua script. Vui lòng mở Developer Portal tạo 1 app bất kỳ.', 'warning')
            else:
                log_event(f'Không thể tự tạo Application: {e}', 'warning')
            return None

    async def _sync_app_name(self, app, desired_name: str):
        if not app or not desired_name:
            return
        if getattr(app, 'name', None) == desired_name:
            return
        now = time.time()
        elapsed = now - self._last_name_edit_time
        if elapsed < self._name_edit_cooldown:
            remain = int(self._name_edit_cooldown - elapsed)
            log_event(f"Tránh Rate Limit: Chờ {remain}s trước khi đổi tên trên Developer Portal.", 'info')
            return
        try:
            log_event(f"Đang đổi tên Application từ '{app.name}' sang '{desired_name}'...", 'info')
            await app.edit(name=desired_name)
            self._last_name_edit_time = now
            log_event(f"Đã đổi tên Application thành '{desired_name}' thành công.", 'success')
        except Exception as e:
            log_event(f'Cảnh báo khi đổi tên Application: {e}', 'warning')

    async def _resolve_or_upload_asset(self, app, img_val: str, prefix: str) -> Optional[str]:
        if not img_val:
            img_val = ''
        img_val = img_val.strip()
        lower_val = img_val.lower()

        if prefix == 's' and not img_val:
            return None

        if lower_val in ('', 'bot', 'app', 'bot_avatar', 'app_icon', 'developer_portal', 'portal', 'default'):
            if prefix == 's':
                return None
            if app:
                try:
                    bot = getattr(app, 'bot', None)
                    if not bot and hasattr(app, 'fetch_bot'):
                        bot = await app.fetch_bot()
                    if bot and bot.avatar:
                        avatar_url = str(bot.avatar.url)
                        return avatar_url
                    if getattr(app, 'icon', None):
                        icon_url = str(app.icon.url)
                        return icon_url
                except Exception:
                    pass
            if not img_val:
                return None

        if any((k in img_val for k in ('discordapp.com/attachments/', 'discordapp.net/attachments/', 'discordapp.com/avatars/', 'discordapp.com/app-icons/', 'discordapp.com/app-assets/', 'mp:'))):
            return img_val
        if lower_val in KNOWN_ASSET_ICONS:
            return KNOWN_ASSET_ICONS[lower_val]

        local_filepath = UPLOAD_PATH_MAP.get(img_val)
        if not local_filepath:
            if '/static/uploads/' in img_val or '/uploads/' in img_val:
                fname = img_val.split('/')[-1].split('?')[0]
                candidate = os.path.join(UPLOAD_FOLDER, fname)
                if os.path.exists(candidate):
                    local_filepath = candidate
            elif not img_val.startswith(('http://', 'https://')):
                candidate = os.path.join(UPLOAD_FOLDER, img_val)
                if os.path.exists(candidate):
                    local_filepath = candidate

        file_bytes = None
        if local_filepath and os.path.exists(local_filepath):
            try:
                with open(local_filepath, 'rb') as f:
                    file_bytes = f.read()
            except Exception:
                pass

        if app and file_bytes:
            try:
                await app.edit(icon=file_bytes)
                if getattr(app, 'icon', None):
                    return str(app.icon.url)
            except Exception:
                pass

        if app and prefix == 'l':
            try:
                bot = getattr(app, 'bot', None)
                if not bot and hasattr(app, 'fetch_bot'):
                    bot = await app.fetch_bot()
                if bot and bot.avatar:
                    return str(bot.avatar.url)
                if getattr(app, 'icon', None):
                    return str(app.icon.url)
            except Exception:
                pass

        if prefix == 'l':
            return KNOWN_ASSET_ICONS.get('vscode')
        return None

    async def _build_activity(self, config):
        activity_type_str = config.get('activityType', 'playing')
        stream_url = config.get('streamUrl', '').strip()
        activity_name = config.get('activityName', 'Visual Studio Code').strip()
        details = config.get('details', '').strip()
        state = config.get('state', '').strip()
        large_image = config.get('largeImage', '').strip()
        large_text = config.get('largeText', '').strip()
        small_image = config.get('smallImage', '').strip()
        small_text = config.get('smallText', '').strip()
        has_timestamp = config.get('hasTimestamp', True)
        btn1_label = config.get('btn1Label', '').strip()
        btn1_url = config.get('btn1Url', '').strip()
        btn2_label = config.get('btn2Label', '').strip()
        btn2_url = config.get('btn2Url', '').strip()
        app_id_str = config.get('appId', '').strip()
        auto_app = config.get('autoApp', True)

        type_mapping = {
            'playing': discord.ActivityType.playing,
            'streaming': discord.ActivityType.streaming,
            'listening': discord.ActivityType.listening,
            'watching': discord.ActivityType.watching,
            'competing': discord.ActivityType.competing
        }
        act_type = type_mapping.get(activity_type_str, discord.ActivityType.playing)
        
        timestamps = None
        if has_timestamp and self.start_timestamp:
            timestamps = {'start': int(self.start_timestamp * 1000)}

        app_id = 383226320970055681
        managed_app = None
        if self.client and not self.client.is_closed():
            managed_app = await self._get_or_create_managed_app(activity_name, app_id_str)
            if managed_app:
                app_id = managed_app.id
                if auto_app:
                    await self._sync_app_name(managed_app, activity_name)

        if not managed_app:
            if app_id_str and app_id_str not in ('1054366629930778644', 'None', ''):
                try:
                    app_id = int(app_id_str)
                except ValueError:
                    app_id = 383226320970055681

        final_large = await self._resolve_or_upload_asset(managed_app, large_image, 'l')
        final_small = await self._resolve_or_upload_asset(managed_app, small_image, 's')

        activity_assets = None
        if final_large or final_small or large_text or small_text:
            activity_assets = discord.ActivityAssets(
                large_image=final_large if final_large else None,
                large_text=large_text if large_text else None,
                small_image=final_small if final_small else None,
                small_text=small_text if small_text else None
            )

        buttons = []
        if btn1_label and btn1_url:
            buttons.append(discord.ActivityButton(label=btn1_label, url=btn1_url))
        if btn2_label and btn2_url:
            buttons.append(discord.ActivityButton(label=btn2_label, url=btn2_url))

        return discord.Activity(
            type=act_type,
            name=activity_name,
            url=stream_url if act_type == discord.ActivityType.streaming else None,
            details=details if details else None,
            state=state if state else None,
            timestamps=timestamps,
            assets=activity_assets,
            buttons=buttons if buttons else None,
            application_id=app_id
        )

    def _run_thread(self, config, run_id):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = discord.Client()

        with self._lock:
            if self._run_id != run_id:
                loop.close()
                return
            self._active_loop = loop
            self._active_client = client
            self.loop = loop
            self.client = client

        token = config.get('token', '').strip()

        @client.event
        async def on_ready():
            try:
                with self._lock:
                    if self._run_id != run_id:
                        return
                    self.user_tag = str(client.user)
                    self.user_id = str(client.user.id)
                log_event(f'Đã đăng nhập tài khoản Discord: {self.user_tag} ({self.user_id})', 'success')
                activity = await self._build_activity(config)
                status_choice = config.get('userStatus', 'online')
                discord_status = getattr(discord.Status, status_choice, discord.Status.online)
                await client.change_presence(status=discord_status, activity=activity)
                with self._lock:
                    if self._run_id == run_id:
                        self.status = 'running'
                log_event(f'Đã phát trạng thái Rich Presence ({discord_status.value}) thành công!', 'success')
            except Exception as e:
                with self._lock:
                    if self._run_id == run_id:
                        self.status = 'error'
                        self.error_message = f'Lỗi khi phát trạng thái: {e}'
                log_event(f'Lỗi nghiêm trọng khi phát trạng thái: {e}', 'error')

        try:
            log_event('Đang kết nối tới Discord Gateway qua User Token...', 'info')
            loop.run_until_complete(client.start(token))
        except discord.errors.LoginFailure:
            with self._lock:
                if self._run_id == run_id:
                    self.status = 'error'
                    self.error_message = 'Discord User Token không hợp lệ hoặc đã bị khóa!'
            log_event('Lỗi LoginFailure: Discord User Token không hợp lệ!', 'error')
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        except Exception as e:
            with self._lock:
                if self._run_id == run_id and self.status not in ('stopped', 'stopping'):
                    self.status = 'error'
                    self.error_message = str(e)
            if self._run_id == run_id and self.status not in ('stopped', 'stopping'):
                log_event(f'Ngoại lệ kết nối Gateway: {e}', 'error')
        finally:
            try:
                if not client.is_closed():
                    loop.run_until_complete(self._safe_close_client(client, loop))
            except BaseException:
                pass
            finally:
                try:
                    loop.close()
                except BaseException:
                    pass

rpc_worker = DiscordRPCWorker()

def normalize_rpc_config(data: dict) -> dict:
    if not isinstance(data, dict):
        return {}
    out = dict(data)
    if 'name' in data and not data.get('activityName'):
        out['activityName'] = data['name']
    if 'activity_name' in data and not data.get('activityName'):
        out['activityName'] = data['activity_name']
    if not out.get('activityName'):
        out['activityName'] = 'Visual Studio Code'
    return out

@app.route('/')
@login_required
def index():
    user_id = session['user_id']
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT username, discord_token, discord_username, discord_avatar FROM users WHERE id = ?', (user_id,))
        u = cursor.fetchone()
    has_token = bool(u and u['discord_token'] and len(u['discord_token']) > 20)
    d_name = (u['discord_username'] if u and u['discord_username'] else None)
    d_avatar = (u['discord_avatar'] if u and u['discord_avatar'] else None)
    return render_template('index.html', username=session.get('username'), has_token=has_token, discord_username=d_name, discord_avatar=d_avatar)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash('Vui lòng nhập đầy đủ tên tài khoản và mật khẩu.', 'error')
            return redirect(url_for('login'))
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            if user['discord_token']:
                session['discord_token'] = user['discord_token']
                session['discord_username'] = user['discord_username']
                session['discord_avatar'] = user['discord_avatar']
            flash(f'Chào mừng trở lại, {username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Tên đăng nhập hoặc mật khẩu không chính xác.', 'error')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Đã đăng xuất thành công.', 'info')
    return redirect(url_for('login'))

@app.route('/api/status', methods=['GET'])
@login_required
def api_status():
    return jsonify(rpc_worker.get_status_data())

@app.route('/api/start', methods=['POST'])
@login_required
def api_start():
    raw_data = request.get_json() or {}
    data = normalize_rpc_config(raw_data)
    token = data.get('token', '').strip()
    if not token:
        user_id = session.get('user_id')
        if user_id:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT discord_token FROM users WHERE id = ?', (user_id,))
                row = cursor.fetchone()
                if row and row['discord_token']:
                    token = row['discord_token']
        if not token and 'discord_token' in session:
            token = session['discord_token']
    if not token:
        return jsonify({'success': False, 'message': 'Chưa có token. Vui lòng liên kết Discord Token tại mục Quản Lý Tài Khoản trước!'}), 400
    data['token'] = token
    rpc_worker.start(data)
    return jsonify({'success': True, 'message': 'Đã gửi lệnh kết nối tới Discord Gateway'})

@app.route('/api/update', methods=['POST'])
@login_required
def api_update():
    raw_data = request.get_json() or {}
    data = normalize_rpc_config(raw_data)
    try:
        rpc_worker.update_presence(data)
        return jsonify({'success': True, 'message': 'Đã cập nhật trạng thái Discord thành công!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi khi cập nhật: {str(e)}'}), 500

@app.route('/api/stop', methods=['POST'])
@login_required
def api_stop():
    rpc_worker.stop()
    return jsonify({'success': True, 'message': 'Đã dừng Discord RPC'})

@app.route('/api/logs', methods=['GET', 'DELETE'])
@login_required
def api_logs():
    global LOG_BUFFER
    if request.method == 'DELETE':
        LOG_BUFFER.clear()
        return jsonify({'success': True, 'message': 'Đã xóa nhật ký'})
    return jsonify({'success': True, 'logs': LOG_BUFFER})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = '0.0.0.0'
    print('=========================================================')
    print('       DISCORD RICH PRESENCE MASTER (Flask + Selfbot)      ')
    print('=========================================================')
    print(f' Đang khởi chạy web server tại http://{host}:{port} ... ')
    try:
        app.run(host=host, port=port, debug=False)
    except (KeyboardInterrupt, SystemExit):
        print('\n[Hệ thống] Đang tắt máy chủ và dọn dẹp tiến trình...')
        rpc_worker.stop()
        sys.exit(0)