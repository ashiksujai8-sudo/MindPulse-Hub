"""
MindPulse Hub — "Predicting Strain, Protecting Minds"
Team Project Mind Guard · Woodlem Park School Dubai · CBSE Artificial Intelligence (843) · Grade 12

Run locally:   streamlit run mindpulse_app.py

Optional secrets (.streamlit/secrets.toml or Streamlit Cloud → Settings → Secrets):
    GEMINI_API_KEY = "your-free-key-from-aistudio.google.com"
    GEMINI_MODEL   = "gemini-flash-latest"      # optional override
    ADMIN_PIN      = "ADMIN2026"                # optional override

    # --- Cloud sync option A: Supabase ---------------------------------------
    # [supabase]
    # url   = "https://xxxx.supabase.co"
    # key   = "service-role-or-anon-key"
    # table = "mindpulse_users"
    #   SQL:  create table mindpulse_users (user_id text primary key, data jsonb not null);

    # --- Cloud sync option B: Google Sheets ----------------------------------
    # [gsheets]
    # spreadsheet = "MindPulse DB"     # sheet name OR the long key from its URL
    # worksheet   = "users"
    # [gcp_service_account]            # paste the service-account JSON fields here
    # type = "service_account"  ...

With no secrets configured the app runs fully offline on the local mindpulse_db.json file.
"""

import streamlit as st
import json
import os
import time
import random
import hashlib
import hmac
import secrets as py_secrets
import inspect
import importlib.util
import io
import re
from datetime import datetime, date, timedelta

import pandas as pd
import streamlit.components.v1 as components

try:
    import plotly.graph_objects as go
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

try:
    import requests
except ImportError:
    requests = None

st.set_page_config(page_title="MindPulse Hub", page_icon="🧠", layout="wide")

# ==============================================================================
# ⚙️ STEP 0: APP CONFIGURATION
# ==============================================================================
DB_FILE = "mindpulse_db.json"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_TIMEZONE = "Asia/Dubai"
DAILY_GOAL_POINTS = 100
GAME_DAILY_CAP = 2          # rewarded plays per arcade game per day
TASK_REWARD_CAP = 3         # rewarded task completions per day
ID_PATTERN = re.compile(r"^[A-Z0-9]{3,12}$")
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,39}$")
DEFAULT_ADMIN_PIN = "ADMIN2026"
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
BACKUP_GEMINI_MODEL = "gemini-3.5-flash"
DATASET_CANDIDATES = ["student_stress_data.csv", "student_stress_data.xlsx", "stress_dataset.csv"]


def now_local():
    """Current time in Dubai (Streamlit Cloud servers run on UTC)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(APP_TIMEZONE)).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def today_str():
    return now_local().strftime("%Y-%m-%d")


def secrets_available():
    """True only when a secrets.toml exists, so st.secrets never prints a red error box."""
    loader = getattr(st.secrets, "load_if_toml_exists", None)
    if loader is not None:
        try:
            return bool(loader())
        except Exception:
            return False
    paths = [
        os.path.expanduser("~/.streamlit/secrets.toml"),
        os.path.join(os.getcwd(), ".streamlit", "secrets.toml"),
        os.path.join(APP_DIR, ".streamlit", "secrets.toml"),
    ]
    return any(os.path.exists(p) for p in paths)


SECRETS_ON = secrets_available()


def get_secret(name, default=None):
    if SECRETS_ON:
        try:
            if name in st.secrets:
                return st.secrets[name]
        except Exception:
            pass
    return os.environ.get(name, default)


GENAI_INSTALLED = importlib.util.find_spec("google.genai") is not None if importlib.util.find_spec("google") else False
CONFIG_FILE = os.path.join(APP_DIR, "mindpulse_config.json")


def load_app_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_app_config(cfg):
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_FILE)


def gemini_key_source():
    if get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY"):
        return "secrets"
    if load_app_config().get("gemini_api_key"):
        return "config"
    return None


def gemini_key():
    return str(get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY") or load_app_config().get("gemini_api_key") or "").strip()


_WIDTH_KW = {}


def full_width(fn):
    """Return the correct 'stretch to full width' keyword for the installed Streamlit version."""
    name = getattr(fn, "__name__", repr(fn))
    if name not in _WIDTH_KW:
        kw = {"use_container_width": True}
        try:
            p = inspect.signature(fn).parameters.get("width")
            if p is not None and isinstance(p.default, str):
                kw = {"width": "stretch"}
        except (TypeError, ValueError):
            pass
        _WIDTH_KW[name] = kw
    return _WIDTH_KW[name]


def wide_button(label, key=None, where=None, **kwargs):
    where = where or st
    return where.button(label, key=key, **full_width(st.button), **kwargs)


def card(key):
    """Bordered glass container (replaces the old empty <div> wrappers, which never actually wrapped widgets)."""
    try:
        return st.container(border=False, key=f"card_{key}")
    except TypeError:  # Streamlit older than 1.42: fall back to the built-in border
        return st.container(border=True)


GAME_BRIDGE_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>html, body { margin: 0; padding: 0; background: transparent; overflow: hidden; } iframe { border: 0; width: 100%; display: block; }</style>
</head><body>
<iframe id="game" allow="autoplay"></iframe>
<script>
  // Tiny Streamlit component bridge: shows the game in an inner frame and passes "win" events back to Python.
  var current = null, frame = document.getElementById("game");
  function send(type, extra) {
    var msg = {isStreamlitMessage: true, type: type};
    for (var k in (extra || {})) { msg[k] = extra[k]; }
    window.parent.postMessage(msg, "*");
  }
  window.addEventListener("message", function (e) {
    var d = e.data || {};
    if (d.type === "streamlit:render") {
      var args = d.args || {}, h = args.height || 400;
      frame.style.height = h + "px";
      if (args.html !== current) { current = args.html; frame.srcdoc = args.html; }
      send("streamlit:setFrameHeight", {height: h});
    } else if (d.mindpulse === "win" && e.source === frame.contentWindow) {
      send("streamlit:setComponentValue", {value: {points: d.points, token: d.token}, dataType: "json"});
    }
  });
  send("streamlit:componentReady", {apiVersion: 1});
</script>
</body></html>
"""


@st.cache_resource(show_spinner=False)
def game_component():
    """Declare the game bridge once per server. Returns None if it can't be created (games still work, without auto points)."""
    try:
        import tempfile
        folder = os.path.join(tempfile.gettempdir(), "mindpulse_game_bridge")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
            f.write(GAME_BRIDGE_HTML)
        return components.declare_component("mindpulse_game_bridge", path=folder)
    except Exception:
        return None


def flash(message, icon="✨", balloons=False):
    """Queue a toast that survives st.rerun()."""
    st.session_state.setdefault("_flash", []).append((message, icon, balloons))


SOUND_RANK = {"click": 1, "chime": 2, "win": 3, "fanfare": 4}
SOUND_NOTES = {  # (frequency Hz, start s, duration s, waveform)
    "click": [(1250, 0, 0.05, "triangle")],
    "chime": [(880, 0, 0.18, "sine"), (1320, 0.09, 0.28, "sine")],
    "win": [(660, 0, 0.14, "triangle"), (880, 0.1, 0.14, "triangle"), (1320, 0.2, 0.35, "sine")],
    "fanfare": [(523, 0, 0.16, "triangle"), (659, 0.13, 0.16, "triangle"), (784, 0.26, 0.16, "triangle"), (1047, 0.39, 0.55, "sine")],
}


def queue_sound(kind):
    """Remember the most important sound to play on the next page load."""
    current = st.session_state.get("_sound")
    if current is None or SOUND_RANK[kind] > SOUND_RANK[current]:
        st.session_state["_sound"] = kind


def play_queued_sound():
    kind = st.session_state.pop("_sound", None)
    if not kind or not st.session_state.get("sound_on", True):
        return
    notes = json.dumps(SOUND_NOTES[kind])
    components.html(f"""<script>
    (function () {{
      try {{
        var ctx = new (window.AudioContext || window.webkitAudioContext)(); ctx.resume();
        {notes}.forEach(function (n) {{
          var o = ctx.createOscillator(), g = ctx.createGain(), t = ctx.currentTime + n[1];
          o.type = n[3]; o.frequency.setValueAtTime(n[0], t);
          g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.18, t + 0.01);
          g.gain.exponentialRampToValueAtTime(0.0001, t + n[2]);
          o.connect(g); g.connect(ctx.destination); o.start(t); o.stop(t + n[2] + 0.02);
        }});
      }} catch (e) {{}}
    }})();
    </script><!-- {random.random()} -->""", height=0)


def show_flashes():
    for message, icon, balloons in st.session_state.pop("_flash", []):
        st.toast(message, icon=icon)
        if balloons:
            st.balloons()
    play_queued_sound()


# ==============================================================================
# 📊 STEP 1: DATABASE LAYER — local JSON now, Google Sheets / Supabase later
# ==============================================================================
META_ROW = "__meta__"


class LocalJSONStore:
    label = "💾 Local JSON (offline)"

    def __init__(self, path):
        self.path = path

    def load(self):
        if not os.path.exists(self.path):
            data = {"users": {}, "active_session_user": None}
            self.save_all(data)
            return data
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("database root is not an object")
        except Exception:
            # Keep a copy of the unreadable file instead of silently overwriting it later
            try:
                os.replace(self.path, self.path + f".corrupt-{int(time.time())}")
            except Exception:
                pass
            data = {"users": {}, "active_session_user": None}
        if not isinstance(data.get("users"), dict):
            data["users"] = {}
        return data

    def save_all(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp, self.path)  # atomic write: a crash can never leave a half-written database

    def save_user(self, uid, record):
        data = self.load()  # merge into the freshest copy so two open tabs don't overwrite each other
        data["users"][uid] = record
        self.save_all(data)

    def delete_user(self, uid):
        data = self.load()
        data["users"].pop(uid, None)
        self.save_all(data)


class _RowStore:
    """Shared logic for cloud tables: one row per user -> (user_id, JSON text)."""

    @staticmethod
    def rows_to_db(rows):
        data = {"users": {}}
        for key, payload in rows:
            try:
                value = json.loads(payload) if isinstance(payload, str) else payload
            except Exception:
                continue
            if key == META_ROW and isinstance(value, dict):
                data.update({k: v for k, v in value.items() if k != "users"})
            elif key:
                data["users"][key] = value
        return data

    @staticmethod
    def db_to_rows(data):
        meta = {k: v for k, v in data.items() if k != "users"}
        rows = [(META_ROW, meta)]
        rows += [(uid, rec) for uid, rec in data.get("users", {}).items()]
        return rows


class GoogleSheetsStore(_RowStore):
    label = "☁️ Google Sheets (cloud sync)"

    def __init__(self, conf, service_account):
        import gspread
        client = gspread.service_account_from_dict(dict(service_account))
        name = conf.get("spreadsheet", "MindPulse DB")
        try:
            book = client.open_by_key(name)
        except Exception:
            book = client.open(name)
        ws_name = conf.get("worksheet", "users")
        try:
            self.ws = book.worksheet(ws_name)
        except Exception:
            self.ws = book.add_worksheet(title=ws_name, rows=1000, cols=2)

    def load(self):
        rows = [(r[0], r[1]) for r in self.ws.get_all_values() if len(r) >= 2 and r[0]]
        return self.rows_to_db(rows)

    def _upsert(self, key, value):
        payload = json.dumps(value, ensure_ascii=False)
        try:
            cell = self.ws.find(key, in_column=1)
        except Exception:
            cell = None
        if cell:
            self.ws.update_cell(cell.row, 2, payload)
        else:
            self.ws.append_row([key, payload])

    def save_all(self, data):
        rows = [[k, json.dumps(v, ensure_ascii=False)] for k, v in self.db_to_rows(data)]
        self.ws.clear()
        self.ws.update(values=rows, range_name="A1")

    def save_user(self, uid, record):
        self._upsert(uid, record)

    def delete_user(self, uid):
        try:
            cell = self.ws.find(uid, in_column=1)
        except Exception:
            cell = None
        if cell:
            self.ws.delete_rows(cell.row)


class SupabaseStore(_RowStore):
    label = "☁️ Supabase (cloud sync)"

    def __init__(self, conf):
        from supabase import create_client
        self.client = create_client(conf["url"], conf["key"])
        self.table = conf.get("table", "mindpulse_users")

    def load(self):
        res = self.client.table(self.table).select("user_id,data").execute()
        return self.rows_to_db([(r["user_id"], r["data"]) for r in (res.data or [])])

    def save_all(self, data):
        payload = [{"user_id": k, "data": v} for k, v in self.db_to_rows(data)]
        self.client.table(self.table).upsert(payload).execute()

    def save_user(self, uid, record):
        self.client.table(self.table).upsert({"user_id": uid, "data": record}).execute()

    def delete_user(self, uid):
        self.client.table(self.table).delete().eq("user_id", uid).execute()


@st.cache_resource(show_spinner=False)
def get_store():
    """Pick the storage backend once per server process. Falls back to local JSON on any problem."""
    note = None
    if SECRETS_ON:
        try:
            if "supabase" in st.secrets:
                return SupabaseStore(dict(st.secrets["supabase"])), None
            if "gsheets" in st.secrets and "gcp_service_account" in st.secrets:
                return GoogleSheetsStore(dict(st.secrets["gsheets"]), st.secrets["gcp_service_account"]), None
        except Exception as exc:
            note = f"Cloud sync unavailable ({type(exc).__name__}); using local JSON."
    return LocalJSONStore(os.path.join(APP_DIR, DB_FILE)), note


STORE, STORE_NOTE = get_store()


@st.cache_data(ttl=20, show_spinner=False)
def _cached_cloud_load():
    return STORE.load()


def load_local_database():
    """Load the whole database (name kept from v1 so the rest of the code reads the same)."""
    if isinstance(STORE, LocalJSONStore):
        return STORE.load()
    try:
        return _cached_cloud_load()
    except Exception:
        return LocalJSONStore(os.path.join(APP_DIR, DB_FILE)).load()


def save_local_database(data_matrix):
    """Save the whole database (used for bulk operations)."""
    STORE.save_all(data_matrix)
    _cached_cloud_load.clear()


def persist_user(uid):
    """Save one student record — safer than rewriting the whole file on every click."""
    try:
        STORE.save_user(uid, db["users"][uid])
    except Exception as exc:
        st.warning(f"Could not sync to cloud ({type(exc).__name__}); saved locally instead.")
        LocalJSONStore(os.path.join(APP_DIR, DB_FILE)).save_user(uid, db["users"][uid])
    _cached_cloud_load.clear()


db = load_local_database()

# ==============================================================================
# 🔐 STEP 1B: ACCOUNT HELPERS — legacy-safe records + salted SHA-256 passwords
# ==============================================================================
HASH_PREFIX = "sha256$"


def hash_password(raw):
    salt = py_secrets.token_hex(8)
    digest = hashlib.sha256((salt + raw).encode("utf-8")).hexdigest()
    return f"{HASH_PREFIX}{salt}${digest}"


def is_hashed(stored):
    return isinstance(stored, str) and stored.startswith(HASH_PREFIX)


def verify_password(stored, raw):
    if is_hashed(stored):
        try:
            _, salt, digest = stored.split("$", 2)
        except ValueError:
            return False
        check = hashlib.sha256((salt + raw).encode("utf-8")).hexdigest()
        return hmac.compare_digest(check, digest)
    # Legacy plain-text password (accounts created before this upgrade)
    return isinstance(stored, str) and hmac.compare_digest(stored, raw)


def ensure_user_schema(uid, record):
    """Turn any stored entry (legacy string or partial dict) into a complete student record.
    Existing keys are never removed — only missing ones are added."""
    if isinstance(record, str):  # legacy format: "Ashik Sujai": "password123"
        record = {"name": uid, "password": record}
    if not isinstance(record, dict):
        record = {"name": uid, "password": ""}
    record.setdefault("name", uid)
    record.setdefault("password", "")
    record.setdefault("high_score", 0)
    record.setdefault("consecutive_days_streak", 0)
    record.setdefault("last_login_date", "")
    for list_key in ("mood_history_records", "journal_entries", "tasks"):
        if not isinstance(record.get(list_key), list):
            record[list_key] = []
    for dict_key in ("points_log", "points_detail", "arcade_log", "stats"):
        if not isinstance(record.get(dict_key), dict):
            record[dict_key] = {}
    if not isinstance(record.get("gratitude_entries"), list):
        record["gratitude_entries"] = []
    return record


def validate_name(raw, uid):
    """Returns (clean_name, error_message)."""
    name = " ".join((raw or "").split())
    if not NAME_PATTERN.match(name):
        return None, "Use 2–40 letters (spaces, apostrophes and hyphens are allowed)."
    if name.upper() == uid.upper():
        return None, "Your name can't be the same as your School ID."
    if name.islower() or name.isupper():
        name = name.title()
    return name, None


def short_name(rec, uid):
    """'Ashik Sujai' -> 'Ashik S.' for leaderboards."""
    parts = str(rec.get("name", uid)).split()
    if not parts or parts[0].upper() == uid.upper():
        return uid
    return parts[0] + (f" {parts[-1][0]}." if len(parts) > 1 else "")


def find_user_key(typed_id):
    """Exact match first (keeps legacy keys like 'Ashik Sujai' working), then case-insensitive."""
    if typed_id in db["users"]:
        return typed_id
    lowered = typed_id.lower()
    for key in db["users"]:
        if key.lower() == lowered:
            return key
    return None


def update_streak(record):
    """True consecutive-day streak: +1 if last login was yesterday, reset to 1 after a missed day."""
    today = now_local().date()
    try:
        last = datetime.strptime(record.get("last_login_date", ""), "%Y-%m-%d").date()
    except ValueError:
        last = None
    if last == today:
        record["consecutive_days_streak"] = max(1, int(record.get("consecutive_days_streak", 1) or 1))
        return
    if last == today - timedelta(days=1):
        record["consecutive_days_streak"] = int(record.get("consecutive_days_streak", 0) or 0) + 1
    else:
        record["consecutive_days_streak"] = 1
    record["last_login_date"] = today.isoformat()


def today_points(record):
    log = record.get("points_log")
    return int(log.get(today_str(), 0)) if isinstance(log, dict) else 0


def trim_days(day_dict, keep=60):
    for old_day in sorted(day_dict)[:-keep]:
        day_dict.pop(old_day, None)


def plays_today(record, activity):
    return int(record.get("arcade_log", {}).get(today_str(), {}).get(activity, 0))


def log_play(record, activity):
    day_log = record.setdefault("arcade_log", {}).setdefault(today_str(), {})
    day_log[activity] = day_log.get(activity, 0) + 1
    trim_days(record["arcade_log"], 30)


