"""
8DStud by PK  v8.3
====================
py -3.12 8DStud_v8.3.py

Changes in v8.3:
  - REMOVED: Recently Played screen, Queue screen (simplified)
  - UNICODE FIX: Bundled NotoSans/DejaVuSans loaded explicitly at startup.
    Kivy's default DroidSans is missing most music symbols. We download
    NotoSans-Regular.ttf once into BASE_DIR and set it as the global font.
  - NAV FREEZE FIX (root cause): LibraryScreen's ScrollView was stealing
    all subsequent touches because after scrolling, Kivy's ScrollView keeps
    touch grab alive. Fixed by subclassing ScrollView to release grab on
    touch_up, and also by making song_row NOT bind any touch events on the
    row BoxLayout itself — only the explicit Button widgets handle touches.
  - play/pause icon in now bar was not flipping — fixed set_playing().
  - Drawer menu updated to remove recent/queue entries.
"""

import os, sys, urllib.request
os.environ.setdefault("KIVY_NO_ENV_CONFIG", "1")
from kivy.config import Config
Config.set("graphics", "width",  "393")
Config.set("graphics", "height", "852")
Config.set("input", "mouse", "mouse,multitouch_on_demand")

import json, threading, subprocess, struct, wave, math
import queue as _queue, shutil, zipfile, time, random

from kivy.app               import App
from kivy.clock             import Clock
from kivy.metrics           import dp, sp
from kivy.core.window       import Window
from kivy.core.text         import LabelBase
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
from kivy.uix.boxlayout     import BoxLayout
from kivy.uix.floatlayout   import FloatLayout
from kivy.uix.anchorlayout  import AnchorLayout
from kivy.uix.scrollview    import ScrollView
from kivy.uix.widget        import Widget
from kivy.uix.label         import Label
from kivy.uix.button        import Button
from kivy.uix.textinput     import TextInput
from kivy.uix.slider        import Slider
from kivy.uix.checkbox      import CheckBox
from kivy.uix.progressbar   import ProgressBar
from kivy.uix.popup         import Popup
from kivy.graphics          import Color, Rectangle, RoundedRectangle, Ellipse
from kivy.graphics.texture  import Texture
from kivy.animation         import Animation

import requests as _req
from PIL import Image as PilImage
from io  import BytesIO
from kivy.utils import platform

if platform != "android":
    try:
        import pyglet
        pyglet.options["audio"]             = ("directsound", "openal", "pulse", "silent")
        pyglet.options["audio_buffers"]     = 8
        pyglet.options["audio_buffer_size"] = 65536
    except ImportError:
        pass
from kivy.core.audio import SoundLoader

# ══════════════════════════════════════════════════════════════════════════════
# FONT SETUP
# Priority: Segoe UI Symbol (Windows built-in) → cached NotoSans → async DL
# Segoe UI Symbol ships with every Windows 10/11 install and has ALL symbols.
# ══════════════════════════════════════════════════════════════════════════════
BASE_DIR = FONT_PATH = FF_DIR = FF_EXE = ID_FILE = UD = DL_DIR = ED_DIR = PL_FILE = ST_FILE = LK_FILE = PC_FILE = ""

def _setup_font():
    bundled = os.path.join(os.path.dirname(__file__), "NotoSans-Regular.ttf")
    if os.path.exists(bundled):
        try:
            LabelBase.register("AppFont", fn_regular=bundled)
            return "AppFont"
        except: pass
        
    if platform == "win":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        for _f in ["seguisym.ttf", "seguiemj.ttf", "DejaVuSans.ttf"]:
            _wf = os.path.join(windir, "Fonts", _f)
            if os.path.exists(_wf):
                try:
                    LabelBase.register("AppFont", fn_regular=_wf)
                    return "AppFont"
                except Exception:
                    pass
    return "Roboto"

_APP_FONT = _setup_font()

# ── Palette ───────────────────────────────────────────────────────────────────
C = {
    "bg":     (0.039, 0.039, 0.039, 1),
    "bg2":    (0.071, 0.071, 0.071, 1),
    "card":   (0.110, 0.110, 0.110, 1),
    "card2":  (0.157, 0.157, 0.157, 1),
    "card3":  (0.220, 0.220, 0.220, 1),
    "sep":    (0.180, 0.180, 0.180, 1),
    "green":  (0.114, 0.725, 0.329, 1),
    "green2": (0.141, 0.820, 0.384, 1),
    "red":    (1.000, 0.220, 0.220, 1),
    "white":  (1, 1, 1, 1),
    "lgrey":  (0.600, 0.600, 0.600, 1),
    "mgrey":  (0.400, 0.400, 0.400, 1),
    "dgrey":  (0.220, 0.220, 0.220, 1),
    "black":  (0, 0, 0, 1),
}
PL_COLS = ["green", "green2", "lgrey", "mgrey", "green", "green2", "lgrey", "mgrey"]

def col(n): return C.get(n, C["white"])

# ── Unicode symbol map ────────────────────────────────────────────────────────
ICO = {
    "play":    "\u25B6",   # ▶
    "pause":   "\u23F8",   # ⏸
    "next":    "\u23ED",   # ⏭
    "prev":    "\u23EE",   # ⏮
    "shuffle": "\u21C4",   # ⇄
    "like":    "\u2665",   # ♥
    "unlike":  "\u2661",   # ♡
    "close":   "\u2715",   # ✕
    "menu":    "\u2630",   # ☰
    "back":    "\u2039",   # ‹
    "star":    "\u2605",   # ★
    "unstar":  "\u2606",   # ☆
    "edit":    "\u270E",   # ✎
    "dot":     "\u2022",   # •
    "queue":   "\u2295",   # ⊕  add to play-next queue
    "chev_d":  "\u25BE",   # ▾  expand chevron (down)
    "chev_r":  "\u25B8",   # ▸  collapse chevron (right)
    "repeat":  "\u21BA",   # ↺
}

# ── Paths ─────────────────────────────────────────────────────────────────────
def init_paths(app):
    global BASE_DIR, FONT_PATH, FF_DIR, FF_EXE, ID_FILE, UD, DL_DIR, ED_DIR, PL_FILE, ST_FILE, LK_FILE, PC_FILE
    if platform == 'android':
        BASE_DIR = app.user_data_dir
        FF_DIR   = os.path.join(BASE_DIR, "ffmpeg")
        FF_EXE   = os.path.join(os.path.dirname(__file__), "ffmpeg")
        try: os.chmod(FF_EXE, 0o755)
        except: pass
    else:
        BASE_DIR = os.path.join(os.path.expanduser("~"), "8DStud")
        FF_DIR   = os.path.join(BASE_DIR, "ffmpeg")
        FF_EXE   = os.path.join(FF_DIR, "ffmpeg.exe")
    
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(FF_DIR, exist_ok=True)
    FONT_PATH = os.path.join(BASE_DIR, "NotoSans-Regular.ttf")
    ID_FILE  = os.path.join(BASE_DIR, "device_id.txt")
    if not os.path.exists(ID_FILE):
        import uuid as _u; _did = _u.uuid4().hex[:12]; open(ID_FILE, "w").write(_did)
    else:
        _did = open(ID_FILE).read().strip()
    UD      = os.path.join(BASE_DIR, "users", _did)
    DL_DIR  = os.path.join(UD, "downloads")
    ED_DIR  = os.path.join(UD, "8D")
    for _d in [DL_DIR, ED_DIR, FF_DIR]: os.makedirs(_d, exist_ok=True)
    PL_FILE = os.path.join(UD, "playlists.json")
    ST_FILE = os.path.join(UD, "settings.json")
    LK_FILE = os.path.join(UD, "liked.json")
    PC_FILE = os.path.join(UD, "playcounts.json")
ED_PL   = "8D Mixes"
DEFAULTS = {
    "autoplay": True, "sleep_timer": 0, "audio_quality": "320",
    "shuffle": False, "repeat": "none", "eq_bass": 2, "eq_treble": 1,
    "normalize": True, "fav_playlist": ""
}

def _lj(f, d):
    try:
        if os.path.exists(f): return json.load(open(f))
    except: pass
    return d() if callable(d) else d

def _sj(f, d): json.dump(d, open(f, "w"), indent=2)
def load_settings():  s = DEFAULTS.copy(); s.update(_lj(ST_FILE, {})); return s
def load_playlists(): return _lj(PL_FILE, {})
def load_liked():     return set(_lj(LK_FILE, []))
def load_counts():    return _lj(PC_FILE, {})
def fmt_t(s):         s = int(max(0, s or 0)); return f"{s // 60}:{s % 60:02d}"

# ── FFmpeg ─────────────────────────────────────────────────────────────────────
FF_URL = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
          "ffmpeg-master-latest-win64-gpl.zip")

def find_ff():
    if platform == "android": return None
    if os.path.isfile(FF_EXE): return FF_EXE
    return shutil.which("ffmpeg") or None

def dl_ff(cb=None):
    zp = os.path.join(FF_DIR, "ffmpeg.zip")
    urllib.request.urlretrieve(FF_URL, zp,
        reporthook=lambda c, b, t: cb and t > 0 and cb(min(c * b / t, .95)))
    with zipfile.ZipFile(zp) as z:
        for m in z.namelist():
            if m.endswith("ffmpeg.exe"):
                with z.open(m) as src, open(FF_EXE, "wb") as dst:
                    dst.write(src.read())
                break
    os.remove(zp)
    if cb: cb(1.0)

# ── YouTube search ─────────────────────────────────────────────────────────────
def search_yt(query, limit=12):
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    out = []
    for e in (info.get("entries") or []):
        thumbs = e.get("thumbnails") or []
        art = thumbs[-1].get("url", "") if thumbs else e.get("thumbnail", "")
        out.append({
            "title": e.get("title", "?"), "artist": e.get("uploader", ""),
            "duration": int(e.get("duration") or 0),
            "art_url": art, "query": e.get("title", query)
        })
    return out

# ── 8D Engine ──────────────────────────────────────────────────────────────────
PRESETS = {
    "Classic":    {"rate": .18, "depth": 1., "reverb": .18, "wobble": .08, "desc": "Smooth circular"},
    "Deep Space": {"rate": .07, "depth": 1., "reverb": .40, "wobble": .15, "desc": "Slow wide pan"},
    "Fast Spin":  {"rate": .42, "depth": 1., "reverb": .10, "wobble": .05, "desc": "Rapid spin"},
    "Concert":    {"rate": .11, "depth": .8, "reverb": .50, "wobble": .12, "desc": "Live feel"},
    "Tunnel":     {"rate": .25, "depth": 1., "reverb": .60, "wobble": .20, "desc": "Heavy echo"},
    "Dreamy":     {"rate": .09, "depth": .9, "reverb": .55, "wobble": .18, "desc": "Dreamy slow"},
    "Stadium":    {"rate": .14, "depth": 1., "reverb": .65, "wobble": .10, "desc": "Stadium reverb"},
}

