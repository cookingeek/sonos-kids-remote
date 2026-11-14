#!/usr/bin/env python3
"""Machbarkeitstest: Apple Music über den Web-Player in einem Headless-Chrome
auf einem Raspberry Pi Zero 2 W (512 MB RAM).

Befehle:
  login   Apple-Login per Live-Ansicht im eigenen Browser (über SSH-Tunnel)
  check   Kurztest: Seite laden, Widevine prüfen, Anmeldung prüfen, Speicher messen
  run     Dauertest: Album abspielen, Speicher/CPU/Aussetzer protokollieren, Urteil

Siehe README.md im selben Ordner.
"""
import argparse
import asyncio
import csv
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    import aiohttp
    from aiohttp import web
except ImportError:
    sys.exit("python3-aiohttp fehlt. Bitte zuerst 'sudo ./setup.sh' ausführen.")

DATA = Path(os.environ.get("ZF_DIR", Path.home() / ".local/share/zero-feasibility"))
PROFILE = DATA / "profile"
RESULTS = DATA / "results"
CDP_PORT = int(os.environ.get("ZF_CDP_PORT", "9222"))
CDP_HTTP = f"http://127.0.0.1:{CDP_PORT}"
APPLE_URL = "https://music.apple.com/"
CLK_TCK = os.sysconf("SC_CLK_TCK")

# ---------------------------------------------------------------------------
# Chrome-Profile. "lean" entspricht der in der Analyse gemessenen Variante C.
# ---------------------------------------------------------------------------
COMMON_FLAGS = [
    "--headless=new",
    "--no-first-run",
    "--no-default-browser-check",
    "--password-store=basic",
    "--autoplay-policy=no-user-gesture-required",
    "--disable-background-media-suspend",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--force-device-scale-factor=1",
]
BALANCED_FLAGS = [
    "--disable-features=site-per-process,IsolateOrigins,Translate,MediaRouter,"
    "OptimizationHints,AutofillServerCommunication,CalculateNativeWinOcclusion,"
    "AudioServiceOutOfProcess,IntensiveWakeUpThrottling",
    "--enable-features=NetworkServiceInProcess2",
    "--renderer-process-limit=1",
    "--disable-extensions",
    "--disable-component-extensions-with-background-pages",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-default-apps",
    "--disable-breakpad",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--in-process-gpu",
    "--enable-low-end-device-mode",
    "--disk-cache-size=8388608",
]
# lean: zusätzlich ohne Sandbox/Zygote (spart einen Prozess) und V8 ohne
# optimierenden JIT (spart Speicher, kostet CPU). Bewusster Kompromiss.
LEAN_EXTRA = ["--no-sandbox", "--no-zygote", "--js-flags=--lite-mode"]

PROFILES = {
    "default": [],
    "balanced": BALANCED_FLAGS,
    "lean": BALANCED_FLAGS + LEAN_EXTRA,
}

# Cover und Video-Artwork blockieren; den Audio-Stream (HLS) nie.
BLOCKED_URLS = ["*mzstatic.com/image/*", "*mvod.itunes.apple.com*"]

JS_READY = "typeof MusicKit !== 'undefined' && !!MusicKit.getInstance()"
JS_AUTHED = f"({JS_READY}) && MusicKit.getInstance().isAuthorized === true"
JS_WIDEVINE = """(async () => {
  try {
    await navigator.requestMediaKeySystemAccess('com.widevine.alpha', [{
      initDataTypes: ['cenc'],
      audioCapabilities: [{contentType: 'audio/mp4; codecs="mp4a.40.2"'}]
    }]);
    return 'ok';
  } catch (e) { return 'fehlt: ' + ((e && e.message) || e); }
})()"""
JS_PLAY = """(() => {
  const mk = MusicKit.getInstance();
  window.__zfErr = '';
  try { mk.volume = %(volume)s; } catch (e) {}
  const p = mk.setQueue({ album: %(album)s, startPlaying: true });
  if (p && p.then) p.then(() => { try { mk.repeatMode = 2; } catch (e) {} })
                    .catch((e) => { window.__zfErr = 'setQueue: ' + ((e && e.message) || e); });
  return true;
})()"""
JS_RESUME = """(() => { const p = MusicKit.getInstance().play();
  if (p && p.catch) p.catch((e) => { window.__zfErr = 'play: ' + ((e && e.message) || e); });
  return true; })()"""