def award_points(uid, points, reason, source="other", celebrate=False):
    rec = db["users"][uid]
    day = today_str()
    log = rec.setdefault("points_log", {})
    before = int(log.get(day, 0))
    after = before + points
    log[day] = after
    detail = rec.setdefault("points_detail", {}).setdefault(day, {})
    detail[source] = detail.get(source, 0) + points
    trim_days(log)
    trim_days(rec["points_detail"], 30)
    rec["high_score"] = max(int(rec.get("high_score", 0) or 0), after)
    stats = rec.setdefault("stats", {})
    reached_goal = before < DAILY_GOAL_POINTS <= after
    if reached_goal:
        stats["goal_days"] = stats.get("goal_days", 0) + 1
    persist_user(uid)
    flash(f"+{points} Zen Points · {reason}", "🌟", balloons=reached_goal or celebrate)
    queue_sound("fanfare" if reached_goal else "win" if celebrate else "chime")
    if reached_goal:
        flash(f"Daily {DAILY_GOAL_POINTS}-point goal reached! Badge unlocked.", "🎯")


def bump_stat(uid, stat_name):
    stats = db["users"][uid].setdefault("stats", {})
    stats[stat_name] = stats.get(stat_name, 0) + 1


# ==============================================================================
# 🎛️ STEP 2: GLOBAL SESSION STATE INITIALIZATION
# ==============================================================================
SESSION_DEFAULTS = {
    "logged_in_user_id": None,
    "current_active_tab": "Home",
    "app_appearance_mode": "Dark Glass",
    "chat_history_logs": None,
    "admin_unlocked": False,
    "admin_failures": 0,
    "admin_locked_until": 0.0,
    "gemini_consent": False,
    "breath_code": None,
    "memory_code": None,
    "memory_board_seed": 0,
    "color_theme": "🌊 Ocean Blue",
    "sound_on": True,
}

for _k, _v in SESSION_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v
if st.session_state.breath_code is None:
    st.session_state.breath_code = f"{random.randint(1000, 9999)}"
if st.session_state.memory_code is None:
    st.session_state.memory_code = f"{random.randint(1000, 9999)}"

# A user whose record disappeared (e.g. deleted by an admin) is logged out safely
if st.session_state.logged_in_user_id and st.session_state.logged_in_user_id not in db["users"]:
    st.session_state.logged_in_user_id = None

# ==============================================================================
# 🎨 STEP 3: MASTER TRANS-THEME UI DESIGN MATRIX (Dark Glass / Light Glass)
# ==============================================================================
COLOR_THEMES = {  # name: (accent 1, accent 2, accent 3)
    "🌊 Ocean Blue": ("#00b4d8", "#3a86ff", "#8338ec"),
    "💜 Lavender Calm": ("#b388ff", "#7c4dff", "#e040fb"),
    "🌅 Sunset Coral": ("#ff8a65", "#ff4d6d", "#ffb703"),
    "🌿 Forest Mint": ("#2ec4b6", "#43aa8b", "#90be6d"),
    "🌸 Rose Blush": ("#ff8fab", "#f15bb5", "#c77dff"),
    "🌙 Midnight Gold": ("#ffd166", "#f4a261", "#e76f51"),
}
DEFAULT_COLOR_THEME = "🌊 Ocean Blue"


def hex_rgb(hex_color):
    h = hex_color.lstrip("#")
    return ",".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


def shade(hex_color, factor):
    """factor < 1 darkens a colour (for readable headings on the light background)."""
    h = hex_color.lstrip("#")
    return "#" + "".join(f"{max(0, min(255, int(int(h[i:i + 2], 16) * factor))):02x}" for i in (0, 2, 4))


if st.session_state.color_theme not in COLOR_THEMES:
    st.session_state.color_theme = DEFAULT_COLOR_THEME
A1, A2, A3 = COLOR_THEMES[st.session_state.color_theme]
A1_RGB, A2_RGB, A3_RGB = hex_rgb(A1), hex_rgb(A2), hex_rgb(A3)
DARK = st.session_state.app_appearance_mode == "Dark Glass"
if DARK:
    bg_hex, panel_hex, text_hex, border_hex, title_color = "#0a0f1d", "rgba(17, 24, 39, 0.72)", "#e2e8f0", f"rgba({A2_RGB}, 0.32)", A1
    muted_hex, input_bg, tile_bg = "#94a3b8", "rgba(30, 41, 59, 0.85)", "rgba(30, 41, 59, 0.65)"
else:
    bg_hex, panel_hex, text_hex, border_hex, title_color = "#f8fafc", "rgba(255, 255, 255, 0.82)", "#0f172a", f"rgba({A2_RGB}, 0.25)", shade(A2, 0.7)
    muted_hex, input_bg, tile_bg = "#475569", "rgba(255, 255, 255, 0.95)", "rgba(226, 232, 240, 0.7)"
    A1, A2 = shade(A1, 0.8), shade(A2, 0.8)
PLOT_TEMPLATE = "plotly_dark" if DARK else "plotly_white"

st.markdown(f"""
<style>
@keyframes fadeUp {{ from {{opacity:0; transform:translateY(14px);}} to {{opacity:1; transform:translateY(0);}} }}
@keyframes shimmer {{ 0% {{background-position:0% 50%;}} 50% {{background-position:100% 50%;}} 100% {{background-position:0% 50%;}} }}
@keyframes flame {{ 0%,100% {{transform:scale(1) rotate(-2deg);}} 50% {{transform:scale(1.12) rotate(2deg);}} }}
@keyframes glow {{ 0%,100% {{box-shadow:0 0 0 rgba(57,255,20,0);}} 50% {{box-shadow:0 0 18px rgba(57,255,20,0.35);}} }}
@keyframes breathe {{ 0%,100% {{transform:scale(1);}} 50% {{transform:scale(1.06);}} }}

.stApp {{ background: radial-gradient(1200px 600px at 10% -10%, rgba({A1_RGB},0.12), transparent 60%),
                     radial-gradient(900px 500px at 110% 10%, rgba({A3_RGB},0.10), transparent 60%), {bg_hex} !important;
          color: {text_hex} !important; transition: all 0.5s ease; }}
.stApp p, .stApp li, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5,
.stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stCaptionContainer"] {{ color: {text_hex}; }}
section[data-testid="stSidebar"] > div {{ background: {panel_hex} !important; backdrop-filter: blur(12px); }}

/* Glass panels (every card() container carries an st-key-card_* class) */
div[class*="st-key-card_"] {{
    background-color: {panel_hex} !important; border: 2px solid {border_hex} !important; border-radius: 16px !important;
    backdrop-filter: blur(10px); box-shadow: 0 8px 32px rgba(0,0,0,0.15);
    transition: transform 0.3s ease, box-shadow 0.3s ease; animation: fadeUp 0.55s ease both; }}
div[class*="st-key-card_"]:hover {{
    transform: translateY(-2px); box-shadow: 0 12px 40px rgba({A2_RGB},0.25); }}
div[class*="st-key-card_"] {{ padding: 18px !important; }}

.stButton > button, .stDownloadButton > button, div[data-testid="stFormSubmitButton"] > button {{
    border-radius: 12px !important; border: 1px solid rgba({A2_RGB},0.55) !important;
    background: linear-gradient(135deg, rgba({A1_RGB},0.18), rgba({A2_RGB},0.18)) !important;
    color: {text_hex} !important; font-weight: 600 !important; transition: all 0.25s ease !important; }}
.stButton > button:hover, .stDownloadButton > button:hover, div[data-testid="stFormSubmitButton"] > button:hover {{
    transform: translateY(-2px); border-color: {A1} !important; box-shadow: 0 6px 18px rgba({A1_RGB},0.3); }}
.stTextInput input, .stTextArea textarea, .stDateInput input {{ background: {input_bg} !important; color: {text_hex} !important; }}

.main-logo-text {{ font-family: 'Segoe UI', system-ui, sans-serif !important; font-size: 2.8rem !important; font-weight: 800 !important;
    letter-spacing: -1px; margin-bottom: 0; animation: fadeUp 0.6s ease both; }}
.logo-shimmer {{ background: linear-gradient(90deg, {A1}, {A2}, {A3}, {A1}); background-size: 300% 300%;
    -webkit-background-clip: text; background-clip: text; color: transparent !important; animation: shimmer 6s ease infinite; }}
.motto-text {{ font-size: 1.1rem !important; font-style: italic !important; color: {muted_hex} !important; margin-bottom: 22px; }}

.kpi-tile {{ background: {tile_bg}; border: 1px solid {border_hex}; border-radius: 14px; padding: 14px 10px; text-align: center;
    animation: fadeUp 0.6s ease both; }}
.kpi-value {{ font-size: 2rem; font-weight: 800; line-height: 1.1; }}
.kpi-label {{ font-size: 0.78rem; color: {muted_hex}; letter-spacing: 0.5px; text-transform: uppercase; }}
.flame {{ display: inline-block; animation: flame 1.6s ease-in-out infinite; }}

.badge-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }}
.badge {{ border-radius: 12px; padding: 10px; border: 1px solid {border_hex}; background: {tile_bg}; animation: fadeUp 0.6s ease both; }}
.badge.on {{ border-color: #39ff14; animation: fadeUp 0.6s ease both, glow 2.8s ease-in-out infinite; }}
.badge.off {{ filter: grayscale(1); opacity: 0.45; }}
.badge-icon {{ font-size: 1.6rem; }} .badge-name {{ font-weight: 700; font-size: 0.9rem; }}
.badge-desc {{ font-size: 0.72rem; color: {muted_hex}; }}

.result-card {{ border-radius: 12px; padding: 20px; margin-bottom: 12px; background: {panel_hex}; animation: fadeUp 0.5s ease both; }}
.pill {{ display:inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.78rem; font-weight: 700;
    border: 1px solid {border_hex}; background: {tile_bg}; margin: 2px 4px 2px 0; }}
div[data-testid="stElementContainer"]:has(iframe[height="0"]), .element-container:has(iframe[height="0"]) {{ display: none; }}
div[role="radiogroup"] {{ gap: 8px; flex-wrap: wrap; }}
div[role="radiogroup"] > label {{ background: {tile_bg}; border: 1px solid {border_hex}; border-radius: 999px;
    padding: 6px 14px !important; margin: 0 !important; transition: all .2s ease; }}
div[role="radiogroup"] > label:hover {{ border-color: {A1}; transform: translateY(-1px); }}
div[role="radiogroup"] > label:has(input:checked) {{ background: linear-gradient(135deg, rgba({A1_RGB},.35), rgba({A2_RGB},.35));
    border-color: {A1}; font-weight: 700; }}
.quote-text {{ font-style: italic; font-size: 1.12rem; animation: breathe 7s ease-in-out infinite; }}
</style>
""", unsafe_allow_html=True)

show_flashes()

# ==============================================================================
# 🛡️ STEP 4A: EXAMINER / ADMIN PORTAL (on the access gate)
# ==============================================================================
def admin_pin():
    return str(get_secret("ADMIN_PIN", DEFAULT_ADMIN_PIN))


def build_admin_report():
    rows, legacy = [], 0
    for uid, rec in db["users"].items():
        if not isinstance(rec, dict):
            legacy += 1
            continue
        tasks = rec.get("tasks") if isinstance(rec.get("tasks"), list) else []
        done = sum(1 for t in tasks if isinstance(t, dict) and t.get("status") == "Completed")
        checkins = [m for m in rec.get("mood_history_records", []) if isinstance(m, dict) and "stress_index" in m]
        rows.append({
            "School ID": uid,
            "Student Name": rec.get("name", uid),
            "Streak (days)": int(rec.get("consecutive_days_streak", 0) or 0),
            "High Score": int(rec.get("high_score", 0) or 0),
            "Last Login": rec.get("last_login_date", "") or "—",
            "Tasks Completed": done,
            "Tasks Pending": len(tasks) - done,
            "Stress Check-ins": len(checkins),
            "Latest Stress Tier": checkins[-1].get("tier", "—") if checkins else "—",
            "Journal Entries": len(rec.get("journal_entries", []) or []),
            "Points Today": today_points(rec),
            "Games Played": sum(n for day in (rec.get("arcade_log") or {}).values() if isinstance(day, dict)
                                for act, n in day.items() if act != "task"),
            "Password Storage": "🔒 SHA-256 (salted)" if is_hashed(rec.get("password")) else "⚠️ Legacy — upgrades on next login",
        })
    return pd.DataFrame(rows), legacy


def render_admin_portal():
    if not st.session_state.admin_unlocked:
        with card("admin_login"):
            st.subheader("🧑‍🏫 Examiner / Admin Portal")
            st.caption("Overview for teachers and external examiners. Journal text and passwords are never shown.")
            locked_for = int(st.session_state.admin_locked_until - time.time())
            if locked_for > 0:
                st.error(f"Too many wrong PIN attempts. Try again in {locked_for} s.")
                return
            with st.form("admin_pin_form", clear_on_submit=True):
                pin = st.text_input("Examiner PIN", type="password")
                if st.form_submit_button("Unlock Portal", **full_width(st.form_submit_button)):
                    if hmac.compare_digest(pin.strip(), admin_pin()):
                        st.session_state.admin_unlocked = True
                        st.session_state.admin_failures = 0
                        st.rerun()
                    else:
                        st.session_state.admin_failures += 1
                        if st.session_state.admin_failures >= 5:
                            st.session_state.admin_locked_until = time.time() + 60
                            st.session_state.admin_failures = 0
                        st.error("Incorrect PIN.")
        return

    report, legacy_count = build_admin_report()
    head_l, head_r = st.columns([4, 1])
    head_l.markdown(f"<h2 style='margin:0;color:{title_color};'>🧑‍🏫 Examiner Dashboard</h2>", unsafe_allow_html=True)
    if head_r.button("🔒 Lock Portal", **full_width(st.button)):
        st.session_state.admin_unlocked = False
        st.rerun()

    total_students = len(report)
    total_done = int(report["Tasks Completed"].sum()) if total_students else 0
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Registered Students", total_students)
    m2.metric("Tasks Completed", total_done)
    m3.metric("Avg. Streak (days)", f"{report['Streak (days)'].mean():.1f}" if total_students else "0")
    m4.metric("Stress Check-ins", int(report["Stress Check-ins"].sum()) if total_students else 0)
    if legacy_count:
        st.caption(f"ℹ️ {legacy_count} legacy pre-upgrade entr{'y' if legacy_count == 1 else 'ies'} skipped — "
                   "they convert to full profiles automatically on that student's next login.")

    if total_students:
        st.dataframe(report, hide_index=True, **full_width(st.dataframe))
        st.download_button(
            "⬇️ Download CSV Report",
            data=report.to_csv(index=False).encode("utf-8"),
            file_name=f"mindpulse_report_{today_str()}.csv",
            mime="text/csv",
            **full_width(st.download_button),
        )
        with st.expander("🛠️ Teacher tools — reset a student's forgotten password"):
            with st.form("reset_pw_form", clear_on_submit=True):
                target = st.selectbox("Student", list(report["School ID"]),
                                      format_func=lambda u: f"{u} — {db['users'][u].get('name', u)}")
                temp_pw = st.text_input("New temporary password (min. 6 characters)", type="password")
                if st.form_submit_button("Reset Password", **full_width(st.form_submit_button)):
                    if len(temp_pw) < 6:
                        st.error("Temporary password must be at least 6 characters.")
                    else:
                        db["users"][target]["password"] = hash_password(temp_pw)
                        persist_user(target)
                        st.success(f"Password for {target} reset. Ask the student to change it under 👤 My Profile.")
    with st.expander("🤖 Online AI counselor (Google Gemini) setup"):
        source = gemini_key_source()
        if source == "secrets":
            st.success("✅ Gemini key is set in Streamlit secrets.")
        elif source == "config":
            st.success("✅ Gemini key is saved on this computer. Students can switch on online AI in the Counselor.")
        else:
            st.info("No key yet. Get a free one at aistudio.google.com → 'Get API key', then paste it below.")
        if not GENAI_INSTALLED:
            st.warning("The `google-genai` library isn't installed, so online AI can't run until it is.")
        with st.form("gemini_key_form", clear_on_submit=True):
            new_key = st.text_input("Gemini API key", type="password", help="Saved in mindpulse_config.json next to the app. It is never shown again.")
            new_model = st.text_input("Model (optional)", placeholder=DEFAULT_GEMINI_MODEL)
            if st.form_submit_button("💾 Save AI settings", **full_width(st.form_submit_button)):
                if len(new_key.strip()) < 20:
                    st.error("That doesn't look like a Gemini API key.")
                else:
                    cfg = load_app_config()
                    cfg["gemini_api_key"] = new_key.strip()
                    if new_model.strip():
                        cfg["gemini_model"] = new_model.strip()
                    save_app_config(cfg)
                    st.success("Saved. Online AI is now available to every student on this computer.")
        if source == "config" and st.button("🗑️ Remove saved key"):
            cfg = load_app_config()
            cfg.pop("gemini_api_key", None)
            save_app_config(cfg)
            st.rerun()
        st.caption("⚠️ Never upload mindpulse_config.json to GitHub or share it. It contains your private key.")
    with st.expander("📦 Backup & move data (laptop ⇄ online version)"):
        st.caption("Download a full backup of every student record, or import records collected on another copy of "
                   "MindPulse (for example, your offline laptop testing session) into this one.")
        st.download_button("⬇️ Download full backup (mindpulse_db.json)",
                           data=json.dumps(load_local_database(), indent=2, ensure_ascii=False).encode("utf-8"),
                           file_name=f"mindpulse_backup_{today_str()}.json", mime="application/json",
                           **full_width(st.download_button))
        upload = st.file_uploader("Import a mindpulse_db.json file", type=["json"])
        overwrite = st.checkbox("Replace students who already exist here (otherwise they are skipped)")
        if upload is not None and st.button("📥 Import students", **full_width(st.button)):
            try:
                incoming = json.loads(upload.getvalue().decode("utf-8"))
                incoming_users = incoming.get("users", {}) if isinstance(incoming, dict) else {}
            except Exception:
                incoming_users = None
            if not isinstance(incoming_users, dict):
                st.error("That file isn't a MindPulse database.")
            else:
                added = replaced = skipped = 0
                for uid_in, rec_in in incoming_users.items():
                    if not isinstance(rec_in, dict):
                        skipped += 1  # old-format entries are left behind
                        continue
                    if uid_in in db["users"] and not overwrite:
                        skipped += 1
                        continue
                    replaced += uid_in in db["users"]
                    added += uid_in not in db["users"]
                    db["users"][uid_in] = ensure_user_schema(uid_in, rec_in)
                    STORE.save_user(uid_in, db["users"][uid_in])
                _cached_cloud_load.clear()
                st.success(f"Imported: {added} new, {replaced} replaced, {skipped} skipped.")
    if legacy_count:
        with st.expander(f"🧹 Clean up {legacy_count} old pre-upgrade test entr{'y' if legacy_count == 1 else 'ies'}"):
            legacy_ids = [u for u, r in db["users"].items() if not isinstance(r, dict)]
            st.caption("These are old-format logins (ID + password only, no profile data): " + ", ".join(legacy_ids))
            confirm = st.checkbox("I understand these old entries will be permanently removed")
            if st.button("Remove old entries", disabled=not confirm):
                for u in legacy_ids:
                    STORE.delete_user(u)
                    db["users"].pop(u, None)
                _cached_cloud_load.clear()
                st.success(f"Removed {len(legacy_ids)} old entries.")
                st.rerun()
    if total_students and PLOTLY_OK:
        fig = go.Figure(go.Bar(x=report["Student Name"], y=report["High Score"],
                               marker_color=A2, text=report["High Score"], textposition="outside"))
        fig.update_layout(template=PLOT_TEMPLATE, height=300, margin=dict(l=10, r=10, t=40, b=10),
                          title="High Score by Student", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, **full_width(st.plotly_chart))
    elif not total_students:
        st.info("No full student profiles registered yet.")
    st.caption(f"Storage backend: {STORE.label}")