def make_8d(src, dst, preset="Classic", settings=None, progress_cb=None, on_complete=None, on_error=None):
    def _worker():
        try:
            ff = find_ff()
            if not ff: raise RuntimeError("ffmpeg not found")
            p = PRESETS.get(preset, PRESETS["Classic"]); s = settings or {}
            tmp = os.path.join(ED_DIR, "_tmp_" + os.path.basename(src) + ".wav")
            af = "loudnorm=I=-16:LRA=11:TP=-1.5" if s.get("normalize", True) else "anull"
            subprocess.run([ff, "-y", "-i", src, "-ar", "48000", "-ac", "2",
                            "-acodec", "pcm_s16le", "-af", af, tmp],
                           check=True, capture_output=True)
            with wave.open(tmp, "rb") as wf:
                n_ch = wf.getnchannels(); sw = wf.getsampwidth(); fps = wf.getframerate()
                frames = wf.readframes(wf.getnframes())
            fmt = f"<{len(frames) // sw}h"
            raw = list(struct.unpack(fmt, frames[:struct.calcsize(fmt)]))
            if n_ch == 1: raw = [x for x in raw for _ in range(2)]
            rsz = [int(fps * .029), int(fps * .053), int(fps * .083)]
            rbu = [[0] * z for z in rsz]; rga = [p["reverb"], p["reverb"] * .5, p["reverb"] * .25]
            ri = [0, 0, 0]; out = []; total = len(raw)
            for i in range(0, total - 1, 2):
                t = (i // 2) / fps; ang = 2 * math.pi * p["rate"] * t
                pan = (math.sin(ang) * p["depth"] + 1) / 2
                elev = 1. + p["wobble"] * math.sin(2 * math.pi * p["rate"] * .5 * t + math.pi / 4)
                shad = .72 + .28 * math.cos(ang); dist = .85 + .15 * abs(math.sin(ang * .5))
                sl = raw[i] * (1 - pan) * elev * dist; sr = raw[i + 1] * pan * elev * shad * dist
                for j in range(3):
                    idx = ri[j]
                    sl += rga[j] * rbu[j][idx]; sr += rga[j] * rbu[j][(idx + rsz[j] // 2) % rsz[j]]
                    rbu[j][idx] = int((sl + sr) * .5); ri[j] = (idx + 1) % rsz[j]
                out.extend([int(max(-32767, min(32767, sl))), int(max(-32767, min(32767, sr)))])
                if progress_cb and i % 96000 == 0:
                    val = i / total
                    Clock.schedule_once(lambda dt, v=val: progress_cb(v))
            with wave.open(dst, "wb") as wf:
                wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(fps)
                wf.writeframes(struct.pack(f"<{len(out)}h", *out))
            try: os.remove(tmp)
            except: pass
            if on_complete: Clock.schedule_once(lambda dt: on_complete(dst))
        except Exception as e:
            if on_error: Clock.schedule_once(lambda dt: on_error(e))
    threading.Thread(target=_worker, daemon=True).start()

# ── Audio ──────────────────────────────────────────────────────────────────────
class AudioPlayer:
    def __init__(self):
        self._p = None; self._src = None; self.duration = 0
        self.finished = False; self._loading = False
        self._is_android = platform == "android"
        self._poll_evt = None

    def load(self, path, on_ready=None):
        """Load audio. on_ready(success) is called on the main thread when done."""
        self.stop(); self.finished = False
        if on_ready is None:
            return self._do_load(path)
        # Non-blocking: decode in background, call on_ready on main thread
        self._loading = True
        def _bg():
            ok = self._do_load(path)
            self._loading = False
            Clock.schedule_once(lambda dt: on_ready(ok))
        threading.Thread(target=_bg, daemon=True).start()
        return None  # result delivered via on_ready

    def _do_load(self, path):
        try:
            if self._is_android:
                self._p = SoundLoader.load(path)
                if self._p:
                    self.duration = self._p.length
                    # Poller for EOS
                    if self._poll_evt: self._poll_evt.cancel()
                    self._poll_evt = Clock.schedule_interval(self._poll_eos, 0.5)
                    return True
                return False
            else:
                raw = pyglet.media.load(path)
                sz = os.path.getsize(path) if os.path.exists(path) else 0
                self._src = pyglet.media.StaticSource(raw) if sz < 50 * 1024 * 1024 else raw
                self._p = pyglet.media.Player(); self._p.queue(self._src)
                self.duration = self._src.duration or 0
                self._p.push_handlers(on_player_eos=self._eos)
                return True
        except Exception as e:
            print(f"Audio: {e}"); return False

    def _poll_eos(self, dt):
        if not self._is_android or not self._p: return False
        if self._p.state == 'stop' and self.position >= max(0.5, self.duration - 1):
            self.finished = True
        return True

    def _eos(self): self.finished = True

    def play(self):
        if self._p:
            self.finished = False; self._p.play()

    def pause(self):
        if self._p:
            if self._is_android: self._p.stop()
            else: self._p.pause()

    def stop(self):
        if self._poll_evt: self._poll_evt.cancel(); self._poll_evt = None
        if self._p:
            try:
                if self._is_android: self._p.stop(); self._p.unload()
                else: self._p.pause(); self._p.delete()
            except: pass
            self._p = None
        self.duration = 0; self.finished = False

    def seek(self, s):
        if self._p:
            try:
                self._p.seek(float(s))
            except: pass

    def set_volume(self, v):
        if self._p:
            try: self._p.volume = max(0., min(float(v), 2.))
            except: pass

    @property
    def position(self):
        try:
            if self._p:
                if self._is_android:
                    return min(self._p.get_pos(), self.duration) if self.duration else 0
                else:
                    pos = self._p.time
                    return min(pos, self.duration) if self.duration and pos else 0
            return 0
        except: return 0

    @property
    def playing(self):
        try:
            if self._p:
                if self._is_android: return self._p.state == 'play'
                else: return self._p.playing
            return False
        except: return False


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET TOOLKIT
# ══════════════════════════════════════════════════════════════════════════════

def _bg(w, cname, radius=0):
    with w.canvas.before:
        Color(*col(cname))
        if radius:
            _r = RoundedRectangle(pos=w.pos, size=w.size, radius=[dp(radius)])
        else:
            _r = Rectangle(pos=w.pos, size=w.size)
    w.bind(pos=lambda *a, r=_r: setattr(r, "pos", w.pos),
           size=lambda *a, r=_r: setattr(r, "size", w.size))


class Lbl(Label):
    """Label that always uses the app font so unicode symbols render."""
    def __init__(self, text="", cname="white", bold=False, fs=13, halign="left", **kw):
        super().__init__(**kw)
        self.font_name  = _APP_FONT
        self.text       = text
        self.color      = col(cname)
        self.bold       = bold
        self.font_size  = sp(fs)
        self.halign     = halign
        self.valign     = "middle"
        self.shorten    = True
        self.shorten_from = "right"
        self.text_size  = self.size
        self.bind(size=lambda *_: setattr(self, "text_size", self.size))


def mkbtn(text, variant="primary", on_press=None, radius=24, fs=13, **kw):
    kw.setdefault("size_hint_y", None); kw.setdefault("height", dp(48))
    BG = {"primary": col("green"), "secondary": col("card2"),
          "ghost": col("card"), "danger": col("red"), "chip": col("card3")}
    FG = {"primary": (0, 0, 0, 1), "secondary": col("white"),
          "ghost": col("lgrey"), "danger": col("white"), "chip": col("white")}
    bg = BG.get(variant, col("green"))
    fg = FG.get(variant, col("white"))
    btn = Button(text=text, background_normal="", background_color=(0, 0, 0, 0),
                 color=list(fg), font_size=sp(fs), font_name=_APP_FONT, bold=True, **kw)
    with btn.canvas.before:
        _c = Color(*bg)
        _r = RoundedRectangle(pos=btn.pos, size=btn.size, radius=[dp(radius)])
    btn.bind(pos=lambda *a, r=_r: setattr(r, "pos", btn.pos),
             size=lambda *a, r=_r: setattr(r, "size", btn.size))
    if on_press:
        btn.bind(on_press=lambda inst: on_press())
    return btn


def mkicon(symbol, fg="white", bg=None, size_px=36, on_press=None, **kw):
    """Icon button — resolves semantic name via ICO dict, uses app font."""
    sym = ICO.get(symbol, symbol)
    kw.setdefault("size_hint", (None, None))
    kw.setdefault("size", (dp(size_px), dp(size_px)))
    # INCREASED multiplier from 0.46 to 0.60 to make the icons visually larger!
    btn = Button(text=sym, background_normal="", background_color=(0, 0, 0, 0),
                 color=list(col(fg)), font_size=sp(size_px * 0.60),
                 font_name=_APP_FONT, **kw)
    if bg:
        with btn.canvas.before:
            _c = Color(*col(bg))
            _e = Ellipse(pos=btn.pos, size=btn.size)
        btn.bind(pos=lambda *a, e=_e: setattr(e, "pos", btn.pos),
                 size=lambda *a, e=_e: setattr(e, "size", btn.size))
    if on_press:
        btn.bind(on_press=lambda inst: on_press())
    return btn


class SInput(TextInput):
    def __init__(self, hint="", **kw):
        super().__init__(**kw)
        self.background_normal = ""
        self.background_active = ""
        self.background_color  = col("card2")
        self.foreground_color  = list(col("white"))
        self.hint_text_color   = list(col("mgrey"))
        self.cursor_color      = list(col("green"))
        self.font_size         = sp(14)
        self.font_name         = _APP_FONT
        self.padding           = [dp(16), dp(12)]
        self.multiline         = False
        self.hint_text         = hint


class ArtThumb(FloatLayout):
    def __init__(self, url="", size_px=56, **kw):
        kw.setdefault("size_hint", (None, None))
        kw.setdefault("size", (dp(size_px), dp(size_px)))
        super().__init__(**kw)
        self._spx = size_px; self._cr = dp(size_px * 0.15)
        with self.canvas:
            Color(*col("card3"))
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[self._cr])
        self._ph = Label(text=ICO["dot"], font_name=_APP_FONT,
                         font_size=sp(size_px * 0.28),
                         color=list(col("mgrey")), size_hint=(1, 1))
        self.add_widget(self._ph)
        self.bind(pos=self._upd, size=self._upd)
        if url:
            threading.Thread(target=self._fetch, args=(url,), daemon=True).start()

    def _upd(self, *_): self._bg.pos = self.pos; self._bg.size = self.size

    def _fetch(self, url):
        try:
            r = _req.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200: return
            try:
                img = PilImage.open(BytesIO(r.content)).convert("RGBA")
                px = max(4, int(dp(self._spx))); img = img.resize((px, px), PilImage.LANCZOS)
                data = img.tobytes()
                Clock.schedule_once(lambda dt, d=data, s=px: self._apply(d, s))
            except Exception as e:
                print(f"PIL Image Error: {e}")
        except: pass

    def _apply(self, data, s):
        try:
            tex = Texture.create(size=(s, s), colorfmt="rgba")
            tex.blit_buffer(data, colorfmt="rgba", bufferfmt="ubyte")
            tex.flip_vertical()
            self.canvas.clear()
            with self.canvas:
                Color(1, 1, 1, 1)
                self._bg = RoundedRectangle(texture=tex, pos=self.pos,
                                            size=self.size, radius=[self._cr])
            try: self.remove_widget(self._ph)
            except: pass
        except: pass


def snack(msg, dur=2.5):
    if not msg: return
    # Use our custom Lbl to guarantee reliable text rendering
    lbl = Lbl(str(msg), fs=12, halign="center")
    lbl.size_hint = (None, None)
    lbl.texture_update()
    w = max(lbl.texture_size[0] + dp(48), dp(200)); h = dp(42)
    lbl.size = (w, h)
    lbl.text_size = (w - dp(24), None)
    
    wrap = FloatLayout(size_hint=(None, None), size=(w, h))
    with wrap.canvas.before:
        Color(*col("card2"))
        _r = RoundedRectangle(pos=wrap.pos, size=wrap.size, radius=[dp(21)])
    wrap.bind(pos=lambda *a, r=_r: setattr(r, "pos", wrap.pos),
              size=lambda *a, r=_r: setattr(r, "size", wrap.size))
    
    wrap.add_widget(lbl)
    def _pos(*_): wrap.pos = (Window.width / 2 - w / 2, dp(110))
    _pos(); Window.bind(size=_pos)
    wrap.opacity = 0; Window.add_widget(wrap)
    Animation(opacity=1, duration=.20).start(wrap)
    def _rm(*_):
        Window.unbind(size=_pos)
        try: Window.remove_widget(wrap)
        except: pass
    a = Animation(opacity=0, duration=.25); a.bind(on_complete=_rm)
    Clock.schedule_once(lambda dt: a.start(wrap), dur)


def confirm_dlg(title, msg, on_yes, danger=False):
    box = BoxLayout(orientation="vertical", spacing=dp(14), padding=dp(22))
    _bg(box, "card2", 20)
    box.add_widget(Lbl(title, bold=True, fs=17, halign="center",
                       size_hint_y=None, height=dp(28)))
    box.add_widget(Lbl(msg, cname="lgrey", fs=12, halign="center",
                       size_hint_y=None, height=dp(38)))
    btns = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(12))
    cancel = mkbtn("Cancel", "ghost", size_hint=(1, None), height=dp(50), radius=25)
    ok = mkbtn("Delete" if danger else "OK",
               "danger" if danger else "primary",
               size_hint=(1, None), height=dp(50), radius=25)
    btns.add_widget(cancel); btns.add_widget(ok); box.add_widget(btns)
    box.size_hint_y = None; box.height = dp(178)
    pop = Popup(title="", content=box, size_hint=(None, None), size=(dp(340), dp(214)),
                separator_height=0, background_color=(0, 0, 0, .92))
    cancel.bind(on_press=lambda *_: pop.dismiss())
    def _y(): pop.dismiss(); on_yes()
    ok.bind(on_press=lambda *_: _y()); pop.open()


def input_dlg(title, hint, on_ok):
    box = BoxLayout(orientation="vertical", spacing=dp(14), padding=dp(22))
    _bg(box, "card2", 20)
    box.add_widget(Lbl(title, bold=True, fs=17, halign="center",
                       size_hint_y=None, height=dp(28)))
    entry = SInput(hint=hint, size_hint_y=None, height=dp(52))
    box.add_widget(entry)
    btns = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(12))
    cb = mkbtn("Cancel", "ghost", size_hint=(1, None), height=dp(50), radius=25)
    ob = mkbtn("OK", "primary", size_hint=(1, None), height=dp(50), radius=25)
    btns.add_widget(cb); btns.add_widget(ob); box.add_widget(btns)
    box.size_hint_y = None; box.height = dp(196)
    pop = Popup(title="", content=box, size_hint=(None, None), size=(dp(340), dp(234)),
                separator_height=0, background_color=(0, 0, 0, .92))
    cb.bind(on_press=lambda *_: pop.dismiss())
    def _ok():
        v = entry.text.strip(); pop.dismiss()
        if v: on_ok(v)
    ob.bind(on_press=lambda *_: _ok())
    pop.open()