JS_STATE = """(() => {
  const mk = MusicKit.getInstance();
  const it = mk.nowPlayingItem;
  const a = (it && it.attributes) || {};
  const err = window.__zfErr || ''; window.__zfErr = '';
  return {
    authed: mk.isAuthorized === true,
    state: mk.playbackState,
    playing: mk.playbackState === 2,
    pos: mk.currentPlaybackTime || 0,
    dur: mk.currentPlaybackDuration || 0,
    title: a.name || '',
    idx: mk.queue ? mk.queue.position : -1,
    err: err,
  };
})()"""


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def find_chrome():
    env = os.environ.get("ZF_CHROME")
    if env:
        return env
    for name in ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    sys.exit("Kein Chrome/Chromium gefunden. 'sudo ./setup.sh' ausführen oder ZF_CHROME setzen.")


# ---------------------------------------------------------------------------
# Speicher- und CPU-Messung über /proc
# ---------------------------------------------------------------------------
def read_meminfo():
    out = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, val = line.split(":", 1)
            out[key] = int(val.split()[0]) // 1024  # MB
    return out


def read_vmstat(key):
    with open("/proc/vmstat") as f:
        for line in f:
            k, v = line.split()
            if k == key:
                return int(v)
    return 0


def zram_stats():
    """(Originaldaten MB, komprimiert MB) aller zram-Geräte."""
    orig = comp = 0
    for dev in Path("/sys/block").glob("zram*"):
        try:
            parts = (dev / "mm_stat").read_text().split()
            orig += int(parts[0])
            comp += int(parts[1])
        except (OSError, IndexError, ValueError):
            pass
    return orig // 2**20, comp // 2**20