# ==============================================================================
# 🔒 STEP 4B: INTERACTIVE STUDENT AUTHENTICATION ACCESS GATE (PRESERVED DESIGN)
# ==============================================================================
if st.session_state.logged_in_user_id is None:
    st.markdown(f"<h1 style='text-align:center; color:{title_color}; margin-top:30px;'>🛡️ ProjectMind Guard Access Gate</h1>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align:center; color:{muted_hex};'>Please authenticate using your verified Student Account credentials to run MindPulse.</p>", unsafe_allow_html=True)

    gate_view = st.radio("Access mode", ["🎓 Student Access", "🧑‍🏫 Examiner / Admin Portal"], horizontal=True,
                         key="gate_view", label_visibility="collapsed")  # stays put after a form is submitted

    if gate_view == "🎓 Student Access":
        auth_col1, auth_col2 = st.columns(2)
        with auth_col1:
            with card("login"):
                st.subheader("🔑 Student Login")
                with st.form("login_form"):
                    login_id = st.text_input("Enter School ID (e.g., WD1234)").strip()
                    login_pw = st.text_input("Enter Password", type="password")
                    submitted = st.form_submit_button("Access Account Dashboard", **full_width(st.form_submit_button))
                if submitted:
                    key = find_user_key(login_id) if login_id else None
                    stored = db["users"].get(key) if key else None
                    stored_pw = stored if isinstance(stored, str) else (stored or {}).get("password", "")
                    if key and login_pw and verify_password(stored_pw, login_pw):
                        record = ensure_user_schema(key, stored)
                        if not is_hashed(record["password"]):
                            record["password"] = hash_password(login_pw)  # silent upgrade of legacy passwords
                        update_streak(record)
                        db["users"][key] = record
                        persist_user(key)
                        st.session_state.logged_in_user_id = key
                        st.session_state.admin_unlocked = False
                        if record.get("saved_theme") in COLOR_THEMES:
                            st.session_state.color_theme = record["saved_theme"]
                        if record.get("appearance_mode") in ("Dark Glass", "Light Glass"):
                            st.session_state.app_appearance_mode = record["appearance_mode"]
                        st.session_state.sound_on = bool(record.get("sound_on", True))
                        queue_sound("chime")
                        st.session_state.current_active_tab = "Home"
                        flash(f"Welcome back, {record['name']}!", "👋")
                        st.rerun()
                    else:
                        st.error("Invalid School ID or Password.")

        with auth_col2:
            with card("register"):
                st.subheader("📝 Register New Student Profile")
                with st.form("register_form", clear_on_submit=False):
                    reg_name = st.text_input("Full Name").strip()
                    reg_id = st.text_input("Allocate School ID (e.g., WD1234)").strip().upper()
                    reg_pw = st.text_input("Create Private Access Password", type="password")
                    reg_pw2 = st.text_input("Confirm Password", type="password")
                    reg_submit = st.form_submit_button("Establish System Record Profile", **full_width(st.form_submit_button))
                if reg_submit:
                    clean_name, name_error = validate_name(reg_name, reg_id or "-")
                    if not reg_name or not reg_id or not reg_pw:
                        st.error("All registration fields must be filled in.")
                    elif not ID_PATTERN.match(reg_id):
                        st.error("School ID must be 3–12 letters or numbers, with no spaces (e.g., WD1234).")
                    elif name_error:
                        st.error(f"Full Name: {name_error}")
                    elif len(reg_pw) < 6:
                        st.error("Password must be at least 6 characters.")
                    elif reg_pw != reg_pw2:
                        st.error("Passwords do not match.")
                    elif find_user_key(reg_id) is not None:
                        st.error("This School ID is already registered to another profile.")
                    else:
                        db["users"][reg_id] = ensure_user_schema(reg_id, {
                            "name": clean_name,
                            "password": hash_password(reg_pw),
                            "high_score": 0,
                            "consecutive_days_streak": 0,
                            "last_login_date": "",
                            "mood_history_records": [],
                            "journal_entries": [],
                            "tasks": [],
                        })
                        persist_user(reg_id)
                        st.success("Account profile created! Sign in using the Student Login panel.")

    else:
        render_admin_portal()

    st.caption(f"🔐 Passwords are stored as salted SHA-256 hashes · Storage: {STORE.label}")
    st.stop()

# ------------------------------------------------------------------------------
UID = st.session_state.logged_in_user_id
user_data = ensure_user_schema(UID, db["users"][UID])
db["users"][UID] = user_data

# ==============================================================================
# 🤖 STEP 4C: AI ENGINES — quotes, Gemini counselor, computer vision, ML model
# ==============================================================================
FALLBACK_QUOTES = [
    ("Your worth is not defined by a specific score grade. Real learning is a lifelong journey.", "MindPulse Wellness Team"),
    ("Take short breaks to preserve your peace. A rested brain retains information faster.", "MindPulse Wellness Team"),
    ("Deconstruct huge study targets into tiny daily steps. Progress beats absolute perfection.", "MindPulse Wellness Team"),
    ("Anxiety tells you stories about tomorrow that haven't happened. Focus on what you can control right now.", "MindPulse Wellness Team"),
    ("One chapter at a time is still forward.", "MindPulse Wellness Team"),
    ("Sleep is part of your revision plan, not a break from it.", "MindPulse Wellness Team"),
    ("A mock paper measures a morning, not your future.", "MindPulse Wellness Team"),
    ("Drink water, stretch, breathe — then try the hard question again.", "MindPulse Wellness Team"),
    ("Asking for help is a study skill too.", "MindPulse Wellness Team"),
    ("Almost everything will work again if you unplug it for a few minutes, including you.", "Anne Lamott"),
    ("Sleep is the golden chain that ties health and our bodies together.", "Thomas Dekker"),
    ("Take rest; a field that has rested gives a bountiful crop.", "Ovid"),
    ("Well begun is half done.", "Aristotle"),
    ("Knowing is not enough; we must apply.", "Johann Wolfgang von Goethe"),
    ("He who has a why to live can bear almost any how.", "Friedrich Nietzsche"),
    ("Rest is not idleness.", "John Lubbock"),
    ("The beautiful thing about learning is that nobody can take it away from you.", "B.B. King"),
]


@st.cache_data(ttl=900, show_spinner=False)
def fetch_zen_quote(day_key):
    """ZenQuotes 'quote of the day'. Returns None when offline (cached 15 min so the page stays fast)."""
    if requests is None:
        return None
    try:
        resp = requests.get("https://zenquotes.io/api/today", timeout=4)
        resp.raise_for_status()
        item = resp.json()[0]
        quote, author = item.get("q", "").strip(), item.get("a", "").strip()
        if not quote or "too many requests" in quote.lower():
            return None
        return {"q": quote, "a": author or "Unknown", "source": "ZenQuotes API", "live": True}
    except Exception:
        return None


def thought_of_the_day():
    live = fetch_zen_quote(today_str())
    if live:
        return live
    q, a = FALLBACK_QUOTES[now_local().timetuple().tm_yday % len(FALLBACK_QUOTES)]
    return {"q": q, "a": a, "source": "MindPulse offline quote library", "live": False}


# ---- Conversational counselor -------------------------------------------------
COUNSELOR_SYSTEM_PROMPT = """You are MindPulse, a friendly, supportive AI companion built into a student wellbeing app for
Grade 11-12 CBSE students in Dubai. Chat naturally like a helpful assistant: answer greetings warmly, answer general
questions (school subjects, homework concepts, general knowledge, how-to questions) clearly and correctly, and gently
bring in wellbeing when it fits. When a student is stressed, be empathetic first, then practical. Keep replies under
150 words unless the student asks for more detail, use short paragraphs or up to 4 bullet points, and use the student's
first name occasionally. Give evidence-based study and wellbeing tips (sleep, breaks, active recall, spaced repetition,
breathing, hydration, movement, realistic timetables). Do not write graded assignments for students; explain and guide
instead. You are not a doctor or therapist: never diagnose and never discuss medication doses. Keep everything
appropriate for teenagers. If a student mentions self-harm, suicide, abuse or feeling unsafe, respond with care, urge
them to talk to a parent, trusted adult or the school counsellor right now, and share the UAE Mental Support Line
800 4673 (800 HOPE, call or WhatsApp) and emergency numbers 999 / 998."""

CRISIS_TERMS = ["suicide", "suicidal", "kill myself", "end my life", "want to die", "self harm", "self-harm",
                "hurt myself", "cut myself", "no reason to live", "better off dead", "don't want to live",
                "dont want to live", "end it all"]
CRISIS_REPLY = ("I'm really glad you told me, and I'm sorry you're carrying this much right now. You deserve "
                "support from a real person today. Please talk to a parent, a trusted adult or your school counsellor "
                "as soon as you can. In the UAE you can call or WhatsApp the Mental Support Line on **800 4673 (800 HOPE)**. "
                "If you are in immediate danger, call **999** (police) or **998** (ambulance). You are not alone in this.")


def chat_greeting(name):
    first = str(name).split()[0] if name else "there"
    return {"role": "assistant",
            "message": f"Hi {first}! 👋 I'm MindPulse, your study and wellbeing companion. How can I help you today? "
                       "You can tell me how you're feeling, ask for study tips, or tap one of the quick questions below."}


# Each intent: (name, regex pattern, list of reply variants). {name} is replaced with the student's first name.
SOCIAL_INTENTS = [
    ("greeting", r"\b(hi+|hello|hey+|hiya|yo|sup|good (morning|afternoon|evening)|salam|assalamu ?alaikum|namaste)\b", [
        "Hello {name}! 👋 How can I help you today?",
        "Hi {name}! 😊 What's on your mind today: studies, stress, sleep, or something else?",
        "Hey {name}! Good to see you. How are you feeling today?"]),
    ("how_are_you", r"\bhow (are|r) (you|u)\b|\bhow'?s it going\b|\bwhat'?s up\b", [
        "I'm doing great, thanks for asking, {name}! 😊 More importantly, how are *you* feeling today?",
        "All good on my side! How's your day going, {name}? Anything I can help with?"]),
    ("thanks", r"\b(thanks|thank you|thank u|thx|ty|appreciate it)\b", [
        "You're very welcome, {name}! 💙 I'm here whenever you need me.",
        "Anytime, {name}! Proud of you for looking after yourself. 🌱"]),
    ("bye", r"\b(bye|goodbye|see (you|ya)|good ?night|gn|cya)\b", [
        "Bye {name}! Take care, drink some water, and get good sleep tonight. 🌙",
        "See you soon, {name}! Remember: small steps every day add up. 💪"]),
    ("identity", r"\b(who|what) are (you|u)\b|\byour name\b|\bare (you|u) (a )?(bot|ai|robot|human)\b", [
        "I'm **MindPulse**, an AI companion built by Team Project Mind Guard to help students handle exam stress, "
        "plan their studies and look after their wellbeing. Right now I'm in offline mode, so I'm best at study and "
        "wellbeing topics. How can I help, {name}?"]),
    ("capabilities", r"\bwhat can (you|u) do\b|\bhow can (you|u) help\b|\b(options|menu)\b|^help$", [
        "I can help you with:\n- 😮‍💨 calming down when you feel anxious or panicky\n- 📋 planning a realistic revision timetable\n"
        "- 😴 sleep and energy tips\n- 🎯 focus and beating procrastination\n- 💪 motivation after a bad result\n\n"
        "What would you like to start with, {name}?"]),
]

TOPIC_INTENTS = [
    ("panic", r"\b(panic\w*|anxious|anxiety|nervous|scared|afraid|worried|worry|calm (me )?down|attack|shaking|heart (is )?racing)\b", [
        "That sounds really uncomfortable, {name}, but you're safe and this feeling will pass. Let's slow your body down "
        "with **4-7-8 breathing**: breathe in through your nose for 4 counts, hold for 7, and breathe out slowly through "
        "your mouth for 8. Repeat 4 times. A long, slow exhale helps switch on your body's calming response. "
        "Want to try the animated breathing guide in the 🕹️ Zen Arcade too?"]),
    ("mock", r"\b(poor(ly)?|mock|fail(ed|ing)?|low (score|marks|grade)|bad (result|marks|grade|score)|demotivated|disappointed)\b", [
        "I'm sorry, {name}. That's a tough feeling. But a mock score is **feedback, not a verdict** on how smart you are. "
        "Go through the paper and sort every lost mark into: *didn't know the concept*, *silly mistake*, or *ran out of "
        "time*. Then fix the biggest group first. That's how marks go up fastest. Which subject was it?"]),
    ("timetable", r"\b(timetable|time ?table|schedule|revision|revise|study plan|plan my|cbse|boards?|syllabus)\b", [
        "Let's make it realistic, {name}:\n- 🌅 Put **hard, analytical subjects in the morning** when your focus is strongest\n"
        "- 🧠 Use afternoons for **active recall**: practice questions and past papers\n- ⏱️ Study in **45-50 minute blocks** "
        "with 10-minute breaks\n- 🔁 Revisit each topic after 1 day, 1 week and 1 month (spaced repetition)\n\n"
        "How many weeks do you have until your exams?"]),
    ("headache", r"\b(head ?ache|my head|head hurts|tired|exhausted|fatigue|burn(ed|t)? ?out|drained|clarity|brain fog|6 hours|hours straight)\b", [
        "Studying for hours without a break overloads your brain and lowers how much you actually remember, {name}. "
        "Right now: **step away from all screens for 10-15 minutes**, drink a full glass of water, stretch your neck and "
        "shoulders, and look out of a window. When you come back, switch to a lighter task first. Have you eaten recently?"]),
    ("sleep", r"\b(sleep\w*|insomnia|can'?t sleep|awake at night|late night|all[- ]nighter|tired in the morning)\b", [
        "Sleep is when your brain saves what you studied, so it's part of revision, {name}, not a break from it. "
        "Teens need about **8-10 hours**. Try: a fixed bedtime, no screens for the last hour, no caffeine after 3 pm, "
        "and writing tomorrow's to-do list before bed so your mind can switch off. What time do you usually sleep?"]),
    ("focus", r"\b(procrastinat\w*|lazy|can'?t (start|focus|concentrate)|distracted|distraction|phone|social media|focus|concentrat\w*)\b", [
        "Totally normal, {name}. Starting is the hardest part. Try the **2-minute rule**: commit to just 2 minutes of the "
        "task; usually you'll keep going. Put your phone in another room, set a 25-minute timer, and pick **one** tiny "
        "goal (e.g. 'finish 3 questions'). Which subject are you avoiding right now?"]),
    ("motivation", r"\b(motivat\w*|give up|giving up|pointless|no energy|unmotivated|hopeless|can'?t do (this|it))\b", [
        "It's okay to feel like this, {name}. Motivation comes and goes, but **small wins** build it back. Choose one "
        "easy task you can finish in 15 minutes and tick it off in your 🗺️ Priority Planner. Remember *why* you started, "
        "and be as kind to yourself as you'd be to a friend. What's one small thing you could do today?"]),
    ("pressure", r"\b(parents?|pressure|expectations?|compare|comparison|toppers?|everyone else)\b", [
        "That pressure can feel really heavy, {name}. Try to focus on **your own progress** compared to last month, not "
        "on others. If expectations at home feel too much, a calm talk with your parents or school counsellor about "
        "how you're feeling, and your realistic plan, often helps more than you'd expect. Would you like help planning "
        "what to say?"]),
    ("lonely", r"\b(lonely|alone|no friends|isolated|left out|nobody)\b", [
        "I'm sorry you're feeling alone, {name}. That's hard. Reaching out to just one person (a friend, a cousin, a "
        "teacher) for a short chat or a study session together can really help. Your school counsellor is also there "
        "for exactly this. Is there someone you feel comfortable messaging today?"]),
    ("exam_tomorrow", r"\b(exam (is )?tomorrow|tomorrow'?s exam|last minute|night before|exam today)\b", [
        "You've got this, {name}! For tonight: **skim your summary notes and formulas** (don't start new topics), pack "
        "your bag and ID now, eat a proper dinner, and get to bed on time. Sleep will help you more than late cramming. "
        "In the exam, read every question carefully and start with the ones you're confident about. 💪"]),
]

OFFLINE_DEFAULT = ("I'm in **offline mode** right now, {name}, so I understand study and wellbeing topics best: exam "
                   "stress, sleep, focus, motivation, revision planning and more. Could you tell me a bit more about "
                   "what's on your mind? (For general questions, ask your teacher to switch on the online AI.)")


def offline_counselor_reply(text, name="there"):
    """Offline NLP engine: regex intent matching with word boundaries, varied replies and the student's name."""
    first = str(name).split()[0] if name else "there"
    t = " ".join(text.lower().split())
    topic = next((replies for _, pattern, replies in TOPIC_INTENTS if re.search(pattern, t)), None)
    social = next((replies for _, pattern, replies in SOCIAL_INTENTS if re.search(pattern, t)), None)
    if topic:
        reply = random.choice(topic).format(name=first)
        if social is SOCIAL_INTENTS[0][2]:  # "hi, I'm stressed" -> greet, then help
            reply = f"Hi {first}! " + reply
        return reply
    if social:
        return random.choice(social).format(name=first)
    return OFFLINE_DEFAULT.format(name=first)