def welcome_dlg(app):
    box = BoxLayout(orientation="vertical", spacing=dp(14), padding=dp(22))
    _bg(box, "card2", 20)
    box.add_widget(Lbl("🎉 Welcome to 8DStud Alpha!", bold=True, fs=16, halign="center",
                       size_hint_y=None, height=dp(30)))
    msg = ("Thank you for trying out this early alpha version!\n\n"
           "Since we're still building and improving, you might run into some bugs. "
           "We'd love your feedback—please reach out to me on Discord at "
           "[color=4ade80]@zooweemama0001[/color] "
           "to report issues, suggest features, or just say hi!")
    lbl = Lbl(msg, cname="lgrey", fs=13, halign="center")
    lbl.markup = True
    lbl.shorten = False  # Allows the text to flow into a paragraph
    box.add_widget(lbl)
    btn = mkbtn("Let's Go!", "primary", size_hint=(1, None), height=dp(50), radius=25)
    box.add_widget(btn)
    box.size_hint_y = None; box.height = dp(240)
    pop = Popup(title="", content=box, size_hint=(None, None), size=(dp(340), dp(280)),
                separator_height=0, background_color=(0, 0, 0, .92), auto_dismiss=False)
    def _ok(*_):
        app.settings["welcome_shown"] = True
        _sj(ST_FILE, app.settings)
        pop.dismiss()
    btn.bind(on_press=_ok)
    pop.open()


# ── NAV-SAFE ScrollView ───────────────────────────────────────────────────────
# Kivy's default ScrollView holds touch grab even after the finger lifts,
# which blocks the BottomNav from receiving the next touch. This subclass
# releases the grab immediately on touch_up so nav always works.
class SafeScrollView(ScrollView):
    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
        return super().on_touch_up(touch)


def mk_sv(spacing=6):
    sc = SafeScrollView(do_scroll_x=False, size_hint=(1, 1))
    inner = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(spacing))
    inner.bind(minimum_height=inner.setter("height"))
    sc.add_widget(inner); return sc, inner


def sep_line():
    w = Widget(size_hint_y=None, height=dp(1))
    with w.canvas:
        Color(*col("sep")); _r = Rectangle(pos=w.pos, size=w.size)
    w.bind(pos=lambda *a, r=_r: setattr(r, "pos", w.pos),
           size=lambda *a, r=_r: setattr(r, "size", w.size))
    return w


# ── iOS-style pill toggle ──────────────────────────────────────────────────────
class PillToggle(Widget):
    def __init__(self, active=False, **kw):
        kw.setdefault("size_hint", (None, None)); kw.setdefault("size", (dp(52), dp(30)))
        super().__init__(**kw)
        self._cbs = []; self._active = active; self._ax = 1.0 if active else 0.0
        self.bind(pos=self._draw, size=self._draw)
        Clock.schedule_once(lambda dt: self._draw(), .05)

    def _draw(self, *_):
        self.canvas.clear()
        x, y = self.pos; w, h = self.size; r = h / 2
        with self.canvas:
            Color(*col("green" if self._active else "card3"))
            RoundedRectangle(pos=(x, y), size=(w, h), radius=[r])
            Color(1, 1, 1, 1)
            kx = x + (w - h) * self._ax + dp(2); ky = y + dp(2); ks = h - dp(4)
            Ellipse(pos=(kx, ky), size=(ks, ks))

    def bind(self, **kw):
        if "active" in kw: self._cbs.append(kw.pop("active"))
        if kw: super().bind(**kw)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._active = not self._active
            t = 1.0 if self._active else 0.0
            a = Animation(_ax=t, duration=0.2, t="out_cubic")
            a.bind(on_progress=lambda *_: self._draw(),
                   on_complete=lambda *_: self._draw())
            a.start(self)
            for cb in self._cbs: cb(self, self._active)
            return True
        return super().on_touch_down(touch)


# ── Custom seek slider ─────────────────────────────────────────────────────────
class SeekBar(Widget):
    def __init__(self, **kw):
        kw.setdefault("size_hint_y", None); kw.setdefault("height", dp(20))
        super().__init__(**kw)
        self._frac = 0.0; self._dragging = False; self._on_seek = None
        self.bind(pos=self._draw, size=self._draw)

    def set_frac(self, f):
        self._frac = max(0., min(1., f))
        if not self._dragging: self._draw()

    def _draw(self, *_):
        self.canvas.clear()
        x, y = self.pos; w, h = self.size; cy = y + h / 2; th = dp(3)
        fill = w * self._frac
        with self.canvas:
            Color(*col("card3"))
            RoundedRectangle(pos=(x, cy - th / 2), size=(w, th), radius=[th / 2])
            Color(*col("green"))
            if fill > 0:
                RoundedRectangle(pos=(x, cy - th / 2), size=(fill, th), radius=[th / 2])
            tr = dp(7); Color(1, 1, 1, 1)
            Ellipse(pos=(x + fill - tr, cy - tr), size=(tr * 2, tr * 2))

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._dragging = True; self._set(touch.x); return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._dragging: self._set(touch.x); return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self._dragging:
            self._dragging = False
            if self._on_seek: self._on_seek(self._frac)
            return True
        return super().on_touch_up(touch)

    def _set(self, tx):
        x = self.pos[0]; w = self.size[0]
        self._frac = max(0., min((tx - x) / w, 1.)) if w > 0 else 0
        self._draw()
        if self._on_seek: self._on_seek(self._frac)


# ══════════════════════════════════════════════════════════════════════════════
# DRAWER
# ══════════════════════════════════════════════════════════════════════════════
class Drawer(FloatLayout):
    def __init__(self, **kw):
        super().__init__(**kw); self._open = False
        self._dim = Button(size_hint=(None, None), size=(Window.width, Window.height),
                           background_normal="", background_color=(0, 0, 0, .65), opacity=0)
        Window.bind(size=lambda inst, v: setattr(self._dim, "size", v))
        self._dim.bind(on_press=lambda *_: self.close())
        self._panel = BoxLayout(orientation="vertical", size_hint=(None, None),
                                width=dp(285), height=Window.height, x=-dp(285), y=0)
        Window.bind(size=lambda inst, v: (
            setattr(self._panel, "height", v[1]), setattr(self._panel, "y", 0)))
        with self._panel.canvas.before:
            Color(*col("bg2"))
            _r = Rectangle(pos=self._panel.pos, size=self._panel.size)
        self._panel.bind(pos=lambda *a, r=_r: setattr(r, "pos", self._panel.pos),
                         size=lambda *a, r=_r: setattr(r, "size", self._panel.size))
        self._fill()

    def _fill(self):
        p = self._panel; p.clear_widgets()
        p.add_widget(Widget(size_hint_y=None, height=dp(52)))
        br = BoxLayout(size_hint_y=None, height=dp(58), padding=[dp(20), dp(4)])
        br.add_widget(Lbl("8DStud", cname="green", bold=True, fs=26))
        p.add_widget(br); p.add_widget(sep_line())
        p.add_widget(Widget(size_hint_y=None, height=dp(8)))
        # Removed "Recently Played" and "Queue" from drawer
        items = [("Liked Songs", "liked"), ("Playlists", "playlists"),
                 ("8D Converter", "eightd"), ("Settings", "settings")]
        for label, screen in items:
            btn = Button(text=f"  {label}", halign="left", valign="middle",
                         background_normal="", background_color=(0, 0, 0, 0),
                         color=list(col("white")), font_size=sp(15),
                         font_name=_APP_FONT,
                         size_hint=(1, None), height=dp(52))
            btn.text_size = (dp(265), dp(52))
            btn.bind(on_press=lambda *_, s=screen: self._go(s))
            p.add_widget(btn)
        p.add_widget(Widget())
        ver = BoxLayout(size_hint_y=None, height=dp(36), padding=[dp(20), 0])
        ver.add_widget(Lbl("v8.3 by PK", cname="dgrey", fs=10))
        p.add_widget(ver)

    def _go(self, screen):
        self.close()
        Clock.schedule_once(lambda dt: App.get_running_app().nav_to(screen), .24)

    def open(self):
        if self._open: return
        self._open = True
        Window.add_widget(self._dim); self._panel.x = -dp(285)
        Window.add_widget(self._panel); self._dim.opacity = 0
        Animation(opacity=.65, duration=.20).start(self._dim)
        Animation(x=0, duration=.26, t="out_cubic").start(self._panel)

    def close(self):
        if not self._open: return
        self._open = False
        def _rm(*_):
            try: Window.remove_widget(self._dim)
            except: pass
            try: Window.remove_widget(self._panel)
            except: pass
        Animation(opacity=0, duration=.16).start(self._dim)
        a = Animation(x=-dp(285), duration=.22, t="in_cubic")
        a.bind(on_complete=_rm); a.start(self._panel)

    def toggle(self): self.open() if not self._open else self.close()