def _ppid(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return None


def process_tree(root):
    pids = {root}
    changed = True
    while changed:
        changed = False
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                pid = int(entry)
                if pid not in pids and _ppid(pid) in pids:
                    pids.add(pid)
                    changed = True
    return pids


def browser_pid():
    """Wurzelprozess des Test-Chrome (am --user-data-dir erkennbar)."""
    marker = f"--user-data-dir={PROFILE}"
    candidates = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            cmd = Path(f"/proc/{entry}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if marker in cmd and "--type=" not in cmd:
            candidates.append(int(entry))
    # Ein Wrapper-Skript (chromium-browser) kann Elternprozess sein: den äußersten nehmen.
    for pid in candidates:
        if _ppid(pid) not in candidates:
            return pid
    return candidates[0] if candidates else None


def chrome_usage(root):
    """Speicher (MB) und CPU-Ticks des Prozessbaums.

    resident = Pss_Anon + Pss_Shmem: was zwingend im RAM (oder zram) liegen muss.
    file     = Pss_File: Programmcode, den der Kernel bei Bedarf verdrängen kann.
    """
    res = file = ticks = 0
    n = 0
    for pid in process_tree(root):
        try:
            fields = {}
            with open(f"/proc/{pid}/smaps_rollup") as f:
                for line in f.readlines()[1:]:
                    k, v = line.split(":", 1)
                    fields[k] = int(v.split()[0])
            res += fields.get("Pss_Anon", fields.get("Private_Dirty", 0)) + fields.get("Pss_Shmem", 0)
            file += fields.get("Pss_File", 0)
            with open(f"/proc/{pid}/stat") as f:
                st = f.read().rsplit(")", 1)[1].split()
            ticks += int(st[11]) + int(st[12])
            n += 1
        except (OSError, ValueError, IndexError):
            continue
    return {"resident_mb": res // 1024, "file_mb": file // 1024, "procs": n, "ticks": ticks}


def pw_errors(name_part):
    """Summe der PipeWire-Fehlerzähler (xruns) für Knoten, deren Name name_part enthält."""
    if not shutil.which("pw-top") or not name_part:
        return None
    try:
        out = subprocess.run(["pw-top", "-b", "-n", "2"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    total, found = 0, False
    for line in out.splitlines():
        cols = line.split()
        if len(cols) >= 10 and cols[8].isdigit() and name_part in cols[-1]:
            total += int(cols[8])
            found = True
    return total if found else None


# ---------------------------------------------------------------------------
# Audio-Ausgang (PipeWire über pactl)
# ---------------------------------------------------------------------------
def pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=15)


def list_sinks():
    try:
        out = pactl("list", "short", "sinks").stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.split("\t")[1] for line in out.splitlines() if "\t" in line]


def default_sink():
    try:
        return pactl("get-default-sink").stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def setup_sink(sink_part, airplay):
    if not shutil.which("pactl"):
        log("WARNUNG: pactl fehlt – Audio-Ausgang wird nicht gesetzt.")
        return ""
    if airplay:
        log("AirPlay-Erkennung einschalten (module-raop-discover) …")
        pactl("load-module", "module-raop-discover")
        sink_part = sink_part or "raop"
    if not sink_part:
        return default_sink()
    deadline = time.time() + (45 if airplay else 10)
    while time.time() < deadline:
        matches = [s for s in list_sinks() if sink_part in s]
        if matches:
            pactl("set-default-sink", matches[0])
            log(f"Audio-Ausgang: {matches[0]}")
            return matches[0]
        time.sleep(2)
    sys.exit(f"Kein Audio-Ausgang mit '{sink_part}' gefunden. Vorhanden: {', '.join(list_sinks()) or '-'}")


# ---------------------------------------------------------------------------
# Chrome DevTools Protocol (minimaler Client)
# ---------------------------------------------------------------------------
class CDP:
    def __init__(self, ws):
        self.ws = ws
        self._id = 0
        self._pending = {}
        self.handlers = []
        self.closed = asyncio.Event()
        self._task = asyncio.create_task(self._reader())

    @classmethod
    async def connect(cls, session, ws_url):
        ws = await session.ws_connect(ws_url, max_msg_size=0, autoping=True)
        return cls(ws)

    async def _reader(self):
        try:
            async for msg in self.ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                if "id" in data:
                    fut = self._pending.pop(data["id"], None)
                    if fut and not fut.done():
                        fut.set_result(data)
                else:
                    for handler in list(self.handlers):
                        handler(data)
        finally:
            self.closed.set()
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("CDP-Verbindung geschlossen"))
            self._pending.clear()

    async def send(self, method, params=None, timeout=30):
        if self.closed.is_set():
            raise ConnectionError("CDP-Verbindung geschlossen")
        self._id += 1
        fut = asyncio.get_running_loop().create_future()
        self._pending[self._id] = fut
        await self.ws.send_str(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        data = await asyncio.wait_for(fut, timeout)
        if "error" in data:
            raise RuntimeError(f"{method}: {data['error'].get('message')}")
        return data.get("result", {})

    async def eval(self, expr, gesture=False, timeout=30):
        res = await self.send("Runtime.evaluate", {
            "expression": expr, "awaitPromise": True, "returnByValue": True, "userGesture": gesture,
        }, timeout)
        if "exceptionDetails" in res:
            det = res["exceptionDetails"]
            raise RuntimeError((det.get("exception") or {}).get("description") or det.get("text"))
        return (res.get("result") or {}).get("value")

    async def close(self):
        await self.ws.close()


async def page_targets(session):
    async with session.get(f"{CDP_HTTP}/json/list") as r:
        return [t for t in await r.json(content_type=None) if t.get("type") == "page"]


class Browser:
    """Startet Chrome, verbindet sich mit der ersten Seite, räumt zuverlässig auf."""

    def __init__(self, profile, window, memory_max=None):
        self.flags = COMMON_FLAGS + PROFILES[profile] + [f"--window-size={window}"]
        self.memory_max = memory_max
        self.proc = None
        self.session = None
        self.page = None
        self.pid = None
        self.capped = False

    def _spawn(self, use_cap):
        cmd = [find_chrome(), *self.flags, f"--user-data-dir={PROFILE}",
               f"--remote-debugging-port={CDP_PORT}", "about:blank"]
        if use_cap:
            cmd = ["systemd-run", "--user", "--scope", "--quiet",
                   "-p", f"MemoryMax={self.memory_max}", *cmd]
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)

    async def start(self):
        PROFILE.mkdir(parents=True, exist_ok=True)
        for lock in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            try:
                (PROFILE / lock).unlink()
            except FileNotFoundError:
                pass
        use_cap = bool(self.memory_max and shutil.which("systemd-run"))
        self.proc = self._spawn(use_cap)
        await asyncio.sleep(3)
        if use_cap and self.proc.poll() is not None:
            err = self.proc.stderr.read().decode(errors="replace").strip()
            log(f"WARNUNG: Speicherlimit per systemd-run nicht möglich ({err[:160]}). Starte ohne Limit.")
            use_cap = False
            self.proc = self._spawn(False)
        self.capped = use_cap
        self.session = aiohttp.ClientSession()
        deadline = time.time() + 120
        while True:
            try:
                targets = await page_targets(self.session)
                if targets:
                    break
            except aiohttp.ClientError:
                pass
            if self.proc.poll() is not None:
                err = self.proc.stderr.read().decode(errors="replace").strip()
                raise RuntimeError(f"Chrome ist beim Start beendet worden: {err[-400:]}")
            if time.time() > deadline:
                raise RuntimeError("Chrome antwortet nicht auf dem DevTools-Port.")
            await asyncio.sleep(1)
        self.page = await CDP.connect(self.session, targets[0]["webSocketDebuggerUrl"])
        for _ in range(20):
            self.pid = browser_pid()
            if self.pid:
                break
            await asyncio.sleep(0.5)
        return self

    async def open_apple(self, block_images=True, timeout=240):
        """Lädt music.apple.com und wartet, bis MusicKit bereit ist. Gibt Sekunden zurück."""
        if block_images:
            await self.page.send("Network.enable")
            await self.page.send("Network.setBlockedURLs", {"urls": BLOCKED_URLS})
        url = os.environ.get("ZF_URL", APPLE_URL)
        t0 = time.time()
        await self.page.send("Page.navigate", {"url": url})
        while time.time() - t0 < timeout:
            try:
                if await self.page.eval(JS_READY, timeout=10):
                    return time.time() - t0
            except (RuntimeError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(2)
        raise RuntimeError(f"MusicKit war nach {timeout} s nicht bereit.")

    async def stop(self):
        try:
            if self.page:
                await self.page.close()
        except Exception:
            pass
        if self.session:
            await self.session.close()
        leftovers = process_tree(self.pid) if self.pid else set()
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        # Prozesse, die eine eigene Sitzung geöffnet haben, gezielt beenden.
        for pid in leftovers:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def parse_album(value):
    m = re.search(r"/album/(?:[^/]+/)?(\d+)", value)
    if m:
        return m.group(1)
    if value.isdigit():
        return value
    sys.exit(f"Album nicht erkannt: {value!r}. Erwartet: Apple-Music-Album-Link oder -ID.")


# ---------------------------------------------------------------------------
# login: Live-Ansicht der Apple-Seite im eigenen Browser
# ---------------------------------------------------------------------------
LOGIN_HTML = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Apple Music verbinden</title>
<style>
 body{margin:0;font:15px system-ui,sans-serif;background:#111;color:#eee}
 header{padding:10px 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
 #status{font-weight:600} #status.ok{color:#5d5}
 #wrap{position:relative;max-width:1000px;margin:0 auto}
 canvas{width:100%;height:auto;display:block;background:#222;touch-action:manipulation;cursor:pointer}
 #kbd{position:absolute;left:-9999px;top:0;width:1px;height:1px;opacity:0}
 input[type=text]{padding:6px;width:220px} button{padding:6px 10px}
 small{color:#aaa}
</style></head><body>
<header><span id="status">Verbinde …</span>
 <span><input id="paste" type="text" placeholder="Text einfügen (z. B. Passwort)" autocomplete="off">
 <button id="send">Senden</button></span>
 <small>Tippen auf das Bild = Klick. Danach Tastatur benutzen.</small></header>
<div id="wrap"><canvas id="c" width="1000" height="800"></canvas>
<textarea id="kbd" autocapitalize="off" autocomplete="off" spellcheck="false"></textarea></div>
<script>
const c=document.getElementById('c'),ctx=c.getContext('2d'),kbd=document.getElementById('kbd');
const st=document.getElementById('status');let fw=1000,fh=800;
const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
const send=o=>ws.readyState===1&&ws.send(JSON.stringify(o));
ws.onopen=()=>{st.textContent='Verbunden – bitte bei Apple anmelden.'};
ws.onclose=()=>{if(!st.classList.contains('ok'))st.textContent='Verbindung beendet.'};
ws.onmessage=ev=>{const m=JSON.parse(ev.data);
 if(m.type==='frame'){const img=new Image();img.onload=()=>{if(c.width!==img.width||c.height!==img.height){c.width=img.width;c.height=img.height;}ctx.drawImage(img,0,0);};
  img.src='data:image/jpeg;base64,'+m.data;fw=m.w||fw;fh=m.h||fh;}
 else if(m.type==='status'){st.textContent=m.text;st.classList.toggle('ok',!!m.done);}};
const pos=e=>{const r=c.getBoundingClientRect();return{x:(e.clientX-r.left)*fw/r.width,y:(e.clientY-r.top)*fh/r.height};};
c.addEventListener('click',e=>{const p=pos(e);send({type:'click',x:p.x,y:p.y});kbd.focus({preventScroll:true});});
c.addEventListener('wheel',e=>{e.preventDefault();const p=pos(e);send({type:'wheel',x:p.x,y:p.y,dy:e.deltaY});},{passive:false});
const special=['Enter','Backspace','Tab','Escape','ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Delete'];
kbd.addEventListener('keydown',e=>{if(special.includes(e.key)){e.preventDefault();send({type:'key',key:e.key,shift:e.shiftKey});}});
kbd.addEventListener('input',()=>{if(kbd.value){send({type:'text',text:kbd.value});kbd.value='';}});
document.getElementById('send').onclick=()=>{const p=document.getElementById('paste');if(p.value){send({type:'text',text:p.value});p.value='';}kbd.focus({preventScroll:true});};
</script></body></html>"""

KEYS = {
    "Enter": (13, "\r"), "Backspace": (8, ""), "Tab": (9, ""), "Escape": (27, ""),
    "ArrowLeft": (37, ""), "ArrowUp": (38, ""), "ArrowRight": (39, ""), "ArrowDown": (40, ""),
    "Delete": (46, ""),
}


class LoginServer:
    def __init__(self, browser):
        self.browser = browser
        self.active = browser.page  # Seite, die gerade übertragen wird
        self.active_id = None
        self.clients = set()
        self.connections = {}  # target-id -> CDP
        self.done = asyncio.Event()
        self.status = "Lade music.apple.com …"

    async def broadcast(self, obj):
        msg = json.dumps(obj)
        for ws in list(self.clients):
            try:
                await ws.send_str(msg)
            except (ConnectionError, RuntimeError):
                self.clients.discard(ws)

    def _on_event(self, cdp):
        def handler(ev):
            if ev.get("method") != "Page.screencastFrame" or cdp is not self.active:
                return
            p = ev["params"]
            meta = p.get("metadata", {})
            asyncio.create_task(cdp.send("Page.screencastFrameAck", {"sessionId": p["sessionId"]}))
            asyncio.create_task(self.broadcast({
                "type": "frame", "data": p["data"],
                "w": meta.get("deviceWidth"), "h": meta.get("deviceHeight"),
            }))
        return handler

    async def _activate(self, cdp):
        if self.active is not cdp:
            try:
                await self.active.send("Page.stopScreencast")
            except Exception:
                pass
        self.active = cdp
        if not getattr(cdp, "_zf_screencast", False):
            cdp.handlers.append(self._on_event(cdp))
            cdp._zf_screencast = True
        await cdp.send("Page.enable")
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 60,
                                                "maxWidth": 1000, "maxHeight": 1000})

    async def watch_targets(self):
        """Folgt Popups (z. B. Apple-Login-Fenster) und kehrt danach zur Hauptseite zurück."""
        main_id = (await page_targets(self.browser.session))[0]["id"]
        self.connections[main_id] = self.browser.page
        self.active_id = main_id
        while not self.done.is_set():
            try:
                targets = await page_targets(self.browser.session)
            except aiohttp.ClientError:
                await asyncio.sleep(1.5)
                continue
            ids = [t["id"] for t in targets]
            new = [t for t in targets if t["id"] not in self.connections]
            if new:
                t = new[-1]
                cdp = await CDP.connect(self.browser.session, t["webSocketDebuggerUrl"])
                self.connections[t["id"]] = cdp
                self.active_id = t["id"]
                await self._activate(cdp)
                log("Popup-Fenster erkannt – übertrage dieses.")
            elif self.active_id not in ids:
                self.connections.pop(self.active_id, None)
                self.active_id = main_id
                await self._activate(self.browser.page)
                log("Popup geschlossen – zurück zur Hauptseite.")
            await asyncio.sleep(1.5)

    async def watch_auth(self):
        while not self.done.is_set():
            try:
                authed = await self.browser.page.eval(JS_AUTHED, timeout=10)
            except (RuntimeError, asyncio.TimeoutError, ConnectionError):
                authed = False
            if authed:
                self.status = "Angemeldet ✓ – du kannst dieses Fenster schließen."
                await self.broadcast({"type": "status", "text": self.status, "done": True})
                log("Anmeldung erfolgreich. Sitzung im Profil gespeichert.")
                await asyncio.sleep(3)
                self.done.set()
                return
            await asyncio.sleep(2)

    async def handle_ws(self, request):
        ws = web.WebSocketResponse(max_msg_size=1 << 20)
        await ws.prepare(request)
        self.clients.add(ws)
        await ws.send_str(json.dumps({"type": "status", "text": self.status}))
        try:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    await self.input(json.loads(msg.data))
                except Exception as exc:  # Eingabefehler dürfen den Server nicht beenden
                    log(f"Eingabe nicht zugestellt: {exc}")
        finally:
            self.clients.discard(ws)
        return ws

    async def input(self, m):
        page = self.active
        kind = m.get("type")
        if kind == "click":
            x, y = float(m["x"]), float(m["y"])
            await page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
            for t in ("mousePressed", "mouseReleased"):
                await page.send("Input.dispatchMouseEvent",
                                {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1})
        elif kind == "wheel":
            await page.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": float(m["x"]),
                                                         "y": float(m["y"]), "deltaX": 0,
                                                         "deltaY": float(m["dy"])})
        elif kind == "text":
            # Eingaben werden bewusst nicht protokolliert (Passwort!).
            await page.send("Input.insertText", {"text": str(m["text"])[:512]})
        elif kind == "key" and m.get("key") in KEYS:
            code, text = KEYS[m["key"]]
            mods = 8 if m.get("shift") else 0
            base = {"key": m["key"], "code": m["key"], "windowsVirtualKeyCode": code, "modifiers": mods}
            await page.send("Input.dispatchKeyEvent", {"type": "keyDown", "text": text, **base})
            await page.send("Input.dispatchKeyEvent", {"type": "keyUp", **base})


async def cmd_login(args):
    browser = await Browser(args.profile, "1000,800").start()
    server = LoginServer(browser)
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text=LOGIN_HTML, content_type="text/html"))
    app.router.add_get("/ws", server.handle_ws)
    runner = web.AppRunner(app)
    await runner.setup()
    host, port = args.listen.rsplit(":", 1)
    await web.TCPSite(runner, host, int(port)).start()
    if host not in ("127.0.0.1", "localhost", "::1"):
        log("ACHTUNG: Der Login-Server ist im Netz erreichbar und unverschlüsselt. "
            "Tastatureingaben (Passwort!) laufen im Klartext. Besser per SSH-Tunnel.")
    log(f"Login-Seite: http://{args.listen}/  (vom Laptop: ssh -L {port}:127.0.0.1:{port} <pi>)")
    try:
        await server._activate(browser.page)
        secs = await browser.open_apple(block_images=False)
        log(f"MusicKit bereit nach {secs:.0f} s.")
        if await browser.page.eval(JS_AUTHED):
            log("Bereits angemeldet – nichts zu tun.")
            return 0
        server.status = "Bitte bei Apple anmelden (oben rechts „Anmelden“)."
        await server.broadcast({"type": "status", "text": server.status})
        watchers = [asyncio.create_task(server.watch_targets()), asyncio.create_task(server.watch_auth())]
        try:
            await asyncio.wait_for(server.done.wait(), timeout=args.timeout * 60)
        except asyncio.TimeoutError:
            log(f"Keine Anmeldung innerhalb von {args.timeout} min – Abbruch.")
            return 1
        finally:
            for w in watchers:
                w.cancel()
        return 0
    finally:
        await runner.cleanup()
        await browser.stop()


# ---------------------------------------------------------------------------
# check / run: Messung
# ---------------------------------------------------------------------------
def system_sample():
    mi = read_meminfo()
    orig, comp = zram_stats()
    return {
        "mem_available_mb": mi.get("MemAvailable", 0),
        "mem_total_mb": mi.get("MemTotal", 0),
        "swap_used_mb": mi.get("SwapTotal", 0) - mi.get("SwapFree", 0),
        "zram_orig_mb": orig,
        "zram_comp_mb": comp,
        "load1": float(open("/proc/loadavg").read().split()[0]),
    }


async def baseline(seconds=10):
    vals = []
    for _ in range(seconds // 2):
        vals.append(read_meminfo().get("MemAvailable", 0))
        await asyncio.sleep(2)
    return min(vals)


async def cmd_check(args):
    base = await baseline()
    log(f"Ohne Chrome frei verfügbar: {base} MB (MemTotal {read_meminfo()['MemTotal']} MB)")
    browser = await Browser(args.profile, "640,480", args.memory_max).start()
    try:
        secs = await browser.open_apple(block_images=not args.no_block_images)
        widevine = await browser.page.eval(JS_WIDEVINE)
        authed = await browser.page.eval(JS_AUTHED)
        await asyncio.sleep(15)
        use = chrome_usage(browser.pid) if browser.pid else {}
        sysd = system_sample()
        log(f"MusicKit bereit nach {secs:.0f} s")
        log(f"Widevine: {widevine}")
        log(f"Angemeldet: {'ja' if authed else 'nein – zuerst ./feasibility.py login'}")
        log(f"Chrome (Leerlauf, Profil {args.profile}): {use.get('resident_mb')} MB resident, "
            f"{use.get('file_mb')} MB verdrängbar, {use.get('procs')} Prozesse")
        log(f"System: {sysd['mem_available_mb']} MB frei, Swap belegt {sysd['swap_used_mb']} MB")
        return 0 if widevine == "ok" else 1
    finally:
        await browser.stop()


async def cmd_run(args):
    album = parse_album(args.album)
    out_dir = RESULTS / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    base = await baseline()
    log(f"Ohne Chrome frei verfügbar: {base} MB")
    sink = setup_sink(args.sink, args.airplay)
    xrun_start = pw_errors(sink)
    oom_start = read_vmstat("oom_kill")

    browser = await Browser(args.profile, "640,480", args.memory_max).start()
    crashed = []
    summary = {"profile": args.profile, "album": album, "sink": sink, "baseline_available_mb": base,
               "memory_cap": browser.memory_max if browser.capped else None}
    rows = []
    try:
        browser.page.handlers.append(
            lambda ev: crashed.append(time.time()) if ev.get("method") == "Inspector.targetCrashed" else None)
        await browser.page.send("Inspector.enable")
        t_ready = await browser.open_apple(block_images=not args.no_block_images)
        summary["musickit_ready_s"] = round(t_ready, 1)
        log(f"MusicKit bereit nach {t_ready:.0f} s")
        summary["widevine"] = await browser.page.eval(JS_WIDEVINE)
        if summary["widevine"] != "ok":
            log(f"Widevine {summary['widevine']} – ohne Widevine keine Wiedergabe.")
        if not await browser.page.eval(JS_AUTHED):
            sys.exit("Nicht bei Apple angemeldet. Zuerst: ./feasibility.py login")

        t0 = time.time()
        await browser.page.eval(JS_PLAY % {"album": json.dumps(album), "volume": args.volume / 100},
                                gesture=True)
        resumed = False
        while True:
            st = await browser.page.eval(JS_STATE)
            if st["playing"] and st["pos"] > 0.5:
                break
            if st.get("err"):
                log(f"MusicKit-Fehler: {st['err']}")
            if not resumed and time.time() - t0 > 25:
                await browser.page.eval(JS_RESUME, gesture=True)
                resumed = True
            if time.time() - t0 > 120:
                raise RuntimeError(f"Wiedergabe startet nicht (Status {st}).")
            await asyncio.sleep(1)
        summary["time_to_play_s"] = round(time.time() - t0, 1)
        log(f"Wiedergabe läuft nach {summary['time_to_play_s']} s: {st['title']}")

        end = time.time() + args.minutes * 60
        last_pos, last_title, last_ticks, last_t = st["pos"], st["title"], None, time.time()
        stall_s = 0.0
        errors = []
        while time.time() < end:
            await asyncio.sleep(args.interval)
            now = time.time()
            if crashed or browser.page.closed.is_set():
                log("Chrome-Seite abgestürzt oder Verbindung verloren!")
                summary["crash"] = True
                break
            try:
                st = await browser.page.eval(JS_STATE, timeout=20)
            except (RuntimeError, asyncio.TimeoutError, ConnectionError) as exc:
                errors.append(f"state: {exc}")
                st = {"playing": False, "pos": last_pos, "title": last_title, "authed": True, "err": ""}
            if st.get("err"):
                errors.append(st["err"])
            progressed = st["title"] != last_title or abs(st["pos"] - last_pos) >= 1.0
            if not progressed:
                stall_s += now - last_t
            use = chrome_usage(browser.pid) if browser.pid else {"resident_mb": 0, "file_mb": 0,
                                                                   "procs": 0, "ticks": 0}
            cpu = None
            if last_ticks is not None:
                cpu = round((use["ticks"] - last_ticks) / CLK_TCK / (now - last_t) * 100, 1)
            sysd = system_sample()
            row = {
                "t_s": round(now - t0), "playing": st["playing"], "title": st["title"],
                "pos_s": round(st["pos"], 1), "progressed": progressed,
                "chrome_resident_mb": use["resident_mb"], "chrome_file_mb": use["file_mb"],
                "chrome_procs": use["procs"], "chrome_cpu_pct": cpu, **sysd,
                "oom_kills": read_vmstat("oom_kill") - oom_start, "sink": default_sink(),
                "authed": st.get("authed"),
            }
            rows.append(row)
            log(f"{row['t_s']:>5}s {'▶' if progressed else '‖'} Chrome {use['resident_mb']:>3} MB "
                f"(+{use['file_mb']} verdrängbar) | frei {sysd['mem_available_mb']:>3} MB | "
                f"Swap {sysd['swap_used_mb']:>3} MB | CPU {cpu if cpu is not None else '-':>5}% | "
                f"{st['title'][:30]}")
            last_pos, last_title, last_ticks, last_t = st["pos"], st["title"], use["ticks"], now
        summary["stall_s"] = round(stall_s)
        summary["errors"] = errors[-20:]
    finally:
        xrun_end = pw_errors(sink)
        await browser.stop()

    if rows:
        with open(out_dir / "samples.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    summary.update({
        "samples": len(rows),
        "chrome_resident_max_mb": max((r["chrome_resident_mb"] for r in rows), default=None),
        "mem_available_min_mb": min((r["mem_available_mb"] for r in rows), default=None),
        "swap_used_max_mb": max((r["swap_used_mb"] for r in rows), default=None),
        "chrome_cpu_avg_pct": round(sum(r["chrome_cpu_pct"] or 0 for r in rows[1:]) / max(len(rows) - 1, 1), 1),
        "oom_kills": read_vmstat("oom_kill") - oom_start,
        "xruns": (xrun_end - xrun_start) if (xrun_start is not None and xrun_end is not None) else None,
        "crash": summary.get("crash", False),
    })
    checks = [
        ("Chrome-Speicher (resident) max", summary["chrome_resident_max_mb"], f"≤ {args.max_chrome_mb} MB",
         summary["chrome_resident_max_mb"] is not None and summary["chrome_resident_max_mb"] <= args.max_chrome_mb),
        ("Freier Speicher min", summary["mem_available_min_mb"], f"≥ {args.min_available_mb} MB",
         summary["mem_available_min_mb"] is not None and summary["mem_available_min_mb"] >= args.min_available_mb),
        ("OOM-Kills", summary["oom_kills"], "= 0", summary["oom_kills"] == 0),
        ("Absturz Chrome-Seite", summary["crash"], "nein", not summary["crash"]),
        ("Stillstand der Wiedergabe", f"{summary.get('stall_s', '-')} s", f"≤ {args.max_stall_s} s",
         summary.get("stall_s", 1e9) <= args.max_stall_s),
        ("Dauer erreicht", f"{len(rows) * args.interval // 60} min", f"{args.minutes} min",
         len(rows) * args.interval >= args.minutes * 60 - args.interval),
    ]
    verdict = all(c[3] for c in checks)
    summary["checks"] = [{"name": c[0], "value": c[1], "limit": c[2], "ok": c[3]} for c in checks]
    summary["verdict"] = "PASST" if verdict else "PASST NICHT"
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print("\n" + "=" * 64)
    print(f"Ergebnis ({args.profile}, {args.minutes} min, Ausgang {sink or 'Standard'}):")
    for name, value, limit, ok in checks:
        print(f"  {'✔' if ok else '✘'} {name:30s} {str(value):>10}   Grenze {limit}")
    print(f"  · MusicKit bereit nach {summary.get('musickit_ready_s')} s, Wiedergabe nach "
          f"{summary.get('time_to_play_s')} s, Chrome-CPU Ø {summary['chrome_cpu_avg_pct']} %")
    print(f"  · Swap max {summary['swap_used_max_mb']} MB, PipeWire-Aussetzer (xruns): "
          f"{summary['xruns'] if summary['xruns'] is not None else 'nicht messbar'}")
    print(f"\n  URTEIL: {summary['verdict']}")
    print(f"  Daten: {out_dir}/summary.json, samples.csv")
    print("  Hörbare Aussetzer am Kopfhörer bitte zusätzlich selbst notieren.")
    print("=" * 64)
    return 0 if verdict else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--profile", choices=PROFILES, default="lean",
                       help="Chrome-Profil (Standard: lean = maximal sparsam)")
        return p

    p = common(sub.add_parser("login", help="Apple-Login per Live-Ansicht"))
    p.add_argument("--listen", default="127.0.0.1:8080",
                   help="Adresse des Login-Servers (Standard 127.0.0.1:8080, Zugriff per SSH-Tunnel)")
    p.add_argument("--timeout", type=int, default=15, help="Minuten bis Abbruch (Standard 15)")

    p = common(sub.add_parser("check", help="Kurztest: Laden, Widevine, Anmeldung, Speicher"))
    p.add_argument("--memory-max", default=None, help="Hartes Speicherlimit für Chrome, z. B. 320M")
    p.add_argument("--no-block-images", action="store_true", help="Cover-Bilder nicht blockieren")

    p = common(sub.add_parser("run", help="Dauertest mit Urteil"))
    p.add_argument("--album", required=True, help="Apple-Music-Album-Link oder -ID")
    p.add_argument("--minutes", type=int, default=30)
    p.add_argument("--interval", type=int, default=10, help="Messintervall in Sekunden")
    p.add_argument("--volume", type=int, default=40, help="Lautstärke im Player 0–100 (Standard 40)")
    p.add_argument("--sink", default="", help="Teil des PipeWire-Ausgangsnamens, z. B. bluez oder raop")
    p.add_argument("--airplay", action="store_true", help="AirPlay-Lautsprecher suchen und als Ausgang nutzen")
    p.add_argument("--memory-max", default=None, help="Hartes Speicherlimit für Chrome, z. B. 320M")
    p.add_argument("--no-block-images", action="store_true", help="Cover-Bilder nicht blockieren")
    p.add_argument("--max-chrome-mb", type=int, default=300)
    p.add_argument("--min-available-mb", type=int, default=50)
    p.add_argument("--max-stall-s", type=int, default=30)

    args = ap.parse_args()
    handler = {"login": cmd_login, "check": cmd_check, "run": cmd_run}[args.cmd]
    try:
        sys.exit(asyncio.run(handler(args)))
    except KeyboardInterrupt:
        sys.exit(130)
    except RuntimeError as exc:
        sys.exit(f"FEHLER: {exc}")


if __name__ == "__main__":
    main()