def ask_gemini(history, student_name):
    """Returns (reply_text, error_message). Tries the configured model, then a backup model."""
    from google import genai
    from google.genai import types
    try:
        client = genai.Client(api_key=gemini_key(), http_options=types.HttpOptions(timeout=25000))
    except Exception:
        client = genai.Client(api_key=gemini_key())
    contents = []
    for turn in history[-14:]:
        role = "user" if turn["role"] == "user" else "model"
        if not contents and role == "model":
            continue  # conversations sent to Gemini must start with a user turn
        contents.append(types.Content(role=role, parts=[types.Part(text=turn["message"])]))
    config = types.GenerateContentConfig(
        system_instruction=COUNSELOR_SYSTEM_PROMPT + f"\nThe student's first name is {student_name.split()[0]}.",
        temperature=0.7,
    )
    models = [str(get_secret("GEMINI_MODEL") or load_app_config().get("gemini_model") or DEFAULT_GEMINI_MODEL), BACKUP_GEMINI_MODEL]
    last_error = "unknown error"
    for model in dict.fromkeys(models):
        try:
            reply = client.models.generate_content(model=model, contents=contents, config=config)
            text = (getattr(reply, "text", None) or "").strip()
            if text:
                return text, None
            last_error = "empty reply"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
    return None, last_error


# ---- Computer vision emotion scanner -----------------------------------------
EMOTION_STRESS_WEIGHTS = {"angry": 18, "fear": 20, "sad": 15, "disgust": 10, "surprise": 4, "neutral": 0, "happy": -10}
EMOTION_EMOJI = {"angry": "😠", "fear": "😨", "sad": "😢", "disgust": "😖", "surprise": "😲", "neutral": "😐", "happy": "😊"}


def available_cv_engine():
    if importlib.util.find_spec("deepface"):
        return "DeepFace (deep CNN)"
    if importlib.util.find_spec("fer"):
        return "FER (CNN)"
    if importlib.util.find_spec("cv2"):
        return "OpenCV Haar cascades (basic)"
    return None