# ══════════════════════════════════════════════════════════════════════════════
# NOW PLAYING BAR
# ══════════════════════════════════════════════════════════════════════════════
class NowBar(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", size_hint_y=None, height=dp(162), **kw)
        _bg(self, "bg2")
        self.add_widget(sep_line())

        # Seek bar + time labels
        seek_wrap = BoxLayout(size_hint_y=None, height=dp(26),
                              padding=[dp(14), dp(4), dp(14), dp(0)])
        self._seek = SeekBar(size_hint=(1, 1))
        def _on_seek(frac):
            a = App.get_running_app(); dur = a.audio.duration
            if dur:
                pos = frac * dur; a.audio.seek(pos)
                a._secs_remaining = max(.5, dur - pos)
                a._schedule_autoplay(a._secs_remaining)
        self._seek._on_seek = _on_seek
        seek_wrap.add_widget(self._seek); self.add_widget(seek_wrap)

        # Time labels row
        trow = BoxLayout(size_hint_y=None, height=dp(14),
                         padding=[dp(14), 0, dp(14), 0])
        self.time_l = Lbl("0:00", cname="mgrey", fs=9, halign="left",
                          size_hint=(None, 1), width=dp(32))
        self.dur_l  = Lbl("0:00", cname="mgrey", fs=9, halign="right",
                          size_hint=(None, 1), width=dp(32))
        trow.add_widget(self.time_l); trow.add_widget(Widget()); trow.add_widget(self.dur_l)
        self.add_widget(trow)

        # Info row: big album art + title/artist
        info = BoxLayout(size_hint_y=None, height=dp(72),
                         padding=[dp(12), dp(4), dp(10), dp(4)], spacing=dp(12))
        self.art = ArtThumb(size_px=64)
        self._art_box = info
        info.add_widget(self.art)
        meta = BoxLayout(orientation="vertical", size_hint=(1, 1))
        self.title_l  = Lbl("Nothing playing", bold=True, fs=15,
                            size_hint_y=None, height=dp(26))
        self.artist_l = Lbl("", cname="lgrey", fs=12, size_hint_y=None, height=dp(18))
        meta.add_widget(self.title_l); meta.add_widget(self.artist_l)
        info.add_widget(meta); self.add_widget(info)

        # Controls row
        anchor = AnchorLayout(anchor_x="center", anchor_y="center",
                              size_hint_y=None, height=dp(52))
        ctrl = BoxLayout(orientation="horizontal", size_hint=(None, None),
                         width=dp(310), height=dp(52), spacing=dp(4))
        self.like_btn = mkicon("unlike", "lgrey", size_px=36,
                               on_press=lambda: App.get_running_app()._toggle_like_cur())
        self.prev_btn = mkicon("prev",    "white", size_px=42,
                               on_press=lambda: App.get_running_app()._prev())
        self.play_btn = mkicon("play",    "black", bg="green", size_px=52,
                               on_press=lambda: App.get_running_app()._toggle_play())
        self.next_btn = mkicon("next",    "white", size_px=42,
                               on_press=lambda: App.get_running_app()._next())
        self.shuf_btn = mkicon("shuffle", "mgrey", size_px=36,
                               on_press=self._toggle_shuf)
        for b in [self.like_btn, self.prev_btn, self.play_btn,
                  self.next_btn, self.shuf_btn]:
            ctrl.add_widget(b)
        anchor.add_widget(ctrl); self.add_widget(anchor)

        Clock.schedule_interval(self._tick,  .35)
        Clock.schedule_interval(self._ptick, 1 / 30)
        Clock.schedule_interval(self._poll,  .2)

    def _ptick(self, dt):
        try: pyglet.clock.tick()
        except: pass

    def _tick(self, dt):
        a = App.get_running_app()
        pos = a.audio.position; dur = a.audio.duration
        if dur and dur > 0:
            self._seek.set_frac(pos / dur)
            self.time_l.text = fmt_t(pos); self.dur_l.text = fmt_t(dur)
            if dur > 2 and pos > 0 and (dur - pos) < 0.8:
                if not a._end_triggered and not a._skip_flag and a.cur_meta:
                    a._end_triggered = True
                    Clock.schedule_once(lambda dt: a._on_track_end(), 0.9)
        if a.audio.finished and not a._skip_flag and a.cur_meta:
            a.audio.finished = False
            if not a._end_triggered:
                a._end_triggered = True
                a._on_track_end()

    def _poll(self, dt):
        a = App.get_running_app()
        try:
            a._autoplay_q.get_nowait()
            if not a._skip_flag and a.cur_meta and not a._end_triggered:
                a._end_triggered = True; a._on_track_end()
        except _queue.Empty: pass

    def _toggle_shuf(self):
        a = App.get_running_app(); a.settings["shuffle"] = not a.settings["shuffle"]
        self.shuf_btn.color = list(col("green") if a.settings["shuffle"] else col("mgrey"))

    def update_meta(self, title, artist, liked=False, art_url=""):
        self.title_l.text = title; self.artist_l.text = artist
        self.like_btn.text  = ICO["like"] if liked else ICO["unlike"]
        self.like_btn.color = list(col("green") if liked else col("lgrey"))
        try: self._art_box.remove_widget(self.art)
        except: pass
        self.art = ArtThumb(url=art_url, size_px=64)  # prominent 64px art
        self._art_box.add_widget(self.art, index=len(self._art_box.children))

    def set_playing(self, playing):
        self.play_btn.text = ICO["pause"] if playing else ICO["play"]


# ══════════════════════════════════════════════════════════════════════════════
# BOTTOM NAV
# ══════════════════════════════════════════════════════════════════════════════
class BottomNav(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(60), **kw)
        _bg(self, "bg2")
        with self.canvas.before:
            Color(*col("sep"))
            _l = Rectangle(pos=self.pos, size=(self.width, dp(1)))
        self.bind(pos=lambda *a, r=_l: setattr(r, "pos", self.pos),
                  size=lambda *a, r=_l: setattr(r, "size", (self.width, dp(1))))
        self._tabs = {}
        ham = Button(text=ICO["menu"], font_size=sp(22), bold=True,
                     font_name=_APP_FONT,
                     background_normal="", background_color=(0, 0, 0, 0),
                     color=list(col("lgrey")), size_hint=(None, 1), width=dp(54))
        ham.bind(on_press=lambda *_: App.get_running_app().toggle_drawer())
        self.add_widget(ham)
        for symbol, label, screen in [
            ("H", "Home",    "home"),
            ("S", "Search",  "search"),
            ("L", "Library", "library"),
        ]:
            cb = BoxLayout(orientation="vertical", size_hint=(1, 1), padding=[0, dp(6)])
            ib = Button(text=symbol, font_size=sp(18), bold=True,
                        font_name=_APP_FONT,
                        background_normal="", background_color=(0, 0, 0, 0),
                        color=list(col("mgrey")), size_hint=(1, None), height=dp(28))
            ib.bind(on_press=lambda *_, s=screen: App.get_running_app().nav_to(s))
            lb = Label(text=label, font_size=sp(9), font_name=_APP_FONT,
                       color=list(col("mgrey")), size_hint=(1, None), height=dp(14))
            cb.add_widget(ib); cb.add_widget(lb)
            self.add_widget(cb)
            self._tabs[screen] = (ib, lb)

    def set_active(self, screen):
        for s, (b, l) in self._tabs.items():
            c = list(col("green") if s == screen else col("mgrey"))
            b.color = c; l.color = c


# ══════════════════════════════════════════════════════════════════════════════
# BASE SCREEN
# ══════════════════════════════════════════════════════════════════════════════
class Base(Screen):
    def __init__(self, **kw): super().__init__(**kw); _bg(self, "bg")

    @property
    def app(self): return App.get_running_app()

    def top_bar(self, title, cname="white", right_widget=None, back_screen=None):
        bar = BoxLayout(size_hint_y=None, height=dp(56),
                        padding=[dp(14), dp(6), dp(12), dp(4)], spacing=dp(8))
        _bg(bar, "bg2")
        if back_screen:
            bb = Button(text=ICO["back"], font_size=sp(22), bold=True,
                        font_name=_APP_FONT,
                        background_normal="", background_color=(0, 0, 0, 0),
                        color=list(col("lgrey")), size_hint=(None, 1), width=dp(36))
            bb.bind(on_press=lambda *_: self.app.nav_to(back_screen))
            bar.add_widget(bb)
        bar.add_widget(Lbl(title, bold=True, fs=20, cname=cname, size_hint=(1, 1)))
        if right_widget: bar.add_widget(right_widget)
        return bar

    def song_row(self, fname, idx, on_play, accent="white", on_del=None):
        """
        Plain BoxLayout row — no touch bindings on the container itself.
        Only the explicit Button widgets handle touches.
        """
        a = self.app
        is_cur = a.cur_meta.get("path", "") in [
            os.path.join(DL_DIR, fname), os.path.join(ED_DIR, fname)]
        liked = fname in a.liked
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(68),
                        padding=[dp(12), dp(8), dp(8), dp(8)], spacing=dp(10))
        with row.canvas.before:
            Color(*col("card2" if not is_cur else "card"))
            _r = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(16)])
        row.bind(pos=lambda *a, r=_r: setattr(r, "pos", row.pos),
                 size=lambda *a, r=_r: setattr(r, "size", row.size))
        # playing indicator / index number
        row.add_widget(Lbl(ICO["play"] if is_cur else str(idx + 1),
                           cname="green" if is_cur else "mgrey",
                           fs=12, halign="center", size_hint=(None, 1), width=dp(24)))
        nb = BoxLayout(orientation="vertical", size_hint=(1, 1))
        pc = a.playcounts.get(fname, 0)
        nb.add_widget(Lbl(os.path.splitext(fname)[0],
                          cname=accent if is_cur else "white", bold=is_cur,
                          fs=14, size_hint_y=None, height=dp(24)))
        nb.add_widget(Lbl(f"{pc} plays" if pc else "",
                          cname="mgrey", fs=10, size_hint_y=None, height=dp(14)))
        row.add_widget(nb)

        def _like(fn=fname):
            if fn in a.liked: a.liked.discard(fn)
            else: a.liked.add(fn)
            _sj(LK_FILE, list(a.liked))
            Clock.schedule_once(lambda dt: self.on_enter(), 0)

        row.add_widget(mkicon("like" if liked else "unlike",
                              "green" if liked else "mgrey",
                              size_px=34, on_press=_like))
        if on_del:
            row.add_widget(mkicon("close", "mgrey", size_px=30, on_press=on_del))
        row.add_widget(mkicon("pause" if is_cur else "play",
                              "black" if is_cur else "green",
                              bg="green" if is_cur else None,
                              size_px=44, on_press=on_play))
        return row


# ══════════════════════════════════════════════════════════════════════════════
# HOME
# ══════════════════════════════════════════════════════════════════════════════
class HomeScreen(Base):
    name = "home"

    def on_enter(self):
        self.clear_widgets()
        root = BoxLayout(orientation="vertical"); _bg(root, "bg")
        a = self.app
        h = int(time.strftime("%H"))
        greet = "Good morning" if h < 12 else ("Good afternoon" if h < 18 else "Good evening")
        hdr = BoxLayout(size_hint_y=None, height=dp(64),
                        padding=[dp(18), dp(10), dp(14), dp(8)])
        _bg(hdr, "bg2")
        left = BoxLayout(orientation="vertical", size_hint=(1, 1))
        left.add_widget(Lbl(greet, bold=True, fs=22, size_hint_y=None, height=dp(30)))
        left.add_widget(Lbl("8DStud", cname="lgrey", fs=12, size_hint_y=None, height=dp(20)))
        hdr.add_widget(left)
        hdr.add_widget(Button(text=ICO["menu"], font_size=sp(22), bold=True,
                              font_name=_APP_FONT,
                              background_normal="", background_color=(0, 0, 0, 0),
                              color=list(col("lgrey")), size_hint=(None, 1), width=dp(44),
                              on_press=lambda *_: a.toggle_drawer()))
        root.add_widget(hdr)
        sc, inner = mk_sv(spacing=14)
        inner.padding = [dp(14), dp(14), dp(14), dp(20)]
        fav = a.settings.get("fav_playlist", "")
        if fav not in a.playlists: fav = ""
        inner.add_widget(Lbl("Your Playlists", bold=True, fs=16,
                              size_hint_y=None, height=dp(30)))
        tile_row = BoxLayout(orientation="horizontal", size_hint_y=None,
                             height=dp(110), spacing=dp(10))
        tile_row.add_widget(self._pl_tile(ED_PL, "green"))
        if fav: tile_row.add_widget(self._pl_tile(fav, "lgrey"))
        inner.add_widget(tile_row)
        # Recently played section (simple inline, no separate screen)
        if a.recently_played:
            inner.add_widget(Lbl("Recently Played", bold=True, fs=16,
                                 size_hint_y=None, height=dp(32)))
            for i, e in enumerate(a.recently_played[:6]):
                inner.add_widget(self._mini(e["fname"], i + 1,
                    lambda fn=e["fname"]: a._play_from_lib(fn), sub=e["time"]))
        else:
            inner.add_widget(Lbl("Search and download your first song!",
                                 cname="lgrey", fs=13, halign="center",
                                 size_hint_y=None, height=dp(80)))
        root.add_widget(sc); self.add_widget(root)

    def _pl_tile(self, name, cc, **kw):
        songs = self.app.playlists.get(name, [])
        card = BoxLayout(orientation="vertical", padding=[dp(14), dp(12)], size_hint=(1, 1))
        with card.canvas.before:
            Color(*[v * .28 for v in col(cc)[:3]] + [1])
            _r = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(18)])
        card.bind(pos=lambda *a, r=_r: setattr(r, "pos", card.pos),
                  size=lambda *a, r=_r: setattr(r, "size", card.size))
        card.add_widget(Lbl(name, bold=True, fs=14, size_hint_y=None, height=dp(24)))
        card.add_widget(Lbl(f"{len(songs)} songs", cname="lgrey", fs=11,
                            size_hint_y=None, height=dp(18)))
        card.add_widget(Widget(size_hint_y=None, height=dp(4)))
        card.add_widget(mkbtn("Play", "primary",
                               on_press=lambda n=name: self.app._play_playlist(n),
                               size_hint=(None, None), width=dp(80), height=dp(36), radius=18))
        return card

    def _mini(self, fname, num, cmd, sub=""):
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(56),
                        padding=[dp(12), dp(8)], spacing=dp(10))
        with row.canvas.before:
            Color(*col("card2"))
            _r = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(14)])
        row.bind(pos=lambda *a, r=_r: setattr(r, "pos", row.pos),
                 size=lambda *a, r=_r: setattr(r, "size", row.size))
        if num is not None:
            row.add_widget(Lbl(str(num), cname="mgrey", fs=11, halign="center",
                               size_hint=(None, 1), width=dp(20)))
        nb = BoxLayout(orientation="vertical", size_hint=(1, 1))
        nb.add_widget(Lbl(os.path.splitext(fname)[0], fs=13,
                          size_hint_y=None, height=dp(22)))
        if sub: nb.add_widget(Lbl(sub, cname="mgrey", fs=10,
                                  size_hint_y=None, height=dp(14)))
        row.add_widget(nb)
        row.add_widget(mkicon("play", "green", size_px=36, on_press=cmd))
        return row


# ══════════════════════════════════════════════════════════════════════════════
# SEARCH
# ══════════════════════════════════════════════════════════════════════════════
class SearchScreen(Base):
    name = "search"

    def on_enter(self):
        self.clear_widgets()
        root = BoxLayout(orientation="vertical"); _bg(root, "bg")
        root.add_widget(self.top_bar("Search"))
        bar = BoxLayout(size_hint_y=None, height=dp(62),
                        padding=[dp(12), dp(8)], spacing=dp(8))
        _bg(bar, "bg2")
        self.entry = SInput(hint="Artists, songs...", size_hint=(1, None), height=dp(46))
        self.entry.bind(on_text_validate=lambda *_: self._search())
        bar.add_widget(self.entry)
        bar.add_widget(mkbtn("Go", "primary", on_press=self._search,
                             size_hint=(None, None), width=dp(64), height=dp(46), radius=23))
        root.add_widget(bar)
        # ⚠️ Caution banner
        warn = BoxLayout(size_hint_y=None, height=dp(38),
                         padding=[dp(14), dp(6)], spacing=dp(8))
        with warn.canvas.before:
            Color(0.55, 0.38, 0.06, 1)   # amber tint
            RoundedRectangle(pos=warn.pos, size=warn.size, radius=[dp(8)])
        warn.bind(pos=lambda *a, w=warn: None, size=lambda *a, w=warn: None)
        # redraw warn bg on pos/size changes
        def _warn_draw(*_):
            warn.canvas.before.clear()
            with warn.canvas.before:
                Color(0.25, 0.18, 0.02, 1)
                RoundedRectangle(pos=warn.pos, size=warn.size, radius=[dp(8)])
        warn.bind(pos=_warn_draw, size=_warn_draw)
        warn.add_widget(Lbl("⚠ Songs only — avoid playlists & long videos",
                            cname="white", fs=11, halign="center", size_hint=(1, 1)))
        root.add_widget(warn)
        self.status = Lbl("Type to search YouTube", cname="mgrey", fs=12,
                          halign="center", size_hint_y=None, height=dp(30))
        root.add_widget(self.status)
        sc, self.res = mk_sv(spacing=8)
        self.res.padding = [dp(12), dp(4), dp(12), dp(12)]
        root.add_widget(sc); self.add_widget(root)

    def _search(self, *_):
        q = self.entry.text.strip()
        if not q: return
        self.status.text = "Searching..."
        for w in list(self.res.children): self.res.remove_widget(w)
        threading.Thread(target=self._task, args=(q,), daemon=True).start()

    def _task(self, q):
        try:
            tracks = search_yt(q)
            Clock.schedule_once(lambda dt: self._show(tracks))
        except Exception as e:
            Clock.schedule_once(lambda dt, err=str(e):
                setattr(self.status, "text", f"Error: {err[:50]}"))

    def _show(self, tracks):
        self.status.text = f"{len(tracks)} results"
        for w in list(self.res.children): self.res.remove_widget(w)
        for t in tracks: self.res.add_widget(self._card(t))

    def _card(self, track):
        card = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(80),
                         padding=[dp(10), dp(10)], spacing=dp(12))
        with card.canvas.before:
            Color(*col("card2"))
            _r = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(16)])
        card.bind(pos=lambda *a, r=_r: setattr(r, "pos", card.pos),
                  size=lambda *a, r=_r: setattr(r, "size", card.size))
        card.add_widget(ArtThumb(url=track.get("art_url", ""), size_px=56))
        info = BoxLayout(orientation="vertical", size_hint=(1, 1))
        info.add_widget(Lbl(track["title"], bold=True, fs=13,
                            size_hint_y=None, height=dp(22)))
        info.add_widget(Lbl(f"{track['artist']}  {fmt_t(track['duration'])}",
                            cname="lgrey", fs=11, size_hint_y=None, height=dp(18)))
        card.add_widget(info)
        dl = mkbtn("DL", "primary", size_hint=(None, None),
                   width=dp(54), height=dp(50), radius=25)
        dl.bind(on_press=lambda *_, t=track, b=dl: self._dl(t, b))
        card.add_widget(dl)
        return card

    def _dl(self, track, btn):
        btn.text = "..."; btn.disabled = True
        snack("Downloading...")
        threading.Thread(target=self._download, args=(track, btn), daemon=True).start()

    def _download(self, track, btn):
        try:
            from kivy.utils import platform
            import yt_dlp
            
            # Subprocesses for yt-dlp are unstable on Android. Use pure python instead.
            opts = {
                "format": "bestaudio/best",
                "outtmpl": os.path.join(DL_DIR, "%(title)s.%(ext)s"),
                "noplaylist": True,
                "writeinfojson": True,
                "quiet": True,
                "extractor_args": {"youtube": {"player_client": ["android", "web"]}}
            }
            
            if platform != "android":
                # Convert to mp3 if we have desktop ffmpeg
                opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",
                }]
                ff = find_ff()
                if ff:
                    opts["ffmpeg_location"] = ff

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"ytsearch1:{track['query']}"])
                
            Clock.schedule_once(lambda dt: (
                setattr(btn, "text", "OK"),
                setattr(btn, "disabled", False),
                snack("Saved: " + track["title"][:24])))
        except Exception as e:
            Clock.schedule_once(lambda dt: (
                setattr(btn, "text", "DL"), setattr(btn, "disabled", False),
                snack(f"Error: {str(e)[:35]}")))


# ══════════════════════════════════════════════════════════════════════════════
# LIBRARY
# ══════════════════════════════════════════════════════════════════════════════
class LibraryScreen(Base):
    name = "library"

    def on_enter(self):
        self.clear_widgets()
        root = BoxLayout(orientation="vertical"); _bg(root, "bg")
        files = self.app._get_files()
        try:
            mb = sum(os.path.getsize(os.path.join(DL_DIR, f)) for f in files
                     if os.path.exists(os.path.join(DL_DIR, f))) // (1024 * 1024)
        except: mb = 0
        bar = BoxLayout(size_hint_y=None, height=dp(56),
                        padding=[dp(14), dp(6), dp(10), dp(4)], spacing=dp(8))
        _bg(bar, "bg2")
        bar.add_widget(Lbl("Library", bold=True, fs=20, size_hint=(1, 1)))
        bar.add_widget(Lbl(f"{len(files)} songs  {mb}MB", cname="mgrey", fs=10,
                           halign="right", size_hint=(None, 1), width=dp(100)))
        bar.add_widget(mkicon("play", "black", bg="green", size_px=36,
                               on_press=self._play_all))
        bar.add_widget(mkicon("shuffle", "green", size_px=36,
                               on_press=self._shuffle))
        root.add_widget(bar)
        fi = BoxLayout(size_hint_y=None, height=dp(54), padding=[dp(12), dp(8)])
        _bg(fi, "bg2")
        self.fi = SInput(hint="Filter songs...", size_hint=(1, None), height=dp(38))
        self.fi.bind(text=lambda inst, v: self._refresh(v))
        fi.add_widget(self.fi); root.add_widget(fi)
        sc, self.lb = mk_sv(spacing=6)
        self.lb.padding = [dp(10), dp(6), dp(10), dp(14)]
        root.add_widget(sc)
        self.add_widget(root)   # attach BEFORE refresh so widget tree is live
        self._refresh()

    def _refresh(self, ft=""):
        for w in list(self.lb.children): self.lb.remove_widget(w)
        files = self.app._get_files(filter_text=ft)
        if not files:
            self.lb.add_widget(Lbl("No songs yet - go to Search!", cname="lgrey", fs=13,
                halign="center", size_hint_y=None, height=dp(80)))
            return
        for i, fn in enumerate(files):
            self.lb.add_widget(self.song_row(fn, i,
                on_play=lambda f=fn: self.app._play_from_lib(f),
                on_del=lambda f=fn: self._del(f)))

    def _play_all(self):
        f = self.app._get_files()
        if not f: return
        self.app.queue = list(f); self.app.queue_idx = 0; self.app._play_q(0)

    def _shuffle(self):
        f = list(self.app._get_files())
        if not f: return
        random.shuffle(f); self.app.queue = f
        self.app.queue_idx = 0; self.app._play_q(0)

    def _del(self, fname):
        def _do():
            p = os.path.join(DL_DIR, fname)
            for pp in [p, p + "_hq.wav"]:
                try: os.remove(pp)
                except: pass
            self.app.liked.discard(fname); self.app.playcounts.pop(fname, None)
            for pl in self.app.playlists.values():
                if fname in pl: pl.remove(fname)
            _sj(LK_FILE, list(self.app.liked)); _sj(PL_FILE, self.app.playlists)
            snack("Deleted"); self._refresh()
        confirm_dlg("Delete", f"Delete {os.path.splitext(fname)[0][:28]}?", _do, danger=True)


# ══════════════════════════════════════════════════════════════════════════════
# LIKED
# ══════════════════════════════════════════════════════════════════════════════
class LikedScreen(Base):
    name = "liked"

    def on_enter(self):
        self.clear_widgets()
        root = BoxLayout(orientation="vertical"); _bg(root, "bg")
        songs = [f for f in self.app._get_files() if f in self.app.liked]
        pb = mkicon("play", "black", bg="green", size_px=38, on_press=self._play_all)
        root.add_widget(self.top_bar("Liked Songs", "green", right_widget=pb))
        sc, inner = mk_sv(spacing=6); inner.padding = [dp(10), dp(6), dp(10), dp(14)]
        if not songs:
            inner.add_widget(Lbl("Tap the heart on any song", cname="lgrey", fs=13,
                halign="center", size_hint_y=None, height=dp(80)))
        for i, fn in enumerate(songs):
            inner.add_widget(self.song_row(fn, i, accent="green",
                on_play=lambda f=fn: self.app._play_liked_fn(f),
                on_del=lambda f=fn: (
                    self.app.liked.discard(f),
                    _sj(LK_FILE, list(self.app.liked)),
                    Clock.schedule_once(lambda dt: self.on_enter(), 0))))
        root.add_widget(sc); self.add_widget(root)

    def _play_all(self):
        s = [f for f in self.app._get_files() if f in self.app.liked]
        if not s: return
        self.app.queue = list(s); self.app.queue_idx = 0; self.app._play_q(0)