@st.cache_data(show_spinner=False, max_entries=8)
def analyze_emotion(image_bytes):
    """Detect facial emotion in-memory. Returns dict(engine, emotions{name: %}, dominant, face_found) or error."""
    import numpy as np
    from PIL import Image
    rgb = np.array(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
    bgr = rgb[:, :, ::-1].copy()
    errors = []

    if importlib.util.find_spec("deepface"):
        try:
            from deepface import DeepFace
            res = DeepFace.analyze(img_path=bgr, actions=["emotion"], enforce_detection=False,
                                   detector_backend="opencv", silent=True)
            res = res[0] if isinstance(res, list) else res
            emotions = {k: float(v) for k, v in res["emotion"].items()}
            face_found = float(res.get("face_confidence", 1) or 0) > 0
            return {"engine": "DeepFace", "emotions": emotions, "dominant": res["dominant_emotion"], "face_found": face_found}
        except Exception as exc:
            errors.append(f"DeepFace: {type(exc).__name__}")

    if importlib.util.find_spec("fer"):
        try:
            try:
                from fer import FER
            except ImportError:
                from fer.fer import FER
            faces = FER(mtcnn=False).detect_emotions(bgr)
            if faces:
                emotions = {k: float(v) * 100 for k, v in faces[0]["emotions"].items()}
                return {"engine": "FER", "emotions": emotions, "dominant": max(emotions, key=emotions.get), "face_found": True}
            errors.append("FER: no face found")
        except Exception as exc:
            errors.append(f"FER: {type(exc).__name__}")

    if importlib.util.find_spec("cv2"):
        try:
            import cv2
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            smile_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_smile.xml")
            if face_cascade.empty() or smile_cascade.empty():
                raise RuntimeError("Haar cascade files missing")
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
            if len(faces) == 0:
                return {"engine": "OpenCV Haar", "emotions": {}, "dominant": None, "face_found": False}
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            lower_face = gray[y + h // 2: y + h, x: x + w]
            smiles = smile_cascade.detectMultiScale(lower_face, scaleFactor=1.7, minNeighbors=22, minSize=(25, 25))
            dominant = "happy" if len(smiles) else "neutral"
            return {"engine": "OpenCV Haar", "emotions": {dominant: 100.0}, "dominant": dominant, "face_found": True}
        except Exception as exc:
            errors.append(f"OpenCV: {type(exc).__name__}")

    return {"engine": None, "emotions": {}, "dominant": None, "face_found": False, "error": "; ".join(errors) or "no CV library installed"}


def emotion_stress_adjustment(emotions):
    """Probability-weighted emotion score: fear/anger/sadness raise stress, happiness lowers it."""
    if not emotions:
        return 0.0
    total = sum(emotions.values()) or 1.0
    return sum((pct / total) * EMOTION_STRESS_WEIGHTS.get(name, 0) for name, pct in emotions.items())


# ---- Stress index + 5-tier classification ------------------------------------
STRESS_TIERS = [
    (55.0, "🔴 Highly Stressed", "#ff4a4a",
     "Your schedule has hit a critical overload. Enforce a mandatory revision halt at 9:30 PM sharp tonight and prioritize restorative rest."),
    (40.0, "🟠 Stressed", "#ffb703",
     "Your tension markers are climbing. Try the 20-20-20 visual rule: look 20 feet away for 20 seconds every 20 minutes to reset focus."),
    (25.0, "🟡 Neutral", "#00b4d8",
     "You are maintaining an average tracking line. Structure a 50-10 Pomodoro loop to take short breaks and preserve efficiency."),
    (15.0, "🟢 Relaxed", "#2ec4b6",
     "A healthy rhythm. Protect it: keep a fixed sleep time and schedule one screen-free hour before bed."),
    (float("-inf"), "💚 Fully Rested & Balanced", "#39ff14",
     "Excellent calendar calibration routine! Your parameters show superb structural equilibrium."),
]


def compute_stress_index(study_h, sleep_h, screen_h, emotion_adj=0.0):
    base = (study_h * 1.2) + (screen_h * 1.0)
    sleep_multiplier = max(1.0, 15.0 / (sleep_h + 1.0))
    return max(0.0, base * sleep_multiplier + emotion_adj), base, sleep_multiplier


def classify_stress(index):
    for threshold, label, color, advice in STRESS_TIERS:
        if index >= threshold:
            return label, color, advice
    return STRESS_TIERS[-1][1:]


# ---- Live in-app Logistic Regression replica (optional) ----------------------
def find_dataset():
    for name in DATASET_CANDIDATES:
        path = os.path.join(APP_DIR, name)
        if os.path.exists(path):
            return path
    return None


@st.cache_resource(show_spinner=False)
def train_live_model(path, mtime):
    """Re-trains the Orange model's twin (scikit-learn Logistic Regression, 5-fold CV) from your dataset file."""
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import StratifiedKFold, cross_validate
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return {"error": "scikit-learn not installed"}
    try:
        frame = pd.read_csv(path) if path.lower().endswith(".csv") else pd.read_excel(path)
    except Exception as exc:
        return {"error": f"could not read dataset ({type(exc).__name__})"}
    norm = {c.lower().replace(" ", "_"): c for c in frame.columns}

    def pick(word):
        return next((orig for low, orig in norm.items() if word in low), None)

    cols = {"study": pick("study"), "sleep": pick("sleep"), "screen": pick("screen"), "target": pick("stress")}
    if None in cols.values():
        return {"error": "dataset needs Study, Sleep, Screen and Stress columns"}
    features = [cols["study"], cols["sleep"], cols["screen"]]
    data = frame[features + [cols["target"]]].dropna()
    X, y = data[features].astype(float), data[cols["target"]].astype(str)
    folds = int(min(5, y.value_counts().min()))
    if folds < 2:
        return {"error": "each stress class needs at least 2 rows"}
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    scores = cross_validate(model, X, y, cv=StratifiedKFold(n_splits=folds, shuffle=True, random_state=42),
                            scoring=["accuracy", "f1_macro"])
    model.fit(X, y)
    return {"model": model, "features": features, "rows": len(data), "folds": folds,
            "accuracy": float(scores["test_accuracy"].mean()), "f1": float(scores["test_f1_macro"].mean())}


def live_model():
    path = find_dataset()
    if not path:
        return None
    return train_live_model(path, os.path.getmtime(path))


# ---- Badges --------------------------------------------------------------------
def valid_checkins(rec):
    return [m for m in rec.get("mood_history_records", []) if isinstance(m, dict) and "stress_index" in m]


def completed_tasks(rec):
    return [t for t in rec.get("tasks", []) if isinstance(t, dict) and t.get("status") == "Completed"]


SOURCE_LABELS = {"checkin": "📊 Check-in", "journal": "✍️ Journal", "task": "✅ Tasks", "breathing": "🧘 Breathing",
                 "memory": "🧩 Memory", "bubble": "🫧 Bubble Pop", "whack": "🔨 Whack-A-Stress", "quiz": "🧠 Quiz",
                 "gratitude": "🌻 Gratitude", "maze": "🚗 Maze", "wordle": "🔤 Daily Word", "other": "⭐ Other"}

BADGES = [
    ("🌱", "First Check-In", "Save your first stress check-in", lambda u: len(valid_checkins(u)) >= 1),
    ("🔥", "3-Day Streak", "Log in 3 days in a row", lambda u: int(u.get("consecutive_days_streak", 0) or 0) >= 3),
    ("🏅", "7-Day Streak", "Log in 7 days in a row", lambda u: int(u.get("consecutive_days_streak", 0) or 0) >= 7),
    ("🎯", "100-Point Day", "Earn 100 Zen Points in one day", lambda u: int(u.get("high_score", 0) or 0) >= DAILY_GOAL_POINTS),
    ("🧘", "Calm Breather", "Finish a 3-cycle box breathing session", lambda u: u["stats"].get("breathing_sessions", 0) >= 1),
    ("🧩", "Memory Master", "Clear the memory board in 12 flips or fewer", lambda u: u["stats"].get("best_memory_pts", 0) >= 22),
    ("🫧", "Bubble Popper", "Earn 15+ points in one Bubble Pop round", lambda u: u["stats"].get("best_bubble_pts", 0) >= 15),
    ("🔨", "Stress Smasher", "Earn 15+ points in Whack-A-Stress", lambda u: u["stats"].get("best_whack_pts", 0) >= 15),
    ("🚗", "Maze Racer", "Earn 20+ points in Maze Runner", lambda u: u["stats"].get("best_maze_pts", 0) >= 20),
    ("🔤", "Word Wizard", "Solve the Daily Word in 3 tries or fewer", lambda u: u["stats"].get("best_wordle", 7) <= 3),
    ("✅", "Task Finisher", "Complete 5 planner tasks", lambda u: len(completed_tasks(u)) >= 5),
    ("✍️", "Reflective Writer", "Write 3 journal entries", lambda u: len(u.get("journal_entries", [])) >= 3),
]

if not st.session_state.get("chat_history_logs"):
    st.session_state.chat_history_logs = [chat_greeting(user_data["name"])]

# ==============================================================================
# 📋 STEP 5: PERMANENT SIDEBAR & SYSTEM CONTROLS
# ==============================================================================
st.sidebar.markdown(f"""
<div style='background: {panel_hex}; padding: 16px; border-radius: 12px; border-left: 5px solid {A1}; margin-bottom: 14px;'>
    <span style='color: {muted_hex}; font-size: 0.8rem; font-weight: bold; letter-spacing:1px;'>⚡ BRAND SECURITY PASS</span><br>
    <span style='color: {text_hex}; font-size: 1.1rem; font-weight: 800;'>🛡️ ProjectMind Guard</span><br>
    <span style='color: {muted_hex}; font-size: 0.85rem;'>Signed in: <b style='color:{text_hex}'>{user_data['name']}</b> · {UID}</span>
</div>
""", unsafe_allow_html=True)

st.sidebar.markdown("### 🎨 Personal Settings")
mode_options = ["Dark Glass", "Light Glass"]
theme_names = list(COLOR_THEMES)
selected_mode = st.sidebar.selectbox("Choose Visual Skin Canvas:", mode_options,
                                     index=mode_options.index(st.session_state.app_appearance_mode))
selected_theme = st.sidebar.selectbox("Calming colour theme:", theme_names,
                                      index=theme_names.index(st.session_state.color_theme))
selected_sound = st.sidebar.toggle("🔊 Sound effects", value=st.session_state.sound_on)
if (selected_mode, selected_theme, selected_sound) != (st.session_state.app_appearance_mode, st.session_state.color_theme,
                                                       st.session_state.sound_on):
    st.session_state.app_appearance_mode = selected_mode
    st.session_state.color_theme = selected_theme
    st.session_state.sound_on = selected_sound
    user_data["saved_theme"], user_data["appearance_mode"], user_data["sound_on"] = selected_theme, selected_mode, selected_sound
    persist_user(UID)  # each student keeps their own look and sound choice
    queue_sound("click")
    st.rerun()

st.sidebar.markdown("### ⏰ Live System Clock")
with st.sidebar:
    components.html(f"""
        <div style="font-family: sans-serif; font-size: 1.3rem; font-weight: bold; color: {title_color}; text-align: center;
             background: rgba({A2_RGB},0.1); padding: 10px; border-radius: 8px; border: 1px solid {A2};">
            <span id="live-clock">00:00:00</span>
        </div>
        <script>
            function updateClock() {{
                const now = new Date();
                document.getElementById('live-clock').innerText =
                    String(now.getHours()).padStart(2, '0') + ":" + String(now.getMinutes()).padStart(2, '0') + ":" + String(now.getSeconds()).padStart(2, '0');
            }}
            setInterval(updateClock, 1000); updateClock();
        </script>
    """, height=60)
st.sidebar.markdown(f"**Today's Date:** {now_local().strftime('%B %d, %Y')}")

st.sidebar.markdown("### 🧭 Quick Navigation")
NAV = [("Home", "🏠 Home Hub"), ("Diagnostics", "📊 Stress Diagnostics"), ("Eisenhower", "🗺️ Priority Planner"),
       ("Counselor", "💬 AI Counselor"), ("Arcade", "🕹️ Zen Arcade"), ("Profile", "👤 My Profile")]
for page_key, page_label in NAV:
    if wide_button(page_label, key=f"nav_{page_key}", where=st.sidebar,
                   disabled=st.session_state.current_active_tab == page_key):
        st.session_state.current_active_tab = page_key
        queue_sound("click")
        st.rerun()

st.sidebar.caption("🤖 Counselor: " + ("online AI available" if (GENAI_INSTALLED and gemini_key()) else "offline mode"))

st.sidebar.caption(f"Storage: {STORE.label}")
if STORE_NOTE:
    st.sidebar.caption(STORE_NOTE)

st.sidebar.markdown("### 🌍 Global SDG Targets")
st.sidebar.markdown("- **Goal 3:** Good Health & Well-being\n- **Goal 4:** Quality Education\n- **Goal 10:** Reduced Inequalities")

st.sidebar.markdown("---")
if wide_button("🚪 Terminate Current Session", key="logout", where=st.sidebar):
    keep_theme = st.session_state.app_appearance_mode
    for k in list(st.session_state.keys()):
        del st.session_state[k]  # wipe chat, API key and codes so the next student on this device starts clean
    st.session_state.app_appearance_mode = keep_theme
    st.rerun()


def back_home_button():
    if st.button("⬅️ Return to Main Home Hub"):
        st.session_state.current_active_tab = "Home"
        queue_sound("click")
        st.rerun()


def page_title(first, second, first_color=None, second_color=None):
    first_color, second_color = first_color or A1, second_color or A2
    st.markdown(f"<h1 class='main-logo-text'><span style='color:{first_color};'>{first}</span>"
                f"<span style='color:{second_color};'> {second}</span></h1>", unsafe_allow_html=True)
    st.markdown("---")


def plot_layout(fig, height, title=None):
    fig.update_layout(template=PLOT_TEMPLATE, height=height, title=title, margin=dict(l=10, r=10, t=45 if title else 10, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", y=-0.2), font=dict(color=text_hex))
    return fig


ACTIVE = st.session_state.current_active_tab

# ==============================================================================
# 🏠 STEP 6: DYNAMIC LANDING HUB (THE MAIN HOME PAGE)
# ==============================================================================
if ACTIVE == "Home":
    st.markdown("<h1 class='main-logo-text'><span class='logo-shimmer'>MindPulse</span> Hub</h1>", unsafe_allow_html=True)
    st.markdown("<p class='motto-text'>Predicting Strain, Protecting Minds</p>", unsafe_allow_html=True)

    hour = now_local().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    st.markdown(f"### {greeting}, {user_data['name']} 👋")
    if str(user_data.get("name", "")).strip().upper() == UID.upper():
        with card("name_fix"):
            st.markdown("👋 **Your display name is still your School ID.** Add your real name so MindPulse greets you properly.")
            with st.form("quick_name_form", clear_on_submit=True):
                quick_name = st.text_input("Your full name")
                if st.form_submit_button("Save my name", **full_width(st.form_submit_button)):
                    clean, err = validate_name(quick_name, UID)
                    if err:
                        st.error(err)
                    else:
                        user_data["name"] = clean
                        persist_user(UID)
                        flash(f"Nice to meet you, {clean}!", "👋")
                        st.rerun()

    checkins = valid_checkins(user_data)
    pts_today = today_points(user_data)
    k1, k2, k3, k4 = st.columns(4)
    tiles = [
        (k1, f"<span class='flame'>🔥</span> {user_data.get('consecutive_days_streak', 1)}", "Day Streak", "#ffb703"),
        (k2, f"{pts_today}<span style='font-size:1rem;opacity:.7'> / {DAILY_GOAL_POINTS}</span>", "Zen Points Today", A1),
        (k3, f"🏆 {user_data.get('high_score', 0)}", "Personal Best", "#39ff14"),
        (k4, f"{checkins[-1]['tier'].split(' ')[0] if checkins else '—'} {len(checkins)}", "Stress Check-ins", A2),
    ]
    for col, value, label, color in tiles:
        col.markdown(f"<div class='kpi-tile'><div class='kpi-value' style='color:{color}'>{value}</div>"
                     f"<div class='kpi-label'>{label}</div></div>", unsafe_allow_html=True)
    st.write("")

    col_dash_left, col_dash_right = st.columns([1.5, 1])

    with col_dash_left:
        with card("thought"):
            st.markdown(f"<h4 style='margin-top:0; color:{title_color};'>📅 Thought of the Day</h4>", unsafe_allow_html=True)
            quote = thought_of_the_day()
            st.markdown(f"<p class='quote-text'>“{quote['q']}”</p><p style='text-align:right; font-weight:700;'>— {quote['a']}</p>",
                        unsafe_allow_html=True)
            if quote["live"]:
                st.caption("🌐 Inspirational quotes provided by [ZenQuotes API](https://zenquotes.io/)")
            else:
                st.caption("📴 Offline mode — quote from the built-in MindPulse wellness library")

        st.markdown("### 🎛️ Program Control Interfaces")
        with card("controls"):
            c1, c2 = st.columns(2)
            nav_tiles = [(c1, "📊 Stress Diagnostics & Analytics Hub", "Diagnostics"),
                         (c2, "🗺️ Eisenhower Task Priority Matrix Planner", "Eisenhower"),
                         (c1, "💬 Conversational Chat AI Counselor Deck", "Counselor"),
                         (c2, "🕹️ ASMR Zen Arcade & Health Challenges", "Arcade")]
            for col, label, target in nav_tiles:
                with col:
                    if wide_button(label, key=f"tile_{target}"):
                        st.session_state.current_active_tab = target
                        queue_sound("click")
                        st.rerun()

        with card("trend"):
            st.markdown(f"<h4 style='margin-top:0; color:{title_color};'>📈 Stress & Wellness Trend</h4>", unsafe_allow_html=True)
            if not checkins:
                st.info("No check-ins yet. Open **Stress Diagnostics**, run a scan and press **Save Check-in** — your trend line appears here.")
            elif not PLOTLY_OK:
                st.line_chart(pd.DataFrame({"Stress Index": [c["stress_index"] for c in checkins[-30:]]}))
            else:
                recent = checkins[-30:]
                times = [c.get("timestamp", "") for c in recent]
                fig = go.Figure()
                bands = [(0, 15, "#39ff14"), (15, 25, "#2ec4b6"), (25, 40, "#00b4d8"), (40, 55, "#ffb703"), (55, 100, "#ff4a4a")]
                for low, high, color in bands:
                    fig.add_hrect(y0=low, y1=high, fillcolor=color, opacity=0.07, line_width=0)
                fig.add_trace(go.Scatter(x=times, y=[min(100, c["stress_index"]) for c in recent], mode="lines+markers",
                                         name="Stress Index", line=dict(color="#ff4a4a", width=3, shape="spline"),
                                         marker=dict(size=8), text=[c.get("tier", "") for c in recent],
                                         hovertemplate="%{x}<br>Index %{y:.1f}<br>%{text}<extra></extra>"))
                fig.add_trace(go.Scatter(x=times, y=[c.get("sleep_hours", 0) * 10 for c in recent], mode="lines",
                                         name="Sleep (h × 10)", line=dict(color=A1, width=2, dash="dot")))
                plot_layout(fig, 320)
                fig.update_yaxes(range=[0, 100], title="Stress Index")
                st.plotly_chart(fig, **full_width(st.plotly_chart))

            log = user_data.get("points_log", {})
            if log and PLOTLY_OK:
                days = sorted(log)[-14:]
                bar = go.Figure(go.Bar(x=days, y=[log[d] for d in days], name="Zen Points",
                                       marker_color=["#39ff14" if log[d] >= DAILY_GOAL_POINTS else A2 for d in days]))
                bar.add_hline(y=DAILY_GOAL_POINTS, line_dash="dash", line_color="#ffb703", annotation_text="Daily goal")
                st.plotly_chart(plot_layout(bar, 230, "Zen Points — last 14 days"), **full_width(st.plotly_chart))

    with col_dash_right:
        with card("badges"):
            unlocked = sum(1 for b in BADGES if b[3](user_data))
            st.markdown(f"<h4 style='margin-top:0; color:{title_color};'>🎖️ Wellness Badges · {unlocked}/{len(BADGES)}</h4>", unsafe_allow_html=True)
            badge_html = "".join(
                f"<div class='badge {'on' if rule(user_data) else 'off'}'><div class='badge-icon'>{icon if rule(user_data) else '🔒'}</div>"
                f"<div class='badge-name'>{name}</div><div class='badge-desc'>{desc}</div></div>"
                for icon, name, desc, rule in BADGES)
            st.markdown(f"<div class='badge-grid'>{badge_html}</div>", unsafe_allow_html=True)

        with card("milestones"):
            st.markdown(f"<h4 style='color:{title_color}; margin-top:0;'>🏆 Daily Progress</h4>", unsafe_allow_html=True)
            st.progress(min(1.0, pts_today / DAILY_GOAL_POINTS))
            remaining = max(0, DAILY_GOAL_POINTS - pts_today)
            st.markdown(f"🌟 **All-Time Personal Best:** {user_data.get('high_score', 0)} Zen Points  \n"
                        f"📊 **Today:** {pts_today} points" + (f" · {remaining} to go" if remaining else " · goal reached 🎉"))
            today_detail = user_data.get("points_detail", {}).get(today_str(), {})
            if today_detail:
                st.markdown("".join(f"<span class='pill'>{SOURCE_LABELS.get(k, k)} +{v}</span>"
                                    for k, v in sorted(today_detail.items(), key=lambda kv: -kv[1])), unsafe_allow_html=True)
            st.caption("Points depend on how well you play, and each activity pays out a limited number of times a day. "
                       "See the full list in the 🕹️ Zen Arcade.")

        with card("leaderboard"):
            st.markdown(f"<h4 style='color:{title_color}; margin-top:0;'>🏅 Today's Wellness Leaderboard</h4>", unsafe_allow_html=True)
            board = sorted(((today_points(r), int(r.get("high_score", 0) or 0), short_name(r, u), u == UID)
                            for u, r in db["users"].items() if isinstance(r, dict)), key=lambda x: (x[0], x[1]), reverse=True)
            board = [row for row in board if row[0] > 0][:5]
            if not board:
                st.caption("Nobody has earned points today yet — be the first!")
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            for i, (pts_b, best_b, nm, me) in enumerate(board):
                style = "font-weight:800;color:#39ff14;" if me else ""
                st.markdown(f"<div style='display:flex;justify-content:space-between;{style}'><span>{medals[i]} {nm}{' (you)' if me else ''}</span>"
                            f"<span>{pts_b} pts</span></div>", unsafe_allow_html=True)

        with card("model"):
            st.markdown("<h4 style='color:#ffb703; margin-top:0;'>🧠 Model Card — Orange Data Mining</h4>", unsafe_allow_html=True)
            st.markdown("""
| Item | Detail |
|---|---|
| Algorithm | Logistic Regression (multiclass) |
| Data | 200 synthetic student profiles |
| Inputs | Study hours · Sleep hours · Screen time |
| Output | 5 stress tiers |
| Validation | 5-fold cross-validation |
| Accuracy (CA) | **90.00%** |
| F1 (macro) | **90.12%** |
| AUC | **0.970** |
""")
            with st.expander("How does the model decide?"):
                st.markdown(
                    "- Logistic Regression learns one **weight per input** for each stress class, adds them up, and "
                    "turns the totals into probabilities with the *softmax* function. The class with the highest probability wins.\n"
                    "- Long study hours, long screen time and short sleep push the totals toward the stressed tiers; "
                    "healthy sleep pushes them back toward the balanced tiers.\n"
                    "- **5-fold cross-validation** split the 200 profiles into 5 parts; the model trained on 4 and was tested on "
                    "the unseen 5th, five times. The 90% is the average on unseen data, so it is not just memorised.\n"
                    "- We chose it over the 4 other models compared in Orange (Tree, Random Forest, kNN, Naive Bayes) "
                    "because it scored strongly and stays simple enough to explain.\n"
                    "- The Diagnostics page uses a transparent stress-index formula on the same three inputs, plus the "
                    "camera's emotion signal. If the dataset file sits next to the app, the trained Logistic Regression "
                    "also runs live as a second opinion.")
            lm = live_model()
            if lm and "model" in lm:
                st.success(f"🔁 Live replica re-trained in-app on {lm['rows']} rows: "
                           f"accuracy {lm['accuracy']*100:.1f}% · F1 {lm['f1']*100:.1f}% ({lm['folds']}-fold CV)")

# ==============================================================================
# 📊 STEP 7: MULTIMODAL DIAGNOSTICS & REFLECTIVE JOURNAL
# ==============================================================================
elif ACTIVE == "Diagnostics":
    back_home_button()
    page_title("Stress", "Diagnostics")

    diag_col1, diag_col2 = st.columns([1, 1.2])

    with diag_col1:
        with card("sliders"):
            st.markdown(f"<h3 style='margin-top:0; color:{title_color};'>⚙️ 24-Hour Parameter Constraints</h3>", unsafe_allow_html=True)
            study_h = st.slider("Daily Study Evaluation Hours", 0.0, 16.0, 8.0, 0.5)
            remaining_cap = max(0.0, 24.0 - study_h)
            sleep_cap = min(12.0, remaining_cap)
            sleep_h = st.slider("Daily Sleep Recovery Hours", 0.0, sleep_cap, min(7.0, sleep_cap), 0.5)
            screen_cap = min(14.0, max(0.0, 24.0 - study_h - sleep_h))
            if screen_cap > 0:
                screen_h = st.slider("Daily Screen Interactive Hours", 0.0, screen_cap, min(5.0, screen_cap), 0.5)
            else:
                screen_h = 0.0
                st.caption("Daily Screen Interactive Hours: 0 — no hours left in the day.")
            total_logged_day = study_h + sleep_h + screen_h
            st.markdown(f"Combined Parameter Allocation: **{total_logged_day:.1f} / 24.0 Hours**")
            st.progress(min(1.0, total_logged_day / 24.0))

        with card("camera"):
            st.markdown(f"<h3 style='margin-top:0; color:{title_color};'>📷 Facial Emotion Scanner</h3>", unsafe_allow_html=True)
            engine_name = available_cv_engine()
            st.caption(f"Engine: **{engine_name or 'none installed'}** · photos are analysed in memory and never saved.")
            cam_enabled = st.toggle("Enable camera emotion scan (optional)", key="cam_enabled")
            emotion_result = None
            if cam_enabled:
                cam_feed_frame = st.camera_input("Take a quick snapshot — look at the camera naturally")
                if cam_feed_frame is not None:
                    with st.spinner("Analysing facial expression… (first scan downloads the model, please wait)"):
                        emotion_result = analyze_emotion(cam_feed_frame.getvalue())
                    if emotion_result.get("engine") is None:
                        st.warning(f"Emotion engine unavailable ({emotion_result.get('error')}). "
                                   "Install `deepface` to enable scanning. Using lifestyle data only.")
                        emotion_result = None
                    elif not emotion_result["face_found"]:
                        st.warning("No face detected — try better lighting and face the camera. Using lifestyle data only.")
                        emotion_result = None
                    else:
                        dom = emotion_result["dominant"]
                        st.success(f"🧬 {emotion_result['engine']} detected: **{EMOTION_EMOJI.get(dom, '')} {dom.title()}**")
                        ranked = sorted(emotion_result["emotions"].items(), key=lambda kv: kv[1], reverse=True)[:5]
                        for name, pct in ranked:
                            st.progress(min(1.0, pct / 100.0), text=f"{EMOTION_EMOJI.get(name, '')} {name.title()} — {pct:.1f}%")

    with diag_col2:
        emotion_adj = emotion_stress_adjustment(emotion_result["emotions"]) if emotion_result else 0.0
        stress_index, base_load, sleep_mult = compute_stress_index(study_h, sleep_h, screen_h, emotion_adj)
        result_badge, result_color, advice_str = classify_stress(stress_index)

        st.markdown("### Structured Holistic Action Blueprint:")
        st.markdown(f"""<div class='result-card' style='border-left:6px solid {result_color};'>
            <h2 style='margin:0; color:{result_color};'>{result_badge}</h2>
            <p style='margin-top:10px; font-size:1.05rem;'>{advice_str}</p></div>""", unsafe_allow_html=True)

        if PLOTLY_OK:
            gauge = go.Figure(go.Indicator(
                mode="gauge+number", value=min(100.0, stress_index), number={"suffix": " / 100", "valueformat": ".1f"},
                title={"text": "MindPulse Stress Index"},
                gauge={"axis": {"range": [0, 100]}, "bar": {"color": result_color, "thickness": 0.3},
                       "steps": [{"range": [0, 15], "color": "rgba(57,255,20,0.25)"}, {"range": [15, 25], "color": "rgba(46,196,182,0.25)"},
                                 {"range": [25, 40], "color": "rgba(0,180,216,0.25)"}, {"range": [40, 55], "color": "rgba(255,183,3,0.25)"},
                                 {"range": [55, 100], "color": "rgba(255,74,74,0.25)"}]}))
            st.plotly_chart(plot_layout(gauge, 250), **full_width(st.plotly_chart))
        st.markdown(f"<span class='pill'>Lifestyle load {base_load:.1f}</span>"
                    f"<span class='pill'>Sleep multiplier ×{sleep_mult:.2f}</span>"
                    f"<span class='pill'>Emotion adjustment {emotion_adj:+.1f}</span>", unsafe_allow_html=True)

        lm = live_model()
        if lm and "model" in lm:
            sample = pd.DataFrame([[study_h, sleep_h, screen_h]], columns=lm["features"])
            probs = lm["model"].predict_proba(sample)[0]
            best = int(probs.argmax())
            st.info(f"🤖 Live Logistic Regression second opinion: **{lm['model'].classes_[best]}** "
                    f"({probs[best]*100:.0f}% confidence)")

        already_today = any(c.get("date") == today_str() for c in valid_checkins(user_data))
        if wide_button("💾 Save this Check-in to my Trend Chart", key="save_checkin"):
            user_data["mood_history_records"].append({
                "timestamp": now_local().strftime("%Y-%m-%d %H:%M"), "date": today_str(),
                "study_hours": study_h, "sleep_hours": sleep_h, "screen_hours": screen_h,
                "emotion": emotion_result["dominant"] if emotion_result else None,
                "emotion_engine": emotion_result["engine"] if emotion_result else None,
                "stress_index": round(stress_index, 2), "tier": result_badge,
            })
            persist_user(UID)
            if not already_today:
                award_points(UID, 10, "daily check-in", "checkin")
            else:
                flash("Check-in saved to your trend chart.", "💾")
            st.rerun()

        with card("vetting"):
            st.markdown("<h4 style='color:#ffb703; margin-top:0;'>📊 AI Model Vetting Records (Orange Data Mining Validation)</h4>", unsafe_allow_html=True)
            st.markdown("""
- **Classification Algorithm:** Logistic Regression
- **Training Set:** 200 synthetic student profiles · 5-fold cross-validation
- **Accuracy:** **90.00%** · **F1-Macro:** **90.12%** · **AUC:** **0.970**
- **Camera signal:** emotion probabilities weighted (fear +20, anger +18, sadness +15, happiness −10)
""")
            if lm and "error" in lm:
                st.caption(f"Live replica not active: {lm['error']}.")
            elif not lm:
                st.caption("Tip: place `student_stress_data.csv` (or .xlsx) next to this app to re-train the model live inside the app.")

        with card("journal"):
            st.markdown(f"<h3 style='margin-top:0; color:{A2};'>✍️ Reflective Mental Journal Log</h3>", unsafe_allow_html=True)
            with st.form("journal_form", clear_on_submit=True):
                journal_text = st.text_area("Record today's mental notes, concerns, or emotional benchmarks:")
                if st.form_submit_button("Commit Log to Journal", **full_width(st.form_submit_button)):
                    if len(journal_text.strip()) >= 10:
                        first_today = not any(isinstance(e, dict) and str(e.get("time", "")).startswith(today_str())
                                              for e in user_data["journal_entries"])
                        user_data["journal_entries"].append({"time": now_local().strftime("%Y-%m-%d %H:%M"), "text": journal_text.strip()})
                        if first_today:
                            award_points(UID, 5, "journal entry", "journal")
                        else:
                            persist_user(UID)
                            flash("Journal entry saved privately.", "📓")
                        st.rerun()
                    elif journal_text.strip():
                        st.error("Write at least a sentence (10+ characters).")
                    else:
                        st.error("Journal entries cannot be empty.")
            entries = user_data["journal_entries"][-3:]
            if entries:
                with st.expander(f"📖 My recent entries ({len(user_data['journal_entries'])} total — only you can see these)"):
                    for e in reversed(entries):
                        if isinstance(e, dict):
                            st.markdown(f"**{e.get('time', '')}** — {e.get('text', '')}")

# ==============================================================================
# 💬 STEP 8: LIVE CHAT ENGINE — GEMINI COUNSELOR WITH OFFLINE FALLBACK
# ==============================================================================
elif ACTIVE == "Counselor":
    back_home_button()
    st.markdown(f"<h1 class='main-logo-text'><span style='color:{A1};'>Mind</span><span style='color:{A3};'>Pulse Chat Deck</span></h1>", unsafe_allow_html=True)
    st.markdown("---")

    online_ready = GENAI_INSTALLED and bool(gemini_key())
    status_l, status_r = st.columns([3, 2])
    with status_r:
        if online_ready:
            st.session_state.gemini_consent = st.toggle(
                "Use online Gemini AI", value=st.session_state.gemini_consent,
                help="When ON, your chat messages are sent to Google Gemini to generate replies. Nothing else is shared.")
        else:
            st.caption("Online AI isn't set up on this computer yet. A teacher can add a free Gemini key in the 🧑‍🏫 Examiner Portal.")
    use_gemini = online_ready and st.session_state.gemini_consent
    with status_l:
        if use_gemini:
            st.markdown("<span class='pill' style='border-color:#39ff14'>🟢 Online · Google Gemini conversational AI</span>", unsafe_allow_html=True)
        else:
            st.markdown("<span class='pill' style='border-color:#ffb703'>🟡 Offline · local keyword NLP engine</span>", unsafe_allow_html=True)

    with card("chat"):
        st.markdown("##### 📜 Conversation")
        for dialogue_turn in st.session_state.chat_history_logs:
            with st.chat_message(dialogue_turn["role"]):
                st.markdown(dialogue_turn["message"])

        st.markdown("---")
        st.markdown(f"<p style='color:{muted_hex}; font-size:0.9rem; margin-bottom:5px;'>⚡ Quick Access Queries:</p>", unsafe_allow_html=True)
        q_col1, q_col2 = st.columns(2)
        triggered_preset_text = None
        with q_col1:
            if wide_button("😫 I have a sudden panic attack before my exams!", key="pq1"):
                triggered_preset_text = "I am having a sudden panic attack before my exam starts, help me calm down!"
            if wide_button("📉 I scored poorly on a mock paper and feel demotivated.", key="pq2"):
                triggered_preset_text = "I just scored poorly on a mock paper and feel completely demotivated."
        with q_col2:
            if wide_button("📋 How do I structure a realistic board exam revision timetable?", key="pq3"):
                triggered_preset_text = "How do I structure a realistic revision timetable for the upcoming CBSE board exams?"
            if wide_button("🧠 My head hurts from studying for 6 hours straight...", key="pq4"):
                triggered_preset_text = "My head hurts from studying for 6 hours straight, how do I reset my mental clarity?"
        if len(st.session_state.chat_history_logs) > 1 and st.button("🧹 Clear conversation"):
            st.session_state.chat_history_logs = [chat_greeting(user_data["name"])]
            st.rerun()

    st.caption("MindPulse offers study and wellbeing support, not medical advice. In the UAE, the Mental Support Line is "
               "800 4673 (800 HOPE, call or WhatsApp). Emergency: 999 / 998.")

    student_user_text = st.chat_input("Or type your own message here...")
    active_chat_payload = student_user_text or triggered_preset_text

    if active_chat_payload:
        st.session_state.chat_history_logs.append({"role": "user", "message": active_chat_payload})
        lowered = active_chat_payload.lower()
        if any(term in lowered for term in CRISIS_TERMS):
            reply = CRISIS_REPLY  # safety first: a fixed, checked message, never left to chance
        elif use_gemini:
            with st.spinner("MindPulse is thinking…"):
                reply, error = ask_gemini(st.session_state.chat_history_logs, user_data["name"])
            if reply is None:
                reply = offline_counselor_reply(active_chat_payload, user_data["name"]) + "\n\n_(Online AI unreachable, so the offline engine answered.)_"
        else:
            reply = offline_counselor_reply(active_chat_payload, user_data["name"])
        st.session_state.chat_history_logs.append({"role": "assistant", "message": reply})
        st.rerun()

# ==============================================================================
# 🗺️ STEP 9: INTERACTIVE EISENHOWER TASK PLANNER WITH GRAPHICAL LEDGER
# ==============================================================================
elif ACTIVE == "Eisenhower":
    back_home_button()
    page_title("Eisenhower", "Priority Planner", A2, A1)

    QUADRANTS = [
        ("Q1", "🔴 Q1: Urgent & Important", "🔴 URGENT & IMPORTANT", "#ff4a4a", 15),
        ("Q2", "🔵 Q2: Important & Not Urgent", "🔵 IMPORTANT & NOT URGENT", "#3a86ff", 15),
        ("Q3", "🟡 Q3: Urgent & Not Important", "🟡 URGENT & NOT IMPORTANT", "#ffb703", 10),
        ("Q4", "🟢 Q4: Not Urgent & Not Important", "🟢 NOT URGENT & NOT IMPORTANT", "#39ff14", 5),
    ]
    tasks = user_data["tasks"]
    col_input, col_matrix = st.columns([1, 1.4])

    with col_input:
        with card("task_input"):
            st.markdown(f"<h4 style='color:{A2}; margin-top:0;'>📝 Log Task Metadata</h4>", unsafe_allow_html=True)
            with st.form("task_form", clear_on_submit=True):
                task_title = st.text_input("Assignment Description Title:")
                task_quadrant = st.selectbox("Assign Priority Classification Matrix:", [q[1] for q in QUADRANTS])
                task_deadline = st.date_input("Target Submission Deadline:", value=now_local().date())
                if st.form_submit_button("Inject Task into Matrix Grid", **full_width(st.form_submit_button)):
                    if task_title.strip():
                        used_ids = {t.get("id") for t in tasks if isinstance(t, dict)}
                        new_id = random.randint(10000, 99999)
                        while new_id in used_ids:
                            new_id = random.randint(10000, 99999)
                        tasks.append({"id": new_id, "title": task_title.strip(), "quadrant": task_quadrant,
                                      "deadline": str(task_deadline), "status": "Pending", "submitted_at": ""})
                        persist_user(UID)
                        flash("Task routed into its priority quadrant!", "🗺️")
                        st.rerun()
                    else:
                        st.error("Please enter a task description.")

        done_count = len(completed_tasks(user_data))
        pending_count = sum(1 for t in tasks if isinstance(t, dict) and t.get("status") == "Pending")
        if PLOTLY_OK and (done_count or pending_count):
            donut = go.Figure(go.Pie(labels=["Completed", "Pending"], values=[done_count, pending_count], hole=0.6,
                                     marker=dict(colors=["#39ff14", "#ff4a4a"])))
            st.plotly_chart(plot_layout(donut, 240, "Task Completion"), **full_width(st.plotly_chart))

    with col_matrix:
        pending_tasks = [t for t in tasks if isinstance(t, dict) and t.get("status") == "Pending"]
        if not pending_tasks:
            st.markdown("<div style='text-align:center; padding:50px; background: rgba(57,255,20,0.05); border-radius:12px; border:2px dashed #39ff14;'>"
                        "<h2 style='color:#39ff14;'>🎉 Yay! All clear. No pending tasks right now!</h2></div>", unsafe_allow_html=True)
        else:
            def checkout_task(task_id, points_gained):
                for t in tasks:
                    if isinstance(t, dict) and t.get("id") == task_id:
                        t["status"] = "Completed"
                        t["submitted_at"] = now_local().strftime("%Y-%m-%d %H:%M:%S")
                        break
                if plays_today(user_data, "task") < TASK_REWARD_CAP:
                    log_play(user_data, "task")
                    award_points(UID, points_gained, "task completed", "task")
                else:
                    persist_user(UID)
                    flash(f"Task completed! (Points are given for the first {TASK_REWARD_CAP} tasks each day.)", "✅")
                st.rerun()

            st.caption(f"Points are awarded for your first {TASK_REWARD_CAP} completed tasks each day "
                       f"({plays_today(user_data, 'task')}/{TASK_REWARD_CAP} used today).")

            grid = st.columns(2) + st.columns(2)
            for (code, _, heading, color, points), cell in zip(QUADRANTS, grid):
                with cell:
                    with card(f"quad_{code}"):
                        st.markdown(f"<span style='color:{color}; font-weight:bold;'>{heading}</span> "
                                    f"<span class='pill'>+{points} pts</span>", unsafe_allow_html=True)
                        items = [t for t in pending_tasks if code in str(t.get("quadrant", ""))]
                        if not items:
                            st.caption("Nothing here.")
                        for item in items:
                            overdue = str(item.get("deadline", "9999")) < today_str()
                            st.markdown(f"▪️ **{item.get('title', 'Untitled')}** (Due: {item.get('deadline', '—')})"
                                        + (" <span style='color:#ff4a4a;font-weight:700'>⚠️ Overdue</span>" if overdue else ""),
                                        unsafe_allow_html=True)
                            b_done, b_del = st.columns([3, 1])
                            with b_done:
                                if wide_button("Complete & Checkout", key=f"btn_{item['id']}"):
                                    checkout_task(item["id"], points)
                            with b_del:
                                if wide_button("🗑️", key=f"del_{item['id']}", help="Delete this task (no points)"):
                                    user_data["tasks"] = [t for t in tasks if not (isinstance(t, dict) and t.get("id") == item["id"])]
                                    persist_user(UID)
                                    flash("Task deleted.", "🗑️")
                                    st.rerun()

    st.markdown("### 📊 Excel-Style Completed Archive Ledger")
    done = completed_tasks(user_data)
    if done:
        ledger = pd.DataFrame([{"Task Description": t.get("title", ""), "Priority Band": t.get("quadrant", ""),
                                "Target Deadline": t.get("deadline", ""), "Submission Timestamp": t.get("submitted_at", "")}
                               for t in done])
        st.dataframe(ledger, hide_index=True, **full_width(st.dataframe))
    else:
        st.caption("No completed tasks archived yet.")

# ==============================================================================
# 🕹️ STEP 10: ZEN ARCADE — 6 ACTIVITIES, SKILL-BASED & DAILY-CAPPED POINTS
# ==============================================================================
elif ACTIVE == "Arcade":
    back_home_button()
    page_title("Zen", "Arcade Node")

    # Games report a win straight back to Python through the game bridge, so points are added instantly.
    # Python re-checks every win (points within the game's maximum, daily limit, one award per win token).
    JS_CODE_HELPER = """
  var SOUND_ON = __SOUND__, CAPPED = __CAPPED__;
  function reportWin(p) {
    try { parent.postMessage({mindpulse: "win", points: p, token: Date.now() + "-" + Math.random().toString(36).slice(2)}, "*"); } catch (e) {}
  }
  function winText(p) {
    return CAPPED ? "Great round! You've already collected today's points for this game, so this one was just for fun."
                  : "<b>+" + p + " Zen Points</b> added to your score!";
  }
  function fxSound(notes) {
    if (!SOUND_ON) return;
    try {
      var ctx = window.__fxctx = window.__fxctx || new (window.AudioContext || window.webkitAudioContext)(); ctx.resume();
      notes.forEach(function (n) {
        var o = ctx.createOscillator(), g = ctx.createGain(), t = ctx.currentTime + n[1];
        o.type = n[3] || "sine"; o.frequency.setValueAtTime(n[0], t);
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.16, t + 0.01);
        g.gain.exponentialRampToValueAtTime(0.0001, t + n[2]);
        o.connect(g); g.connect(ctx.destination); o.start(t); o.stop(t + n[2] + 0.02);
      });
    } catch (e) {}
  }
  function tick() { fxSound([[950, 0, 0.05, "triangle"]]); }
  function celebrate() {
    fxSound([[523, 0, 0.16, "triangle"], [659, 0.13, 0.16, "triangle"], [784, 0.26, 0.16, "triangle"], [1047, 0.39, 0.55, "sine"]]);
    var cv = document.createElement("canvas"); cv.width = window.innerWidth; cv.height = window.innerHeight;
    cv.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:9999;";
    document.body.appendChild(cv);
    var c = cv.getContext("2d"), cols = ["__A1__", "__A2__", "__A3__", "#ffb703", "#39ff14", "#ff4d6d"], parts = [], frames = 0;
    for (var i = 0; i < 120; i++) {
      parts.push({x: cv.width / 2, y: cv.height * 0.6, vx: (Math.random() - 0.5) * 12, vy: -Math.random() * 11 - 4,
                  s: 4 + Math.random() * 5, r: Math.random() * 6, col: cols[i % cols.length]});
    }
    (function frame() {
      c.clearRect(0, 0, cv.width, cv.height);
      parts.forEach(function (p) {
        p.vy += 0.35; p.x += p.vx; p.y += p.vy; p.r += 0.2;
        c.save(); c.translate(p.x, p.y); c.rotate(p.r); c.fillStyle = p.col; c.fillRect(-p.s / 2, -p.s / 2, p.s, p.s * 0.6); c.restore();
      });
      if (++frames < 110) requestAnimationFrame(frame); else cv.remove();
    })();
  }
"""
    BTN_STYLE = ("padding:8px 16px;border-radius:10px;border:1px solid __A1__;background:rgba(__A1RGB__,.2);"
                 "color:__TEXT__;font-weight:700;cursor:pointer;")
    DONE_STYLE = ("display:none;margin-top:12px;padding:10px;border-radius:10px;border:1px dashed #39ff14;"
                  "color:#39ff14;font-weight:700;")

    GAMES = {
        "breathing": {"title": "Box Breathing", "max": 15, "stat": "breathing_sessions", "best": None, "reason": "box breathing complete"},
        "memory": {"title": "Memory Matrix", "max": 30, "stat": "memory_wins", "best": "best_memory_pts", "reason": "memory board cleared"},
        "bubble": {"title": "Bubble Pop", "max": 25, "stat": "bubble_rounds", "best": "best_bubble_pts", "reason": "bubble pop round"},
        "whack": {"title": "Whack-A-Stress", "max": 25, "stat": "whack_rounds", "best": "best_whack_pts", "reason": "whack-a-stress round"},
        "maze": {"title": "Maze Runner", "max": 25, "stat": "maze_rounds", "best": "best_maze_pts", "reason": "maze finished"},
    }

    def fill(template, game):
        capped = plays_today(user_data, game) >= GAME_DAILY_CAP
        out = template.replace("__HELPER__", JS_CODE_HELPER).replace("__CAPPED__", "true" if capped else "false")
        out = out.replace("__BTN__", BTN_STYLE).replace("__DONE__", DONE_STYLE)
        out = (out.replace("__A1RGB__", A1_RGB).replace("__A2RGB__", A2_RGB).replace("__A3RGB__", A3_RGB)
                  .replace("__A1__", A1).replace("__A2__", A2).replace("__A3__", A3)
                  .replace("__SOUND__", "true" if st.session_state.sound_on else "false"))
        return (out.replace("__TEXT__", text_hex).replace("__MUTED__", muted_hex)
                .replace("__CARD_OPEN__", "#334155" if DARK else "#cbd5e1").replace("__CARD__", "#1e293b" if DARK else "#e2e8f0"))

    def play_game(game, template, height):
        """Show a game; when it reports a win, check it and add the points straight away."""
        cfg = GAMES[game]
        html = fill(template, game)
        bridge = game_component()
        result = bridge(html=html, height=height, key=f"game_{game}", default=None) if bridge else None
        if bridge is None:
            components.html(html, height=height)
        used = plays_today(user_data, game)
        best = user_data["stats"].get(cfg["best"], 0) if cfg["best"] else 0
        st.caption(f"Points pay out for {GAME_DAILY_CAP} wins a day: **{min(used, GAME_DAILY_CAP)}/{GAME_DAILY_CAP} used**"
                   + (f" · Personal best: **{best} pts**" if best else "")
                   + (" · Today's points collected. Keep playing for fun!" if used >= GAME_DAILY_CAP else ""))
        seen = st.session_state.setdefault("_game_tokens", [])
        if not (isinstance(result, dict) and result.get("token")) or result["token"] in seen:
            return
        seen.append(result["token"])  # each win is counted once, even though the page reloads
        try:
            pts = int(result.get("points", 0))
        except (TypeError, ValueError):
            return
        if used >= GAME_DAILY_CAP or not 0 < pts <= cfg["max"]:
            return
        stats = user_data["stats"]
        stats[cfg["stat"]] = stats.get(cfg["stat"], 0) + 1
        if cfg["best"]:
            stats[cfg["best"]] = max(stats.get(cfg["best"], 0), pts)
        log_play(user_data, game)
        award_points(UID, pts, cfg["reason"], game, celebrate=True)
        st.rerun()

    BREATHING_HTML = """
<div style="font-family:'Segoe UI',system-ui,sans-serif;text-align:center;color:__TEXT__;">
  <div id="cyc" style="font-weight:700;color:__A2__;letter-spacing:1px;">CYCLE 0 / 3</div>
  <div style="height:210px;display:flex;align-items:center;justify-content:center;">
    <div id="ring" style="width:120px;height:120px;border-radius:50%;border:4px solid __A2__;
         background:radial-gradient(circle, rgba(__A1RGB__,0.35), rgba(__A2RGB__,0.08));
         display:flex;flex-direction:column;align-items:center;justify-content:center;
         transform:scale(1);transition:transform 4s ease-in-out, border-color .6s, box-shadow .6s;">
      <div id="phase" style="font-weight:800;font-size:1rem;">READY</div>
      <div id="count" style="font-family:monospace;font-size:1.8rem;font-weight:800;">4</div>
    </div>
  </div>
  <div id="hint" style="min-height:22px;color:__MUTED__;font-size:.9rem;">Press Start and follow the circle: 4s in · 4s hold · 4s out · 4s rest</div>
  <div style="margin-top:10px;display:flex;gap:10px;justify-content:center;">
    <button id="startBtn" style="__BTN__">▶ Start</button>
    <button id="stopBtn" style="__BTN__border-color:#ff4a4a;background:rgba(255,74,74,.15);">⏹ Stop / Reset</button>
  </div>
  <div id="done" style="__DONE__"></div>
</div>
<script>
  __HELPER__
  var PHASES = [["INHALE","Breathe in slowly through your nose",1.55,"__A1__"],
                ["HOLD","Hold gently, shoulders relaxed",1.55,"#ffb703"],
                ["EXHALE","Breathe out slowly through your mouth",1.0,"#ff6b6b"],
                ["REST","Rest before the next breath",1.0,"#39ff14"]];
  var CYCLES = 3, SECS = 4, timer = null, cycle = 0, phase = 0, left = SECS;
  var ring = document.getElementById("ring"), phaseEl = document.getElementById("phase"),
      countEl = document.getElementById("count"), hintEl = document.getElementById("hint"),
      cycEl = document.getElementById("cyc"), doneEl = document.getElementById("done");
  function applyPhase() {
    var p = PHASES[phase];
    ring.style.transform = "scale(" + p[2] + ")"; ring.style.borderColor = p[3]; ring.style.boxShadow = "0 0 30px " + p[3];
    phaseEl.innerText = p[0]; phaseEl.style.color = p[3]; hintEl.innerText = p[1];
    cycEl.innerText = "CYCLE " + (cycle + 1) + " / " + CYCLES; countEl.innerText = left;
  }
  function resetView(label) {
    ring.style.transform = "scale(1)"; ring.style.borderColor = "__A2__"; ring.style.boxShadow = "none";
    phaseEl.innerText = label; phaseEl.style.color = ""; countEl.innerText = SECS;
  }
  function tick() {
    left -= 1;
    if (left <= 0) {
      phase += 1;
      if (phase >= PHASES.length) { phase = 0; cycle += 1; }
      if (cycle >= CYCLES) { finish(); return; }
      left = SECS; applyPhase(); return;
    }
    countEl.innerText = left;
  }
  function finish() {
    clearInterval(timer); timer = null; resetView("DONE");
    cycEl.innerText = "CYCLE 3 / 3"; hintEl.innerText = "Well done. Notice how your body feels now.";
    doneEl.innerHTML = "✨ 3 cycles complete! " + winText(15); doneEl.style.display = "block"; celebrate(); reportWin(15);
  }
  document.getElementById("startBtn").onclick = function () {
    if (timer) return;
    cycle = 0; phase = 0; left = SECS; doneEl.style.display = "none";
    applyPhase(); timer = setInterval(tick, 1000);
  };
  document.getElementById("stopBtn").onclick = function () {
    clearInterval(timer); timer = null; cycle = 0; phase = 0; left = SECS;
    resetView("READY"); cycEl.innerText = "CYCLE 0 / 3"; doneEl.style.display = "none";
    hintEl.innerText = "Stopped. Press Start whenever you are ready.";
  };
</script>
"""

    MEMORY_HTML = """
<div style="font-family:'Segoe UI',system-ui,sans-serif;text-align:center;color:__TEXT__;">
  <div style="margin-bottom:10px;font-weight:bold;color:__A2__;font-size:.95rem;">
    Flips: <span id="flips">0</span> · Pairs: <span id="pairs">0</span>/8
    <button id="restart" style="__BTN__margin-left:10px;padding:3px 10px;">↻ Restart</button>
  </div>
  <div style="font-size:.8rem;color:__MUTED__;margin-bottom:8px;">Fewer flips = more points (8 flips = a perfect 30).</div>
  <div id="board" style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;max-width:280px;margin:0 auto;"></div>
  <div id="win" style="__DONE__"></div>
</div>
<script>
  __HELPER__
  var ICONS = ["🌸","🍃","🌊","☀️","⭐","🔮","🍀","🎨"];
  var board = document.getElementById("board"), selected = [], matched = 0, flips = 0, busy = false;
  function shuffle(a) { for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t; } return a; }
  function hide(c) { c.style.color = "transparent"; c.style.background = "__CARD__"; c.dataset.open = "0"; }
  function build() {
    board.innerHTML = ""; selected = []; matched = 0; flips = 0; busy = false;
    document.getElementById("flips").innerText = 0; document.getElementById("pairs").innerText = 0;
    document.getElementById("win").style.display = "none";
    shuffle(ICONS.concat(ICONS)).forEach(function (icon) {
      var c = document.createElement("div");
      c.style.cssText = "height:54px;border:1px solid __A2__;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:1.5rem;cursor:pointer;user-select:none;transition:background .2s, transform .2s;";
      c.innerText = icon; c.dataset.icon = icon; hide(c);
      c.onclick = function () {
        if (busy || c.dataset.open === "1" || c.dataset.done === "1") return;
        c.style.color = "__TEXT__"; c.style.background = "__CARD_OPEN__"; c.style.transform = "scale(1.05)"; c.dataset.open = "1";
        selected.push(c); tick();
        if (selected.length === 2) {
          flips += 1; document.getElementById("flips").innerText = flips;
          var a = selected[0], b = selected[1];
          if (a.dataset.icon === b.dataset.icon) {
            [a, b].forEach(function (x) { x.style.border = "1px solid #39ff14"; x.dataset.done = "1"; x.style.transform = "scale(1)"; });
            matched += 2; selected = []; fxSound([[880, 0, 0.12], [1320, 0.08, 0.2]]);
            document.getElementById("pairs").innerText = matched / 2;
            if (matched === 16) {
              var pts = Math.max(8, 30 - 2 * Math.max(0, flips - 8));
              var w = document.getElementById("win"); w.style.display = "block";
              w.innerHTML = "🎉 Board clear in " + flips + " flips! " + winText(pts);
              celebrate(); reportWin(pts);
            }
          } else {
            busy = true;
            setTimeout(function () { [a, b].forEach(function (x) { hide(x); x.style.transform = "scale(1)"; }); selected = []; busy = false; }, 700);
          }
        }
      };
      board.appendChild(c);
    });
  }
  document.getElementById("restart").onclick = build;
  build();
</script>
"""

    BUBBLE_HTML = """
<div style="font-family:'Segoe UI',system-ui,sans-serif;text-align:center;color:__TEXT__;">
  <div style="display:flex;gap:14px;justify-content:center;align-items:center;flex-wrap:wrap;font-weight:700;">
    <span>⏱ <span id="time">40</span>s</span><span>🫧 Score: <span id="score">0</span></span>
    <button id="start" style="__BTN__">▶ Start</button>
    <label style="font-weight:400;font-size:.85rem;cursor:pointer;"><input type="checkbox" id="sound"> 🔊 Soft pop sounds</label>
  </div>
  <div id="field" style="position:relative;height:290px;margin-top:10px;border-radius:14px;overflow:hidden;border:1px solid __A2__;
       background:linear-gradient(180deg,rgba(__A1RGB__,.07),rgba(__A3RGB__,.12));touch-action:manipulation;">
    <div id="msg" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:__MUTED__;padding:20px;">
      Press Start, then pop the rising bubbles. Golden bubbles are worth 3. Every 4 score = 1 Zen Point (max 25).</div>
  </div>
  <div id="end" style="__DONE__"></div>
</div>
<script>
  __HELPER__
  var running = false, score = 0, left = 40, spawnT = null, clockT = null, actx = null;
  document.getElementById("sound").checked = SOUND_ON;
  var field = document.getElementById("field");
  function popSound(gold) {
    if (!document.getElementById("sound").checked) return;
    try {
      actx = actx || new (window.AudioContext || window.webkitAudioContext)();
      var t = actx.currentTime, o = actx.createOscillator(), g = actx.createGain();
      o.type = "sine";
      o.frequency.setValueAtTime(gold ? 950 : 520 + Math.random() * 300, t);
      o.frequency.exponentialRampToValueAtTime(110, t + 0.12);
      g.gain.setValueAtTime(0.22, t);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.16);
      o.connect(g); g.connect(actx.destination); o.start(t); o.stop(t + 0.17);
    } catch (e) {}
  }
  function spawn() {
    if (!running) return;
    var b = document.createElement("div"), gold = Math.random() < 0.12, size = 34 + Math.random() * 30, dur = 3.5 + Math.random() * 3;
    b.className = "bubble";
    b.style.cssText = "position:absolute;bottom:-70px;left:" + (Math.random() * 88) + "%;width:" + size + "px;height:" + size +
      "px;border-radius:50%;cursor:pointer;transition:bottom " + dur + "s linear, transform .15s, opacity .15s;" +
      (gold ? "background:radial-gradient(circle at 30% 30%,#fff7c2,#ffb703);box-shadow:0 0 14px #ffb703;"
            : "background:radial-gradient(circle at 30% 30%,rgba(255,255,255,.95),rgba(__A1RGB__,.35));border:1px solid rgba(255,255,255,.6);");
    b.onpointerdown = function () {
      if (!running || b.dataset.popped) return;
      b.dataset.popped = "1"; score += gold ? 3 : 1; popSound(gold);
      document.getElementById("score").innerText = score;
      b.style.transform = "scale(1.5)"; b.style.opacity = "0";
      setTimeout(function () { b.remove(); }, 160);
    };
    b.addEventListener("transitionend", function (e) { if (e.propertyName === "bottom") b.remove(); });
    field.appendChild(b);
    setTimeout(function () { b.style.bottom = "330px"; }, 30);
  }
  function finish() {
    running = false; clearInterval(spawnT); clearInterval(clockT);
    field.querySelectorAll(".bubble").forEach(function (x) { x.remove(); });
    document.getElementById("msg").style.display = "flex";
    var pts = Math.min(25, Math.floor(score / 4)), end = document.getElementById("end");
    end.style.display = "block";
    end.innerHTML = pts > 0
      ? "🫧 Round over! You scored " + score + ". " + winText(pts)
      : "Round over! Score " + score + " — pop at least 4 bubbles to earn points. Try again!";
    if (pts > 0) { celebrate(); reportWin(pts); }
  }
  document.getElementById("start").onclick = function () {
    if (running) return;
    try { actx = actx || new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {}
    score = 0; left = 40; running = true;
    document.getElementById("score").innerText = 0; document.getElementById("time").innerText = left;
    document.getElementById("end").style.display = "none"; document.getElementById("msg").style.display = "none";
    spawnT = setInterval(spawn, 450);
    clockT = setInterval(function () { left -= 1; document.getElementById("time").innerText = left; if (left <= 0) finish(); }, 1000);
  };
</script>
"""

    WHACK_HTML = """
<div style="font-family:'Segoe UI',system-ui,sans-serif;text-align:center;color:__TEXT__;">
  <div style="display:flex;gap:14px;justify-content:center;align-items:center;font-weight:700;">
    <span>⏱ <span id="t">30</span>s</span><span>🔨 Score: <span id="s">0</span></span>
    <button id="go" style="__BTN__">▶ Start</button>
  </div>
  <div style="font-size:.85rem;color:__MUTED__;margin-top:6px;">Smash the stressors 📚 ⏰ 😫 📝 📱 (+1) but leave the calm 🌿 alone (−2). It speeds up!</div>
  <div id="grid" style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;max-width:300px;margin:12px auto;touch-action:manipulation;"></div>
  <div id="end" style="__DONE__"></div>
</div>
<script>
  __HELPER__
  var STRESS = ["📚","⏰","😫","📝","📱"], running = false, score = 0, left = 30, elapsed = 0, clockT = null, spawnT = null;
  var grid = document.getElementById("grid"), cells = [];
  function clearCell(c) { c.innerText = ""; c.dataset.kind = ""; clearTimeout(c._t); }
  for (var i = 0; i < 9; i++) {
    (function () {
      var c = document.createElement("div");
      c.style.cssText = "height:78px;border-radius:12px;border:1px solid __A2__;background:__CARD__;display:flex;align-items:center;justify-content:center;font-size:2rem;cursor:pointer;user-select:none;transition:transform .1s, background .2s;";
      c.dataset.kind = "";
      c.onpointerdown = function () {
        if (!running || !c.dataset.kind) return;
        if (c.dataset.kind === "stress") { score += 1; c.style.background = "rgba(57,255,20,.35)"; fxSound([[700, 0, 0.06, "square"]]); }
        else { score -= 2; c.style.background = "rgba(255,74,74,.4)"; fxSound([[180, 0, 0.18, "sawtooth"]]); }
        document.getElementById("s").innerText = score;
        clearCell(c); c.style.transform = "scale(.9)";
        setTimeout(function () { c.style.transform = "scale(1)"; c.style.background = "__CARD__"; }, 160);
      };
      grid.appendChild(c); cells.push(c);
    })();
  }
  function spawn() {
    if (!running) return;
    var empty = cells.filter(function (c) { return !c.dataset.kind; });
    if (empty.length) {
      var c = empty[Math.floor(Math.random() * empty.length)], calm = Math.random() < 0.22;
      c.dataset.kind = calm ? "calm" : "stress";
      c.innerText = calm ? "🌿" : STRESS[Math.floor(Math.random() * STRESS.length)];
      c._t = setTimeout(function () { clearCell(c); }, Math.max(550, 1150 - elapsed * 18));
    }
    spawnT = setTimeout(spawn, Math.max(330, 800 - elapsed * 14));
  }
  function finish() {
    running = false; clearInterval(clockT); clearTimeout(spawnT); cells.forEach(clearCell);
    var pts = Math.min(25, Math.max(0, Math.round(score * 0.7))), end = document.getElementById("end");
    end.style.display = "block";
    end.innerHTML = pts > 0
      ? "🔨 Time! You scored " + score + ". " + winText(pts)
      : "Time! Score " + score + " — smash more stressors (and avoid the 🌿) to earn points. Try again!";
    if (pts > 0) { celebrate(); reportWin(pts); }
  }
  document.getElementById("go").onclick = function () {
    if (running) return;
    score = 0; left = 30; elapsed = 0; running = true; cells.forEach(clearCell);
    document.getElementById("s").innerText = 0; document.getElementById("t").innerText = left;
    document.getElementById("end").style.display = "none";
    clockT = setInterval(function () { left -= 1; elapsed += 1; document.getElementById("t").innerText = left; if (left <= 0) finish(); }, 1000);
    spawn();
  };
</script>
"""

    MAZE_HTML = """
<div style="font-family:'Segoe UI',system-ui,sans-serif;text-align:center;color:__TEXT__;">
  <div style="display:flex;gap:14px;justify-content:center;align-items:center;font-weight:700;">
    <span>⏱ <span id="tm">0.0</span>s</span><span>Moves: <span id="mv">0</span></span>
    <button id="newMaze" style="__BTN__">🔀 New Maze</button>
  </div>
  <div style="font-size:.85rem;color:__MUTED__;margin:6px 0;">Drag the 🚗 along the paths to the 🏁 (arrow keys work too). The clock starts on your first move.</div>
  <canvas id="cv" width="330" height="330" style="max-width:100%;touch-action:none;border-radius:12px;border:1px solid __A2__;background:__CARD__;cursor:grab;"></canvas>
  <div id="end" style="__DONE__"></div>
</div>
<script>
  __HELPER__
  var N = 9, SZ = 330, S = SZ / N, walls, pos, start = null, timerT = null, moves = 0, done = false, dragging = false;
  var cv = document.getElementById("cv"), ctx = cv.getContext("2d");
  function gen() {
    walls = [];
    for (var r = 0; r < N; r++) { walls.push([]); for (var c = 0; c < N; c++) walls[r].push({t: 1, r: 1, b: 1, l: 1, v: 0}); }
    var stack = [[0, 0]]; walls[0][0].v = 1;
    while (stack.length) {
      var cur = stack[stack.length - 1], r = cur[0], c = cur[1], nb = [];
      if (r > 0 && !walls[r - 1][c].v) nb.push([r - 1, c, "t", "b"]);
      if (c < N - 1 && !walls[r][c + 1].v) nb.push([r, c + 1, "r", "l"]);
      if (r < N - 1 && !walls[r + 1][c].v) nb.push([r + 1, c, "b", "t"]);
      if (c > 0 && !walls[r][c - 1].v) nb.push([r, c - 1, "l", "r"]);
      if (!nb.length) { stack.pop(); continue; }
      var n = nb[Math.floor(Math.random() * nb.length)];
      walls[r][c][n[2]] = 0; walls[n[0]][n[1]][n[3]] = 0; walls[n[0]][n[1]].v = 1; stack.push([n[0], n[1]]);
    }
  }
  function line(x1, y1, x2, y2) { ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); }
  function draw() {
    ctx.clearRect(0, 0, SZ, SZ);
    ctx.strokeStyle = "__A2__"; ctx.lineWidth = 3; ctx.lineCap = "round";
    for (var r = 0; r < N; r++) for (var c = 0; c < N; c++) {
      var w = walls[r][c], x = c * S, y = r * S;
      if (w.t) line(x, y, x + S, y); if (w.l) line(x, y, x, y + S);
      if (w.b) line(x, y + S, x + S, y + S); if (w.r) line(x + S, y, x + S, y + S);
    }
    ctx.font = Math.floor(S * 0.68) + "px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText("🏁", (N - 0.5) * S, (N - 0.5) * S + 1);
    ctx.fillText("🚗", (pos[1] + 0.5) * S, (pos[0] + 0.5) * S + 1);
  }
  function canMove(dr, dc) {
    var w = walls[pos[0]][pos[1]];
    return (dr === -1 && !w.t) || (dr === 1 && !w.b) || (dc === -1 && !w.l) || (dc === 1 && !w.r);
  }
  function step(dr, dc) {
    if (done || !canMove(dr, dc)) return false;
    if (start === null) {
      start = Date.now();
      timerT = setInterval(function () { document.getElementById("tm").innerText = ((Date.now() - start) / 1000).toFixed(1); }, 100);
    }
    pos = [pos[0] + dr, pos[1] + dc]; moves += 1; document.getElementById("mv").innerText = moves; draw();
    if (moves % 3 === 0) tick();
    if (pos[0] === N - 1 && pos[1] === N - 1) finish();
    return true;
  }
  function cellAt(e) {
    var b = cv.getBoundingClientRect();
    return [Math.floor((e.clientY - b.top) * SZ / b.height / S), Math.floor((e.clientX - b.left) * SZ / b.width / S)];
  }
  cv.onpointerdown = function (e) {
    var c = cellAt(e);
    if (c[0] === pos[0] && c[1] === pos[1]) { dragging = true; cv.setPointerCapture(e.pointerId); cv.style.cursor = "grabbing"; }
  };
  cv.onpointermove = function (e) {
    if (!dragging) return;
    var t = cellAt(e), guard = 0;
    while ((t[0] !== pos[0] || t[1] !== pos[1]) && guard++ < 4) {
      var dr = Math.sign(t[0] - pos[0]), dc = Math.sign(t[1] - pos[1]);
      if (dr !== 0 && step(dr, 0)) continue;
      if (dc !== 0 && step(0, dc)) continue;
      break;
    }
  };
  cv.onpointerup = cv.onpointercancel = function () { dragging = false; cv.style.cursor = "grab"; };
  document.addEventListener("keydown", function (e) {
    var k = {ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1]}[e.key];
    if (k) { e.preventDefault(); step(k[0], k[1]); }
  });
  function finish() {
    done = true; clearInterval(timerT);
    var secs = (Date.now() - start) / 1000;
    var pts = Math.max(8, Math.min(25, 25 - Math.floor(Math.max(0, secs - 12) / 2)));
    var end = document.getElementById("end"); end.style.display = "block";
    end.innerHTML = "🏁 Finished in " + secs.toFixed(1) + "s! " + winText(pts);
    celebrate(); reportWin(pts);
  }
  function reset() {
    clearInterval(timerT); gen(); pos = [0, 0]; start = null; moves = 0; done = false;
    document.getElementById("tm").innerText = "0.0"; document.getElementById("mv").innerText = 0;
    document.getElementById("end").style.display = "none"; draw();
  }
  document.getElementById("newMaze").onclick = reset;
  reset();
</script>
"""

    # Daily Word: (word, part of speech, meaning, example sentence). The answer stays on the server,
    # so it can't be found by inspecting the page.
    WORD_BANK = [
        ("ADEPT", "adjective", "Very skilled or good at something.", "She is adept at solving tricky integration problems."),
        ("AGILE", "adjective", "Able to move or think quickly and easily.", "An agile mind adapts quickly to unfamiliar questions."),
        ("ALOFT", "adverb", "Up in the air; overhead.", "The kite stayed aloft all afternoon in the sea breeze."),
        ("AMBLE", "verb", "To walk at a slow, relaxed pace.", "After the last paper, we ambled along the beach at sunset."),
        ("AMPLE", "adjective", "Enough or more than enough; plentiful.", "Leave ample time to revise before the board exams."),
        ("BLISS", "noun", "Perfect happiness; great joy.", "Sleeping in after the final exam felt like pure bliss."),
        ("BLOOM", "verb", "To grow or develop well; to produce flowers.", "With the right support, every student can bloom."),
        ("BRAVE", "adjective", "Ready to face danger, pain or difficulty; showing courage.", "It was brave of him to ask for help when he was struggling."),
        ("BRISK", "adjective", "Quick, active and energetic.", "A brisk ten-minute walk can clear your head between study blocks."),
        ("CIVIC", "adjective", "Relating to a town or city, or to the duties of its citizens.", "Volunteering at the clean-up drive is a civic responsibility."),
        ("CREED", "noun", "A set of beliefs or principles that guide someone's actions.", "Honesty and hard work are the creed of our team."),
        ("DEFER", "verb", "To put off to a later time; to postpone.", "Don't defer your revision until the final week."),
        ("DELVE", "verb", "To search or research deeply into something.", "Delve into past papers to spot the questions that repeat."),
        ("DWELL", "verb", "To keep thinking or talking about something, usually something unpleasant (dwell on).", "Don't dwell on one bad mock score; learn from it and move on."),
        ("EAGER", "adjective", "Wanting very much to do or have something.", "The juniors were eager to try our MindPulse app."),
        ("EMBER", "noun", "A small piece of burning wood or coal in a dying fire.", "A single ember of hope can grow into determination."),
        ("ENDOW", "verb", "To give someone a quality or ability.", "Practice endows you with confidence on exam day."),
        ("EPOCH", "noun", "A long period of time marked by notable events or changes.", "The invention of the internet began a new epoch."),
        ("EVOKE", "verb", "To bring a feeling, memory or image into the mind.", "The smell of rain evokes memories of childhood holidays."),
        ("FABLE", "noun", "A short story, often with animals, that teaches a moral lesson.", "The fable of the tortoise and the hare rewards steady effort."),
        ("FEIGN", "verb", "To pretend to feel or have something.", "He feigned calm, but his hands were shaking before the viva."),
        ("FLAIR", "noun", "A natural ability to do something well.", "She has a flair for explaining physics in simple words."),
        ("FORGE", "verb", "To create something strong or lasting through effort.", "Our team forged a strong friendship while building the project."),
        ("GAUGE", "verb", "To estimate or judge something, such as progress or feelings.", "Use timed mock tests to gauge how ready you are."),
        ("GLEAN", "verb", "To gather information slowly, bit by bit.", "I gleaned useful tips from last year's toppers."),
        ("GRACE", "noun", "Elegance of movement; or courtesy and kindness.", "He accepted the feedback with grace."),
        ("GUSTO", "noun", "Great enjoyment and energy in doing something.", "She tackled the problem set with gusto."),
        ("HAVEN", "noun", "A safe or peaceful place; a refuge.", "The school library became my quiet haven during exams."),
        ("HEFTY", "adjective", "Large and heavy; or large in amount.", "The hefty chemistry textbook felt lighter once I made summary notes."),
        ("IDEAL", "adjective", "Perfect, or the best possible.", "Early morning is the ideal time for tough topics."),
        ("IMBUE", "verb", "To fill someone or something with a feeling or quality.", "Her speech imbued the whole class with hope."),
        ("INFER", "verb", "To work out a conclusion from evidence and reasoning.", "From the graph, we can infer that sleep affects stress."),
        ("IRONY", "noun", "A situation that is strangely the opposite of what you would expect.", "The irony was that I stayed up all night studying sleep science."),
        ("KNACK", "noun", "A natural skill or a clever way of doing something.", "He has a knack for mental maths."),
        ("LUCID", "adjective", "Clear and easy to understand.", "Examiners reward lucid, well-structured answers."),
        ("MERIT", "noun", "The quality of being good, worthy or deserving praise.", "The scholarship is awarded on merit."),
        ("MIRTH", "noun", "Amusement and laughter.", "The classroom filled with mirth when the teacher told a joke."),
        ("MOTTO", "noun", "A short phrase that expresses a guiding belief.", "Our team motto is 'Predicting Strain, Protecting Minds'."),
        ("NOBLE", "adjective", "Having high moral principles and good character.", "Tutoring younger students for free is a noble act."),
        ("NOVEL", "adjective", "New, original and unusual.", "The team found a novel way to measure stress."),
        ("OASIS", "noun", "A fertile spot in a desert; or a peaceful place in a busy situation.", "The quiet garden was an oasis during exam week."),
        ("PLUCK", "noun", "Courage and determination in a difficult situation.", "It took pluck to present in front of the whole school."),
        ("POISE", "noun", "Calm, graceful self-control.", "She answered the examiner's questions with poise."),
        ("PRISM", "noun", "A clear glass object that splits white light into colours.", "In physics we used a prism to see the spectrum."),
        ("QUELL", "verb", "To calm or put an end to something, such as a fear.", "Slow breathing helps quell exam nerves."),
        ("QUEST", "noun", "A long search for something important.", "Learning is a lifelong quest."),
        ("RALLY", "verb", "To come together to support a cause; or to recover strength.", "The class rallied around a friend who was feeling low."),
        ("RENEW", "verb", "To begin again; or to give fresh strength.", "A good night's sleep renews your energy."),
        ("REVEL", "verb", "To enjoy something very much.", "Take a moment to revel in your small wins."),
        ("SAVVY", "adjective", "Having practical knowledge and good judgement.", "A savvy student plans breaks into the timetable."),
        ("SPARK", "noun", "A small trace of a feeling or idea that can grow.", "One great teacher can spark a lifelong interest."),
        ("STOIC", "adjective", "Accepting hardship calmly without complaining.", "He stayed stoic even when the paper was difficult."),
        ("SWIFT", "adjective", "Happening quickly or promptly.", "Thanks for your swift reply to my question."),
        ("TACIT", "adjective", "Understood without being said directly.", "There was a tacit agreement to keep the study room quiet."),
        ("TEMPO", "noun", "The speed or pace of an activity or piece of music.", "Keep a steady tempo when revising, not a last-minute rush."),
        ("TENET", "noun", "A main principle or belief.", "Kindness is a core tenet of our school community."),
        ("TRAIT", "noun", "A quality that is part of someone's character.", "Patience is a valuable trait in a scientist."),
        ("UNITY", "noun", "The state of being joined together as one.", "The house showed great unity on sports day."),
        ("USHER", "verb", "To show someone the way; or to cause something new to begin (usher in).", "The internet ushered in a new era of learning."),
        ("VERVE", "noun", "Energy, enthusiasm and spirit.", "The choir performed with real verve."),
        ("VIVID", "adjective", "Very bright, clear or detailed.", "Colourful mind maps make your notes vivid and memorable."),
        ("WITTY", "adjective", "Clever and funny with words.", "Her witty answer made the whole panel smile."),
        ("YEARN", "verb", "To want something very strongly.", "After exams, I yearn for a long holiday."),
        ("ZESTY", "adjective", "Full of energy and enthusiasm; or having a strong, pleasant taste.", "He brought a zesty energy to every group project."),
        ("AWAKE", "adjective", "Not asleep; or fully alert and aware.", "Stay awake and alert by taking short movement breaks."),
        ("VALUE", "noun", "The importance or worth of something.", "Never underestimate the value of a good night's sleep."),
        ("CHEER", "noun", "Happiness and good spirits; or a shout of encouragement.", "A loud cheer went up when the results were announced."),
        ("DREAM", "noun", "A hope or ambition you want to achieve.", "Her dream is to study aviation management."),
        ("FOCUS", "noun", "The centre of attention or concentration.", "Put your phone away to keep your focus."),
        ("PEACE", "noun", "A state of calm and quiet; freedom from worry.", "Five minutes of deep breathing brought a sense of peace."),
        ("SHINE", "verb", "To give out light; or to be very good at something.", "Everyone has a subject where they shine."),
        ("TRUST", "noun", "A firm belief in the honesty or ability of someone.", "Talking to someone you trust can lighten any worry."),
    ]
    WORD_EPOCH = date(2026, 11, 1)
    WORD_POINTS = {1: 30, 2: 26, 3: 22, 4: 18, 5: 14, 6: 10}

    def daily_word():
        """Every word is used once before any repeats; consecutive days never share a word."""
        order = list(range(len(WORD_BANK)))
        random.Random(843).shuffle(order)
        return WORD_BANK[order[(now_local().date() - WORD_EPOCH).days % len(order)]]

    def score_guess(guess, answer):
        result, remaining = ["absent"] * 5, {}
        for i, (g, a) in enumerate(zip(guess, answer)):
            if g == a:
                result[i] = "correct"
            else:
                remaining[a] = remaining.get(a, 0) + 1
        for i, g in enumerate(guess):
            if result[i] != "correct" and remaining.get(g, 0) > 0:
                result[i] = "present"
                remaining[g] -= 1
        return result

    TILE_COLORS = {"correct": "#43aa8b", "present": "#e9c46a", "absent": "#3a3a3c" if DARK else "#787c7e", "empty": "transparent"}

    def render_word_board(guesses, answer):
        rows = []
        for r in range(6):
            if r < len(guesses):
                marks = score_guess(guesses[r], answer)
                cells = [(ch, marks[i]) for i, ch in enumerate(guesses[r])]
            else:
                cells = [("", "empty")] * 5
            tiles = "".join(
                f"<div style='width:52px;height:52px;display:flex;align-items:center;justify-content:center;font-size:1.6rem;"
                f"font-weight:800;border-radius:8px;border:2px solid {'transparent' if m != 'empty' else border_hex};"
                f"background:{TILE_COLORS[m]};color:{'#ffffff' if m != 'empty' else text_hex};"
                f"animation:fadeUp .35s ease both;animation-delay:{i * 0.08}s'>{ch}</div>"
                for i, (ch, m) in enumerate(cells))
            rows.append(f"<div style='display:flex;gap:6px;justify-content:center;margin-bottom:6px'>{tiles}</div>")
        best = {}
        rank = {"absent": 0, "present": 1, "correct": 2}
        for g in guesses:
            for ch, m in zip(g, score_guess(g, answer)):
                if rank[m] > rank.get(best.get(ch), -1):
                    best[ch] = m
        keys = ""
        for row in ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]:
            keys += "<div style='display:flex;gap:4px;justify-content:center;margin-top:4px'>" + "".join(
                f"<span style='min-width:26px;padding:6px 4px;border-radius:6px;font-weight:700;font-size:.8rem;"
                f"background:{TILE_COLORS.get(best.get(ch), tile_bg) if ch in best else tile_bg};"
                f"color:{'#ffffff' if ch in best else text_hex};border:1px solid {border_hex}'>{ch}</span>" for ch in row) + "</div>"
        st.markdown("".join(rows) + f"<div style='margin-top:10px'>{keys}</div>", unsafe_allow_html=True)

    st.markdown(
        "<span class='pill'>🧘 Breathing +15</span><span class='pill'>🧩 Memory 8–30</span>"
        "<span class='pill'>🫧 Bubble Pop up to 25</span><span class='pill'>🔨 Whack-A-Stress up to 25</span>"
        "<span class='pill'>🚗 Maze Runner up to 25</span><span class='pill'>🔤 Daily Word up to 30</span>", unsafe_allow_html=True)
    st.caption(f"Win a game and your points are added instantly. Better play = more points. Each game pays out for "
               f"{GAME_DAILY_CAP} wins a day (Daily Word once). Daily goal: {DAILY_GOAL_POINTS} points.")

    ARCADE_OPTIONS = ["🧘 Breathing", "🧩 Memory", "🫧 Bubble Pop", "🔨 Whack-A-Stress", "🚗 Maze Runner", "🔤 Daily Word"]
    arcade_choice = st.radio("Choose an activity", ARCADE_OPTIONS, horizontal=True, key="arcade_choice",
                             label_visibility="collapsed")  # remembers the selection across page reloads

    if arcade_choice == "🧘 Breathing":
        with card("breathing"):
            st.markdown(f"<h3 style='margin-top:0; color:{title_color}; text-align:center;'>🧘 Animated Box Breathing (3 Cycles)</h3>", unsafe_allow_html=True)
            play_game("breathing", BREATHING_HTML, 400)

    if arcade_choice == "🧩 Memory":
        with card("memory"):
            st.markdown(f"<h3 style='margin-top:0; color:{A2}; text-align:center;'>🧩 Memory Matrix Challenge</h3>", unsafe_allow_html=True)
            play_game("memory", MEMORY_HTML, 420)

    if arcade_choice == "🫧 Bubble Pop":
        with card("bubble"):
            st.markdown(f"<h3 style='margin-top:0; color:{title_color}; text-align:center;'>🫧 ASMR Bubble Pop</h3>", unsafe_allow_html=True)
            play_game("bubble", BUBBLE_HTML, 430)

    if arcade_choice == "🔨 Whack-A-Stress":
        with card("whack"):
            st.markdown("<h3 style='margin-top:0; color:#ff4a4a; text-align:center;'>🔨 Whack-A-Stress</h3>", unsafe_allow_html=True)
            play_game("whack", WHACK_HTML, 430)

    if arcade_choice == "🚗 Maze Runner":
        with card("maze"):
            st.markdown(f"<h3 style='margin-top:0; color:{title_color}; text-align:center;'>🚗 Maze Runner</h3>", unsafe_allow_html=True)
            play_game("maze", MAZE_HTML, 470)

    if arcade_choice == "🔤 Daily Word":
        with card("daily_word"):
            st.markdown(f"<h3 style='margin-top:0; color:{title_color}; text-align:center;'>🔤 Daily Word</h3>", unsafe_allow_html=True)
            st.caption("Guess today's 5-letter word in 6 tries. 🟩 right letter, right spot · 🟨 right letter, wrong spot · "
                       "⬛ not in the word. Everyone gets the same word, and a new one arrives every day.")
            answer, part, meaning, example = daily_word()
            state = user_data["stats"].get("wordle")
            if not isinstance(state, dict) or state.get("date") != today_str():
                state = {"date": today_str(), "guesses": [], "status": "playing"}
                user_data["stats"]["wordle"] = state
            render_word_board(state["guesses"], answer)
            if state["status"] == "playing":
                with st.form("word_form", clear_on_submit=True):
                    w_in, w_btn = st.columns([2, 1])
                    guess_raw = w_in.text_input("Your guess", max_chars=5, placeholder="5-letter word", label_visibility="collapsed")
                    guess_go = w_btn.form_submit_button("Guess ↵", **full_width(st.form_submit_button))
                if guess_go:
                    guess = guess_raw.strip().upper()
                    if not re.fullmatch(r"[A-Z]{5}", guess):
                        st.error("Please type exactly 5 letters.")
                    elif not re.search(r"[AEIOUY]", guess):
                        st.error("That doesn't look like a real word. Try one with a vowel.")
                    elif guess in state["guesses"]:
                        st.error("You already tried that word.")
                    else:
                        state["guesses"].append(guess)
                        tries = len(state["guesses"])
                        if guess == answer:
                            state["status"] = "won"
                            stats = user_data["stats"]
                            stats["wordle_wins"] = stats.get("wordle_wins", 0) + 1
                            stats["best_wordle"] = min(stats.get("best_wordle", 7), tries)
                            log_play(user_data, "wordle")
                            award_points(UID, WORD_POINTS[tries], f"daily word in {tries} {'try' if tries == 1 else 'tries'}",
                                         "wordle", celebrate=True)
                        else:
                            if tries >= 6:
                                state["status"] = "lost"
                                log_play(user_data, "wordle")
                            persist_user(UID)
                            queue_sound("click")
                        st.rerun()
                st.caption(f"Tries left: {6 - len(state['guesses'])} · Solve in 1 try = 30 pts, 2 = 26, 3 = 22, 4 = 18, 5 = 14, 6 = 10")
            else:
                if state["status"] == "won":
                    st.success(f"🎉 Solved in {len(state['guesses'])} {'try' if len(state['guesses']) == 1 else 'tries'}! Come back tomorrow for a new word.")
                else:
                    st.warning(f"So close! Today's word was **{answer}**. A new word arrives tomorrow.")
                st.markdown(f"<div class='result-card' style='border-left:6px solid {A1};'>"
                            f"<h2 style='margin:0;color:{A1};letter-spacing:4px'>{answer}</h2>"
                            f"<p style='margin:4px 0;color:{muted_hex};font-style:italic'>{part}</p>"
                            f"<p style='margin:6px 0;font-size:1.05rem'><b>Meaning:</b> {meaning}</p>"
                            f"<p style='margin:0'><b>Example:</b> “{example}”</p></div>", unsafe_allow_html=True)

    with card("roadmap"):
        st.markdown(f"<h4 style='color:{muted_hex}; margin-top:0; text-align:center;'>🚀 Future Release Roadmap</h4>", unsafe_allow_html=True)
        st.markdown("- **Somatic Particle Catcher:** an interactive 2D physics mini-game for hand-eye focus resets.\n"
                    "- **Weekly class challenges:** team goals that reward groups for healthy habits together.")

# ==============================================================================
# 👤 STEP 10B: MY PROFILE — change name, change password, download my data
# ==============================================================================
elif ACTIVE == "Profile":
    back_home_button()
    page_title("My", "Profile")
    prof_left, prof_right = st.columns(2)

    with prof_left:
        with card("profile_name"):
            st.markdown(f"<h4 style='margin-top:0; color:{title_color};'>✏️ Change Display Name</h4>", unsafe_allow_html=True)
            st.caption(f"Current name: **{user_data['name']}** · School ID **{UID}** (IDs can't be changed)")
            with st.form("name_form", clear_on_submit=True):
                new_name = st.text_input("New display name")
                if st.form_submit_button("Update Name", **full_width(st.form_submit_button)):
                    clean, err = validate_name(new_name, UID)
                    if err:
                        st.error(err)
                    else:
                        user_data["name"] = clean
                        persist_user(UID)
                        flash(f"Name updated to {clean}.", "✏️")
                        st.rerun()

        with card("profile_password"):
            st.markdown(f"<h4 style='margin-top:0; color:{title_color};'>🔑 Change Password</h4>", unsafe_allow_html=True)
            with st.form("password_form", clear_on_submit=True):
                current_pw = st.text_input("Current password", type="password")
                new_pw = st.text_input("New password (min. 6 characters)", type="password")
                new_pw2 = st.text_input("Confirm new password", type="password")
                if st.form_submit_button("Update Password", **full_width(st.form_submit_button)):
                    if not verify_password(user_data["password"], current_pw):
                        st.error("Current password is incorrect.")
                    elif len(new_pw) < 6:
                        st.error("New password must be at least 6 characters.")
                    elif new_pw != new_pw2:
                        st.error("New passwords do not match.")
                    elif new_pw == current_pw:
                        st.error("New password must be different from the current one.")
                    else:
                        user_data["password"] = hash_password(new_pw)
                        persist_user(UID)
                        flash("Password updated securely.", "🔒")
                        st.rerun()

    with prof_right:
        with card("profile_stats"):
            st.markdown(f"<h4 style='margin-top:0; color:{title_color};'>📇 My Wellness Summary</h4>", unsafe_allow_html=True)
            games_total = sum(n for day in user_data["arcade_log"].values() if isinstance(day, dict)
                              for act, n in day.items() if act != "task")
            s1, s2 = st.columns(2)
            s1.metric("Day Streak", user_data.get("consecutive_days_streak", 0))
            s2.metric("Personal Best", f"{user_data.get('high_score', 0)} pts")
            s1.metric("Stress Check-ins", len(valid_checkins(user_data)))
            s2.metric("Tasks Completed", len(completed_tasks(user_data)))
            s1.metric("Games Played", games_total)
            s2.metric("Badges", f"{sum(1 for b in BADGES if b[3](user_data))}/{len(BADGES)}")

        with card("profile_data"):
            st.markdown(f"<h4 style='margin-top:0; color:{title_color};'>📦 My Data</h4>", unsafe_allow_html=True)
            st.caption("Download everything MindPulse stores about you (your password is never included).")
            export = {k: v for k, v in user_data.items() if k != "password"}
            st.download_button("⬇️ Download my data (JSON)", data=json.dumps(export, indent=2, ensure_ascii=False).encode("utf-8"),
                               file_name=f"mindpulse_{UID}_data.json", mime="application/json",
                               **full_width(st.download_button))

# ==============================================================================
# 📊 STEP 11: UNIFIED APP FOOTER PROGRESS DECK
# ==============================================================================
st.markdown("---")
pts = today_points(user_data)
foot_col1, foot_col2 = st.columns([2.5, 1])
with foot_col1:
    st.markdown(f"**Daily Balanced Stress-Relief Progress Target: {pts} / {DAILY_GOAL_POINTS} Points**")
    st.progress(min(1.0, pts / DAILY_GOAL_POINTS))
with foot_col2:
    st.markdown(f"<h3 style='margin-top:15px; color:{title_color}; text-align:right;'>{int(min(100, pts / DAILY_GOAL_POINTS * 100))}% Relieved</h3>", unsafe_allow_html=True)