# ══════════════════════════════════════════════════════════════════════════════
# PLAYLISTS
# ══════════════════════════════════════════════════════════════════════════════
class PlaylistsScreen(Base):
    name = "playlists"

    def on_enter(self):
        self.clear_widgets()
        root = BoxLayout(orientation="vertical"); _bg(root, "bg")
        nb = mkbtn("+ New", "primary",
                   on_press=lambda: input_dlg("New Playlist", "Name:", self._create),
                   size_hint=(None, None), width=dp(90), height=dp(40), radius=20)
        root.add_widget(self.top_bar("Playlists", right_widget=nb))
        sc, inner = mk_sv(spacing=10); inner.padding = [dp(12), dp(10), dp(12), dp(18)]
        pls = list(self.app.playlists.keys())
        order = ([ED_PL] if ED_PL in pls else []) + [p for p in pls if p != ED_PL]
        if not order:
            inner.add_widget(Lbl("No playlists yet", cname="lgrey", fs=14,
                halign="center", size_hint_y=None, height=dp(80)))
        for i, name in enumerate(order):
            cc = PL_COLS[i % len(PL_COLS)]
            inner.add_widget(self._card(name, cc, locked=(name == ED_PL)))
        root.add_widget(sc); self.add_widget(root)

    def _card(self, name, cc, locked=False):
        a = self.app; songs = a.playlists[name]
        fav = a.settings.get("fav_playlist", ""); is_fav = (name == fav and not locked)

        # ── inner BoxLayout (the actual visible card) ──────────────────────────
        card = BoxLayout(orientation="horizontal", size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        with card.canvas.before:
            Color(*col("card2"))
            _r = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(18)])
        card.bind(pos=lambda *a, r=_r: setattr(r, "pos", card.pos),
                  size=lambda *a, r=_r: setattr(r, "size", card.size))
        # Coloured left accent strip
        strip = BoxLayout(size_hint=(None, 1), width=dp(8))
        with strip.canvas.before:
            Color(*col(cc)); _s = Rectangle(pos=strip.pos, size=strip.size)
        strip.bind(pos=lambda *a, r=_s: setattr(r, "pos", strip.pos),
                   size=lambda *a, r=_s: setattr(r, "size", strip.size))
        card.add_widget(strip)
        # Name + song count
        info = BoxLayout(orientation="vertical", size_hint=(1, 1), padding=[dp(12), dp(12)])
        info.add_widget(Lbl(name, bold=True, fs=15, size_hint_y=None, height=dp(26)))
        info.add_widget(Lbl(f"{len(songs)} songs", cname="lgrey", fs=11,
                            size_hint_y=None, height=dp(18)))
        card.add_widget(info)
        # Action buttons on the right
        # Action buttons on the right
        act_w = dp(210 if not locked else 68)
        acts = BoxLayout(size_hint=(None, 1), width=act_w,
                         spacing=dp(8), padding=[0, 0, dp(10), 0])
        acts.add_widget(mkicon("play", "black", bg=cc, size_px=48, pos_hint={"center_y": .5},
                                on_press=lambda *_, n=name: a._play_playlist(n)))
        if not locked:
            star_sym = "star" if is_fav else "unstar"
            sb = mkicon(star_sym, "green" if is_fav else "lgrey", size_px=40, pos_hint={"center_y": .5})
            def _star(n=name, b=sb):
                cur = a.settings.get("fav_playlist", "")
                if cur == n:
                    a.settings["fav_playlist"] = ""
                    b.text = ICO["unstar"]; b.color = list(col("lgrey"))
                else:
                    a.settings["fav_playlist"] = n
                    b.text = ICO["star"]; b.color = list(col("green"))
                _sj(ST_FILE, a.settings)
            sb.bind(on_press=lambda *_: _star()); acts.add_widget(sb)
            acts.add_widget(mkicon("edit", "lgrey", size_px=40, pos_hint={"center_y": .5},
                on_press=lambda *_, n=name: input_dlg("Rename", "New name:",
                    lambda v, o=n: self._rename(o, v))))
            acts.add_widget(mkicon("close", "red", size_px=40, pos_hint={"center_y": .5},
                on_press=lambda *_, n=name: confirm_dlg(
                    "Delete", f"Delete '{n}'?",
                    lambda: self._delete(n), danger=True)))
        card.add_widget(acts)

        # ── FloatLayout wrapper: open_btn overlays only the info area, not btns ─
        wrap = FloatLayout(size_hint_y=None, height=dp(90))
        wrap.add_widget(card)  # card fills entire float
        # Transparent button covers left portion (strip + info), not actions
        open_btn = Button(text="", background_normal="", background_color=(0, 0, 0, 0),
                          size_hint=(None, 1), pos_hint={"x": 0, "y": 0}, width=dp(10))
        def _upd_btn(*_):
            open_btn.width = max(dp(10), wrap.width - act_w)
        wrap.bind(size=_upd_btn, pos=_upd_btn)
        Clock.schedule_once(lambda dt: _upd_btn(), 0)
        open_btn.bind(on_press=lambda *_, n=name: self.app.nav_to("pl_detail", playlist_name=n))
        wrap.add_widget(open_btn)
        return wrap

    def _create(self, n):
        if not n: return
        if n in self.app.playlists: snack("Already exists"); return
        self.app.playlists[n] = []; _sj(PL_FILE, self.app.playlists)
        snack(f"'{n}' created"); self.on_enter()

    def _rename(self, old, new):
        if not new or new in self.app.playlists: return
        a = self.app; a.playlists[new] = a.playlists.pop(old)
        if a.settings.get("fav_playlist", "") == old:
            a.settings["fav_playlist"] = new; _sj(ST_FILE, a.settings)
        _sj(PL_FILE, a.playlists); self.on_enter()

    def _delete(self, name):
        a = self.app; del a.playlists[name]
        if a.settings.get("fav_playlist", "") == name:
            a.settings["fav_playlist"] = ""; _sj(ST_FILE, a.settings)
        _sj(PL_FILE, a.playlists); snack("Deleted"); self.on_enter()


# ══════════════════════════════════════════════════════════════════════════════
# PLAYLIST DETAIL
# ══════════════════════════════════════════════════════════════════════════════
class PlDetailScreen(Base):
    name = "pl_detail"

    def __init__(self, **kw): super().__init__(**kw); self._pl = None

    def show(self, name): self._pl = name; self.on_enter()

    # ── helper: extract base name + preset from 8D filename ─────────────────
    @staticmethod
    def _8d_split(fn):
        """Returns (base_name, preset_name) for 8D files, else (fn, None)."""
        if not fn.endswith("_8D.wav"):
            return fn, None
        stem = fn[:-7]
        for p in PRESETS:
            suf = "_" + p.replace(" ", "_")
            if stem.endswith(suf):
                return stem[:-len(suf)], p
        return stem, None

    def on_enter(self):
        if not self._pl: return
        self.clear_widgets()
        name = self._pl; a = self.app
        songs = a.playlists.get(name, []); is8 = (name == ED_PL)
        folder = ED_DIR if is8 else DL_DIR
        root = BoxLayout(orientation="vertical"); _bg(root, "bg")
        banner = BoxLayout(size_hint_y=None, height=dp(110),
                           padding=[dp(14), dp(12)], spacing=dp(12))
        _bg(banner, "bg2")
        banner.add_widget(Button(text=ICO["back"], font_size=sp(24), bold=True,
                                 font_name=_APP_FONT,
                                 background_normal="", background_color=(0, 0, 0, 0),
                                 color=list(col("lgrey")),
                                 size_hint=(None, 1), width=dp(40),
                                 on_press=lambda *_: a.nav_to("playlists")))
        meta = BoxLayout(orientation="vertical", size_hint=(1, 1))
        meta.add_widget(Lbl(name, bold=True, fs=18, size_hint_y=None, height=dp(30)))
        meta.add_widget(Lbl(f"{len(songs)} songs", cname="lgrey", fs=12,
                            size_hint_y=None, height=dp(20)))
        meta.add_widget(mkbtn("Play All", "primary",
                               on_press=lambda: a._play_playlist(name),
                               size_hint=(None, None), width=dp(110), height=dp(40), radius=20))
        banner.add_widget(meta); root.add_widget(banner)
        sc, inner = mk_sv(spacing=6); inner.padding = [dp(10), dp(8), dp(10), dp(14)]
        if not songs:
            inner.add_widget(Lbl("No songs yet.", cname="lgrey", fs=13,
                halign="center", size_hint_y=None, height=dp(80)))
        elif is8:
            # ── 8D Mixes: group by base song, show preset chips ───────────────
            groups = {}  # base_name -> {preset: filename}
            for fn in songs:
                base, preset = self._8d_split(fn)
                if preset:
                    groups.setdefault(base, {})[preset] = fn
                else:
                    groups.setdefault(fn, {})["?"] = fn
            for base, versions in groups.items():
                inner.add_widget(self._8d_group_row(base, versions, a))
        else:
            for i, fn in enumerate(songs):
                exists = (os.path.exists(os.path.join(folder, fn)) or
                          os.path.exists(os.path.join(DL_DIR, fn)))
                if exists:
                    def _del(f=fn, n=name):
                        if f in a.playlists.get(n, []): a.playlists[n].remove(f)
                        _sj(PL_FILE, a.playlists)
                        Clock.schedule_once(lambda dt: self.show(n), 0)
                    inner.add_widget(self.song_row(fn, i,
                        on_play=lambda n=name, idx=i: a._play_pl_from(n, idx),
                        on_del=_del))
                else:
                    r = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(50),
                                  padding=[dp(12), 0])
                    with r.canvas.before:
                        Color(*col("card2"))
                        _rx = RoundedRectangle(pos=r.pos, size=r.size, radius=[dp(12)])
                    r.bind(pos=lambda *a, rx=_rx: setattr(rx, "pos", r.pos),
                           size=lambda *a, rx=_rx: setattr(rx, "size", r.size))
                    r.add_widget(Lbl(os.path.splitext(fn)[0], cname="mgrey",
                                     fs=12, size_hint=(1, 1)))
                    r.add_widget(Lbl("missing", cname="red", fs=10,
                                     size_hint=(None, 1), width=dp(60)))
                    inner.add_widget(r)
        root.add_widget(sc); self.add_widget(root)

    def _8d_group_row(self, base, versions, a):
        """One card per base song with preset-chip buttons (like choosing a model)."""
        card = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6),
                         padding=[dp(12), dp(10)])
        with card.canvas.before:
            Color(*col("card2"))
            _r = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(16)])
        card.bind(pos=lambda *a, r=_r: setattr(r, "pos", card.pos),
                  size=lambda *a, r=_r: setattr(r, "size", card.size))
        # Title row
        title_row = BoxLayout(size_hint_y=None, height=dp(28))
        title_row.add_widget(Lbl(base, bold=True, fs=14, size_hint=(1, 1)))
        is_playing = any(
            a.cur_meta.get("path", "") == os.path.join(ED_DIR, fn)
            for fn in versions.values())
        pi = mkicon("pause" if is_playing else "play",
                    "black" if is_playing else "green",
                    bg="green" if is_playing else None, size_px=36)
        title_row.add_widget(pi)
        card.add_widget(title_row)
        # Preset chips
        chips = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
        for preset_name in PRESETS:
            if preset_name not in versions:
                continue
            fn = versions[preset_name]
            path = os.path.join(ED_DIR, fn)
            active = a.cur_meta.get("path", "") == path
            chip = mkbtn(preset_name, "primary" if active else "chip",
                         size_hint=(None, None),
                         width=dp(max(80, len(preset_name) * 8 + 24)),
                         height=dp(36), radius=18)
            def _play_ver(p=path, t=base, pn=preset_name):
                a._play_file(p, title=f"{t} ({pn})")
            chip.bind(on_press=lambda *_, fn=_play_ver: fn())
            chips.add_widget(chip)
        # also wire the big play icon to the first available version
        first_fn = next(iter(versions.values()))
        first_path = os.path.join(ED_DIR, first_fn)
        first_base = base; first_preset = next(iter(versions))
        pi.bind(on_press=lambda *_: a._play_file(
            first_path, title=f"{first_base} ({first_preset})"))
        card.add_widget(chips)
        # dynamic height = title + chips + padding*2
        card.height = dp(28) + dp(38) + dp(26)
        return card


# ══════════════════════════════════════════════════════════════════════════════
# 8D CONVERTER
# ══════════════════════════════════════════════════════════════════════════════
class EightDScreen(Base):
    name = "eightd"

    def on_enter(self):
        self.clear_widgets(); self._sel = set(); self._busy = False; self._preset = "Classic"
        root = BoxLayout(orientation="vertical"); _bg(root, "bg")
        root.add_widget(self.top_bar("8D Converter", "green"))
        sc, inner = mk_sv(spacing=10); inner.padding = [dp(12), dp(10), dp(12), dp(14)]
        inner.add_widget(Lbl("Effect Preset", cname="lgrey", fs=12,
                              size_hint_y=None, height=dp(24)))
        psv = SafeScrollView(do_scroll_x=True, do_scroll_y=False,
                             size_hint=(1, None), height=dp(56))
        prow = BoxLayout(orientation="horizontal", size_hint=(None, 1),
                         spacing=dp(8), padding=[dp(2), dp(4)])
        prow.bind(minimum_width=prow.setter("width"))
        self._pbtns = {}
        for pname in PRESETS:
            active = (pname == self._preset)
            pb = mkbtn(pname, "primary" if active else "secondary",
                       size_hint=(None, None), height=dp(44),
                       width=dp(max(88, len(pname) * 9 + 28)), radius=22)
            pb.bind(on_press=lambda *_, p=pname: self._pick_preset(p))
            self._pbtns[pname] = pb; prow.add_widget(pb)
        psv.add_widget(prow); inner.add_widget(psv)
        self.desc_l = Lbl(PRESETS["Classic"]["desc"], cname="lgrey", fs=11,
                          halign="center", size_hint_y=None, height=dp(22))
        inner.add_widget(self.desc_l)
        ph = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
        ph.add_widget(Lbl("Select songs:", cname="lgrey", fs=12, size_hint=(1, 1)))
        ph.add_widget(mkbtn("All", "secondary", on_press=self._sel_all,
                            size_hint=(None, None), width=dp(56), height=dp(36), radius=18))
        ph.add_widget(mkbtn("Clear", "ghost", on_press=self._clr,
                            size_hint=(None, None), width=dp(62), height=dp(36), radius=18))
        inner.add_widget(ph)
        picker_sv = SafeScrollView(do_scroll_x=False, size_hint=(1, None), height=dp(180))
        self.picker = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(5))
        self.picker.bind(minimum_height=self.picker.setter("height"))
        picker_sv.add_widget(self.picker); inner.add_widget(picker_sv)
        self._build_picker()
        self.sel_l = Lbl("No songs selected", cname="lgrey", fs=12,
                         halign="center", size_hint_y=None, height=dp(24))
        inner.add_widget(self.sel_l)
        self.prog = ProgressBar(max=100, value=0, size_hint=(1, None), height=dp(6))
        inner.add_widget(self.prog)
        self.stat_l = Lbl("", cname="lgrey", fs=11, halign="center",
                          size_hint_y=None, height=dp(22))
        inner.add_widget(self.stat_l)
        self.conv_btn = mkbtn("Convert to 8D", "primary", on_press=self._start,
                              size_hint=(1, None), height=dp(54), radius=27)
        inner.add_widget(self.conv_btn)
        root.add_widget(sc); self.add_widget(root)

    def _build_picker(self):
        for w in list(self.picker.children): self.picker.remove_widget(w)
        try: mp3s = sorted(f for f in os.listdir(DL_DIR) if f.endswith(".mp3"))
        except: mp3s = []
        if not mp3s:
            self.picker.add_widget(Lbl("Download songs first", cname="lgrey", fs=13,
                halign="center", size_hint_y=None, height=dp(54)))
            return
        for fname in mp3s:
            sel = (fname in self._sel)
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48),
                            padding=[dp(10), dp(6)], spacing=dp(10))
            with row.canvas.before:
                Color(*col("card2"))
                _r = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(12)])
            row.bind(pos=lambda *a, r=_r: setattr(r, "pos", row.pos),
                     size=lambda *a, r=_r: setattr(r, "size", row.size))
            chk = CheckBox(active=sel, size_hint=(None, None),
                           width=dp(28), height=dp(28), color=list(col("green")))
            chk.bind(active=lambda inst, v, fn=fname: self._toggle(fn, v))
            row.add_widget(chk)
            row.add_widget(Lbl(fname[:-4], fs=13,
                               cname="green" if sel else "white", size_hint=(1, 1)))
            self.picker.add_widget(row)

    def _toggle(self, fn, v):
        if v: self._sel.add(fn)
        else: self._sel.discard(fn)
        n = len(self._sel)
        self.sel_l.text  = f"{n} selected" if n else "No songs selected"
        self.sel_l.color = col("green") if n else col("lgrey")
        self._build_picker()

    def _sel_all(self):
        try: self._sel = set(f for f in os.listdir(DL_DIR) if f.endswith(".mp3"))
        except: self._sel = set()
        self._build_picker()
        self.sel_l.text = f"{len(self._sel)} selected"; self.sel_l.color = col("green")

    def _clr(self):
        self._sel.clear(); self._build_picker()
        self.sel_l.text = "No songs selected"; self.sel_l.color = col("lgrey")

    def _pick_preset(self, name):
        self._preset = name; self.desc_l.text = PRESETS[name]["desc"]
        for pn, pb in self._pbtns.items():
            with pb.canvas.before:
                Color(*col("green" if pn == name else "card3"))
                RoundedRectangle(pos=pb.pos, size=pb.size, radius=[dp(22)])

    def _start(self):
        if not self._sel: snack("Select at least one song"); return
        if self._busy: return
        if not find_ff(): snack("ffmpeg not ready"); return
        self._busy = True; self.conv_btn.text = "Converting..."
        self._batch(list(self._sel), self._preset)

    def _batch(self, songs, preset):
        total = len(songs)

        def _process_next(idx=0):
            if idx >= total:
                Clock.schedule_once(lambda dt: self._done(total))
                return
            fn = songs[idx]
            src = os.path.join(DL_DIR, fn)
            safe = fn.replace(".mp3", f"_{preset.replace(' ', '_')}_8D.wav")
            dst = os.path.join(ED_DIR, safe)
            Clock.schedule_once(lambda dt, n=fn, _i=idx:
                setattr(self.stat_l, "text", f"[{_i + 1}/{total}] {n[:-4]}..."))
            
            def _comp(_dst):
                pl = self.app.playlists.setdefault(ED_PL, [])
                if safe not in pl: pl.append(safe); _sj(PL_FILE, self.app.playlists)
                _process_next(idx + 1)
                
            def _err(e):
                Clock.schedule_once(lambda dt, err=str(e): snack(f"Failed: {err[:40]}"))
                _process_next(idx + 1)
                
            make_8d(src, dst, preset=preset, settings=self.app.settings,
                    progress_cb=lambda p: Clock.schedule_once(
                        lambda dt, v=(idx + p) / total: setattr(self.prog, "value", v * 100)),
                    on_complete=_comp, on_error=_err)

        _process_next(0)

    def _done(self, total):
        self._busy = False; self.prog.value = 100
        self.stat_l.text = f"Done! {total} converted"
        self.conv_btn.text = "Convert to 8D"
        snack(f"{total} tracks in 8D Mixes!")
        self._sel.clear(); self._build_picker()
        Clock.schedule_once(lambda dt: setattr(self.prog, "value", 0), 2.5)


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
class SettingsScreen(Base):
    name = "settings"

    def on_enter(self):
        self.clear_widgets()
        root = BoxLayout(orientation="vertical"); _bg(root, "bg")
        root.add_widget(self.top_bar("Settings"))
        sc, inner = mk_sv(spacing=14); inner.padding = [dp(12), dp(10), dp(12), dp(18)]
        s = self.app.settings
        # ── Listening stats card ──────────────────────────────────────────────
        a = self.app
        total_mins = int(a.settings.get("total_secs_listened", 0) // 60)
        songs_n    = len(a.playcounts)
        stat = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(80),
                         padding=[dp(18), dp(14)], spacing=dp(4))
        _bg(stat, "card2", 18)
        stat.add_widget(Lbl("Your Listening Stats", bold=True, fs=14,
                            size_hint_y=None, height=dp(22)))
        stat.add_widget(Lbl(f"{total_mins} min listened  •  {songs_n} songs played",
                            cname="green", fs=12, size_hint_y=None, height=dp(18)))
        inner.add_widget(stat)
        inner.add_widget(self._sec("Playback", [
            self._sw("Autoplay next song", "autoplay", s),
            self._sw("Shuffle by default", "shuffle", s),
            self._sw("Loudness normalize", "normalize", s)]))
        inner.add_widget(self._sec("Audio Quality", [
            self._opt("Download bitrate", "audio_quality", s,
                      ["128", "192", "256", "320"], "kbps")]))
        inner.add_widget(self._sec("Equalizer", [
            self._sl("Bass",   "eq_bass",   s, -6, 12, "dB"),
            self._sl("Treble", "eq_treble", s, -6, 10, "dB")]))
        inner.add_widget(self._sleep_card())
        about = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(76),
                          padding=[dp(18), dp(12)])
        _bg(about, "card2", 18)
        about.add_widget(Lbl("8DStud v9.0 (Alpha)", bold=True, fs=15,
                             size_hint_y=None, height=dp(26)))
        about.add_widget(Lbl("Feedback: Discord @zooweemama0001", cname="lgrey", fs=12,
                             size_hint_y=None, height=dp(20)))
        inner.add_widget(about)
        inner.add_widget(mkbtn("Save Settings", "primary",
            on_press=lambda: (_sj(ST_FILE, self.app.settings), snack("Saved!")),

            size_hint=(1, None), height=dp(54), radius=27))
        root.add_widget(sc); self.add_widget(root)

    def _cw(self, h):
        card = BoxLayout(orientation="vertical", padding=[dp(16), dp(10)],
                         spacing=dp(4), size_hint_y=None, height=h)
        _bg(card, "card2", 18); return card

    def _sec(self, title, rows):
        h = int(dp(14)) + int(dp(30)) + len(rows) * int(dp(54)) + int(dp(10))
        card = self._cw(h)
        card.add_widget(Lbl(title, bold=True, fs=15, size_hint_y=None, height=dp(30)))
        for r in rows: card.add_widget(r)
        return card

    def _sw(self, label, key, s):
        row = BoxLayout(size_hint_y=None, height=dp(50))
        row.add_widget(Lbl(label, cname="white", fs=13, size_hint=(1, 1)))
        tog = PillToggle(active=s.get(key, False),
                         size_hint=(None, None), size=(dp(52), dp(30)))
        tog.bind(active=lambda inst, v, k=key: s.__setitem__(k, v))
        row.add_widget(tog); return row

    def _opt(self, label, key, s, opts, unit):
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        row.add_widget(Lbl(label, cname="white", fs=13, size_hint=(1, 1)))
        cur = str(s.get(key, opts[0]))
        st = [opts.index(cur) if cur in opts else 0]
        vl = Lbl(f"{cur} {unit}", fs=13, cname="green", halign="right",
                 size_hint=(None, 1), width=dp(80))
        def _cyc():
            st[0] = (st[0] + 1) % len(opts); v = opts[st[0]]
            s[key] = int(v) if v.isdigit() else v; vl.text = f"{v} {unit}"
        row.add_widget(vl)
        row.add_widget(mkbtn("Change", "secondary", on_press=_cyc,
                             size_hint=(None, None), width=dp(80), height=dp(40), radius=20))
        return row

    def _sl(self, label, key, s, mn, mx, unit):
        """Custom styled slider using SeekBar so it matches the app theme."""
        # 60 dp total height, tight layout
        cb = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(60))
        top = BoxLayout(size_hint_y=None, height=dp(26), padding=[0, dp(4), 0, 0])
        top.add_widget(Lbl(label, cname="white", fs=13, size_hint=(1, 1)))
        cur_v = s.get(key, 0)
        vl = Lbl(f"{cur_v} {unit}", fs=13, cname="green",
                 halign="right", size_hint=(None, 1), width=dp(60))
        top.add_widget(vl); cb.add_widget(top)
        # SeekBar-style track (maps [mn,mx] → [0,1])
        sb = SeekBar(size_hint=(1, None), height=dp(28))
        span = mx - mn
        sb.set_frac((cur_v - mn) / span if span else 0)
        def _on_seek_sl(frac, k=key, l=vl, u=unit, _s=s, _mn=mn, _span=span):
            iv = int(_mn + frac * _span)
            _s[k] = iv; l.text = f"{iv} {u}"
        sb._on_seek = _on_seek_sl
        cb.add_widget(sb); return cb

    def _sleep_card(self):
        card = self._cw(int(dp(116)))
        hdr = BoxLayout(size_hint_y=None, height=dp(28))
        hdr.add_widget(Lbl("Sleep Timer", bold=True, fs=15, size_hint=(1, 1)))
        self.sleep_l = Lbl("Off", cname="lgrey", fs=11, halign="right",
                           size_hint=(None, 1), width=dp(80))
        hdr.add_widget(self.sleep_l); card.add_widget(hdr)
        btns = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        for mins, lbl in [(0, "Off"), (15, "15m"), (30, "30m"), (60, "1h"), (90, "1.5h")]:
            btns.add_widget(mkbtn(lbl, "secondary",
                on_press=lambda m=mins: self._set_sleep(m),
                size_hint=(1, None), height=dp(40), radius=20))
        card.add_widget(btns); return card

    def _set_sleep(self, mins):
        a = self.app
        if hasattr(a, "_sleep_ev") and a._sleep_ev:
            try: a._sleep_ev.cancel()
            except: pass
            a._sleep_ev = None
        a.settings["sleep_timer"] = mins
        if mins == 0:
            self.sleep_l.text = "Off"; self.sleep_l.color = col("lgrey"); snack("Sleep off")
        else:
            a._sleep_ev = Clock.schedule_once(
                lambda dt: (a.audio.pause(), a.now_bar.set_playing(False), snack("Stopped")),
                mins * 60)
            self.sleep_l.text = f"{mins}m"; self.sleep_l.color = col("green")
            snack(f"Sleep: {mins} min")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ══════════════════════════════════════════════════════════════════════════════
class EightDStudApp(App):
    def build(self):
        init_paths(self)
        Window.clearcolor = col("bg")
        self.settings     = load_settings()
        self.playlists    = load_playlists()
        self.liked        = load_liked()
        self.playcounts   = load_counts()
        self.audio        = AudioPlayer()
        self.recently_played = []
        self.queue = []; self.queue_idx = -1; self.cur_meta = {}
        self._secs_remaining = 0; self._skip_flag = False
        self._end_triggered  = False
        self._autoplay_q     = _queue.Queue()
        self._autoplay_evt   = None; self._sleep_ev = None
        self._listen_start   = None  # timestamp when current track started
        if ED_PL not in self.playlists:
            self.playlists[ED_PL] = []; _sj(PL_FILE, self.playlists)
        root = FloatLayout()
        main = BoxLayout(orientation="vertical", size_hint=(1, 1)); _bg(main, "bg")
        self.sm = ScreenManager(transition=NoTransition(), size_hint=(1, 1))
        for SC in [HomeScreen, SearchScreen, LibraryScreen, LikedScreen,
                   PlaylistsScreen, PlDetailScreen, EightDScreen, SettingsScreen]:
            self.sm.add_widget(SC())
        main.add_widget(self.sm)
        self.now_bar  = NowBar();    main.add_widget(self.now_bar)
        self.bot_nav  = BottomNav(); main.add_widget(self.bot_nav)
        root.add_widget(main)
        self.drawer = Drawer(size_hint=(1, 1)); root.add_widget(self.drawer)
        Clock.schedule_once(lambda dt: self._check_ff(), 2)
        if not self.settings.get("welcome_shown", False):
            Clock.schedule_once(lambda dt: welcome_dlg(self), 0.5)
        return root

    def on_start(self):
        if platform == "android":
            from android.permissions import request_permissions, Permission
            request_permissions([
                Permission.READ_EXTERNAL_STORAGE, 
                Permission.WRITE_EXTERNAL_STORAGE
            ])

    def on_pause(self):
        # Kivy Android: return True tells Android to keep the app alive instead of killing it
        self._acquire_wakelock()
        return True

    def on_resume(self):
        self._release_wakelock()

    def _acquire_wakelock(self):
        if platform == "android":
            try:
                pm = PythonActivity.mActivity.getSystemService(Context.POWER_SERVICE)
                self._wake_lock = pm.newWakeLock(1, "8DStud:BackgroundAudioLock") # 1 = PARTIAL_WAKE_LOCK
                self._wake_lock.acquire()
            except Exception as e: print("WakeLock acquire failed:", e)

    def _release_wakelock(self):
        if platform == "android":
            try:
                if hasattr(self, "_wake_lock") and self._wake_lock:
                    self._wake_lock.release()
                    self._wake_lock = None
            except Exception as e: print("WakeLock release failed:", e)

    def toggle_drawer(self): self.drawer.toggle()

    def nav_to(self, screen, **kw):
        if screen == "pl_detail":
            pl = kw.get("playlist_name")
            if pl: self.sm.get_screen("pl_detail").show(pl)
        self.sm.current = screen; self.bot_nav.set_active(screen)

    def _get_files(self, filter_text="", sort="A-Z"):
        try: files = [f for f in os.listdir(DL_DIR)
                      if f.endswith((".mp3", ".m4a", ".webm"))]
        except: files = []
        if filter_text:
            files = [f for f in files if filter_text.lower() in f.lower()]
        return sorted(files)

    def _play_file(self, path, title="", artist="", art_url=""):
        # Accumulate listening time from previous track
        if self._listen_start is not None:
            elapsed = time.time() - self._listen_start
            self.settings["total_secs_listened"] = \
                self.settings.get("total_secs_listened", 0) + elapsed
        self._listen_start = time.time()
        self._cancel_autoplay()
        self._skip_flag    = False
        self._end_triggered = False
        # If no metadata given (e.g. playing from library), check for yt-dlp info.json
        if not art_url:
            info_path = os.path.splitext(path)[0] + ".info.json"
            if os.path.exists(info_path):
                try:
                    with open(info_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if not title: title = data.get("title", "")
                        if not artist: artist = data.get("uploader", "")
                        art_url = data.get("thumbnail", "")
                except: pass

        name  = title or os.path.splitext(os.path.basename(path))[0]
        fname = os.path.basename(path)
        self.cur_meta = {"path": path, "title": name, "artist": artist, "art_url": art_url}
        self.now_bar.update_meta(name, artist, fname in self.liked, art_url)
        self.now_bar.set_playing(False)
        snack("Loading...")
        def _on_ready(ok):
            if not ok:
                snack(f"Cannot play: {fname[:30]}"); return
            self.audio.set_volume(.88); self.audio.play()
            self.now_bar.set_playing(True)
            dur = self.audio.duration
            if dur and dur > 0: self._schedule_autoplay(dur)
        self.audio.load(path, on_ready=_on_ready)
        self.playcounts[fname] = self.playcounts.get(fname, 0) + 1
        entry = {"fname": fname, "title": name, "time": time.strftime("%H:%M")}
        self.recently_played = [e for e in self.recently_played if e["fname"] != fname]
        self.recently_played.insert(0, entry); self.recently_played = self.recently_played[:30]

    def _toggle_play(self):
        if not self.cur_meta: return
        if self.audio.playing:
            dur = self.audio.duration; pos = self.audio.position
            self._secs_remaining = max(0., dur - pos) if dur else 0
            self._cancel_autoplay(); self.audio.pause(); self.now_bar.set_playing(False)
        else:
            self.audio.play(); self.now_bar.set_playing(True)
            if self._secs_remaining > .5: self._schedule_autoplay(self._secs_remaining)

    def _prev(self):
        if self.queue and self.queue_idx > 0:
            self._skip_flag = True; self._end_triggered = False
            self._play_q(self.queue_idx - 1)

    def _next(self):
        if not self.queue: return
        self._skip_flag = True; self._end_triggered = False
        repeat = self.settings.get("repeat", "none")
        shuf   = self.settings.get("shuffle", False)
        last   = len(self.queue) - 1
        if shuf:
            cands = [i for i in range(len(self.queue)) if i != self.queue_idx]
            if cands: self._play_q(random.choice(cands))
            elif repeat == "all": self._play_q(0)
        elif self.queue_idx < last: self._play_q(self.queue_idx + 1)
        elif repeat == "all": self._play_q(0)
        else: self._skip_flag = False; self.now_bar.set_playing(False)

    def _play_q(self, idx):
        if 0 <= idx < len(self.queue):
            self.queue_idx = idx; fn = self.queue[idx]
            for folder in [DL_DIR, ED_DIR]:
                path = os.path.join(folder, fn)
                if os.path.exists(path):
                    self._play_file(path, title=os.path.splitext(fn)[0]); return
            snack(f"Missing: {fn}")
            if idx < len(self.queue) - 1: self._play_q(idx + 1)

    def _play_from_lib(self, fn):
        files = self._get_files(); self.queue = list(files)
        try: self.queue_idx = files.index(fn)
        except ValueError: self.queue_idx = 0
        self._play_q(self.queue_idx)

    def _play_liked_fn(self, fn):
        songs = [f for f in self._get_files() if f in self.liked]
        self.queue = songs
        try: self.queue_idx = songs.index(fn)
        except ValueError: self.queue_idx = 0
        self._play_q(self.queue_idx)

    def _play_playlist(self, name):
        songs  = self.playlists.get(name, [])
        folder = ED_DIR if name == ED_PL else DL_DIR
        valid  = [s for s in songs if os.path.exists(os.path.join(folder, s)) or
                  os.path.exists(os.path.join(DL_DIR, s))]
        if not valid: snack("No valid songs"); return
        self.queue = list(valid)
        if self.settings.get("shuffle"): random.shuffle(self.queue)
        self.queue_idx = 0; self._play_q(0)

    def _play_pl_from(self, name, start_idx):
        songs  = self.playlists.get(name, [])
        folder = ED_DIR if name == ED_PL else DL_DIR
        valid  = [s for s in songs if os.path.exists(os.path.join(folder, s)) or
                  os.path.exists(os.path.join(DL_DIR, s))]
        if not valid: return
        try: vi = valid.index(songs[start_idx]) if songs[start_idx] in valid else 0
        except: vi = 0
        self.queue = valid; self.queue_idx = vi; self._play_q(vi)

    def _on_track_end(self):
        if self._skip_flag: return
        self._end_triggered = False
        if self.settings.get("repeat", "none") == "one": self._play_q(self.queue_idx)
        else: self._next()

    def _toggle_like_cur(self):
        if not self.cur_meta: return
        fn = os.path.basename(self.cur_meta.get("path", ""))
        if not fn: return
        if fn in self.liked:
            self.liked.discard(fn)
            self.now_bar.like_btn.text  = ICO["unlike"]
            self.now_bar.like_btn.color = list(col("lgrey"))
            snack("Removed from Liked")
        else:
            self.liked.add(fn)
            self.now_bar.like_btn.text  = ICO["like"]
            self.now_bar.like_btn.color = list(col("green"))
            snack("Liked!")
        _sj(LK_FILE, list(self.liked))

    def _schedule_autoplay(self, seconds):
        self._cancel_autoplay()
        if seconds <= 0: return
        self._autoplay_evt = threading.Event(); ev = self._autoplay_evt
        def _w():
            cancelled = ev.wait(timeout=seconds)
            if not cancelled and not self._skip_flag and self.cur_meta:
                self._autoplay_q.put(True)
        threading.Thread(target=_w, daemon=True).start()

    def _cancel_autoplay(self):
        if self._autoplay_evt: self._autoplay_evt.set(); self._autoplay_evt = None
        while not self._autoplay_q.empty():
            try: self._autoplay_q.get_nowait()
            except: break

    def _check_ff(self):
        if platform == "android": return
        if find_ff(): snack("ffmpeg ready")
        else:
            snack("Downloading ffmpeg...")
            threading.Thread(target=self._dl_ff_bg, daemon=True).start()

    def _dl_ff_bg(self):
        try:
            dl_ff(); Clock.schedule_once(lambda dt: snack("ffmpeg ready!"))
        except:
            Clock.schedule_once(lambda dt: snack("ffmpeg download failed"))

    def on_stop(self):
        self._cancel_autoplay()
        if self._sleep_ev:
            try: self._sleep_ev.cancel()
            except: pass
        self.audio.stop()
        _sj(ST_FILE,  self.settings)
        _sj(PC_FILE,  self.playcounts)
        _sj(LK_FILE,  list(self.liked))


if __name__ == "__main__":
    EightDStudApp().run()