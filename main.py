"""MollyPaw - AI Agent Desktop Client + Desktop Pet"""
import sys
import os
import tempfile

# Single-instance lock via file
_LOCK_PATH = os.path.join(tempfile.gettempdir(), "MollyPaw.lock")
def _check_single_instance():
    try:
        # Try to open with exclusive access
        fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        # Check if the PID in the file is still alive
        try:
            with open(_LOCK_PATH, "r") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)  # Check if process exists
            return False  # Another instance is running
        except (ValueError, OSError, ProcessLookupError):
            # Lock is stale, remove it and take over
            os.remove(_LOCK_PATH)
            return _check_single_instance()

if not _check_single_instance():
    sys.exit(0)

import io
import json
import random
import subprocess

import threading

import time

import webview

import http.server



try:

    import pystray

    from PIL import Image

    HAS_TRAY = True

except ImportError:

    HAS_TRAY = False



from agent.core import AgentCore



class MollyPawAPI:

    """API exposed to the frontend via pywebview."""



    def __init__(self):

        self.agent = None

        self.window = None

        # pet is now a separate tkinter subprocess (pet.py)

        self.pet_state = "idle"  # idle | work | cry | sleep

        self._last_activity = time.time()

        self._idle_threshold = 30

        self._sleep_timer_started = False



    def set_window(self, window):

        self.window = window



    # pet is launched via subprocess, no set_pet_window needed



    def start_pet_server(self):

        """Start a local HTTP server to serve pet assets + state API."""

        pet_dir = os.path.join(_base_dir(), "assets", "pet")

        api_ref = self



        class PetHandler(http.server.BaseHTTPRequestHandler):

            def do_GET(self):
                try:
                    if self.path == "/state":
                        data = json.dumps({"state": api_ref.pet_state}).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                    else:
                        fname = self.path.lstrip("/")
                        fpath = os.path.join(pet_dir, fname)
                        if os.path.isfile(fpath):
                            with open(fpath, "rb") as f:
                                data = f.read()
                            ext = os.path.splitext(fname)[1].lower()
                            ctype = {
                                ".png": "image/png",
                                ".jpg": "image/jpeg",
                                ".gif": "image/gif",
                            }.get(ext, "application/octet-stream")
                            self.send_response(200)
                            self.send_header("Content-Type", ctype)
                            self.send_header("Content-Length", str(len(data)))
                            self.end_headers()
                            self.wfile.write(data)
                        else:
                            self.send_error(404)
                except (ConnectionAbortedError, BrokenPipeError):
                    pass



            def log_message(self, fmt, *a):

                pass



        try:

            httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 18765), PetHandler)

            threading.Thread(target=httpd.serve_forever, daemon=True).start()

            print("[MollyPaw] Pet server started on http://127.0.0.1:18765/")

        except Exception as e:

            print("[MollyPaw] Pet server failed: " + str(e))



    # -- Chat -----------------------------------------------------------------



    def send_message(self, message):
        """Send a user message to the agent and get a response."""
        self.pet_state = "work"
        self._last_activity = time.time()
        self._sleep_timer_started = False

        def _do_chat():
            try:
                if self.agent is None:
                    self.agent = AgentCore()
                response = self.agent.chat(message)
                self.pet_state = "idle"
                self._last_activity = time.time()
                self._start_sleep_timer()
                result = json.dumps({"ok": True, "response": response}, ensure_ascii=False)
            except Exception as e:
                self.pet_state = "cry"
                self._start_sleep_timer()
                result = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
            if self.window:
                self.window.evaluate_js(
                    "window._onChatResult && window._onChatResult(" + result + ")"
                )

        threading.Thread(target=_do_chat, daemon=True).start()
        return json.dumps({"ok": True, "pending": True}, ensure_ascii=False)



    # -- Pet state ------------------------------------------------------------



    def get_pet_state(self):

        return json.dumps({"state": self.pet_state}, ensure_ascii=False)



    def set_pet_state(self, state):

        if state in ("idle", "work", "cry", "sleep"):

            self.pet_state = state

            self._last_activity = time.time()

            return json.dumps({"ok": True}, ensure_ascii=False)

        return json.dumps({"ok": False, "error": "Invalid state"}, ensure_ascii=False)



    def _start_sleep_timer(self):

        def _check_sleep():

            while True:

                time.sleep(5)

                elapsed = time.time() - self._last_activity

                if elapsed >= self._idle_threshold and self.pet_state not in ("work", "sleep"):

                    self.pet_state = "sleep"

                    break



        if not self._sleep_timer_started:

            self._sleep_timer_started = True

            t = threading.Thread(target=_check_sleep, daemon=True)

            t.start()



    # -- Config ---------------------------------------------------------------



    def _push_result(self, callback, result):
        if self.window:
            self.window.evaluate_js(
                f"window.{callback} && window.{callback}({result})"
            )

    def get_config(self):
        def _work():
            try:
                if self.agent is None:
                    from agent.core import AgentCore
                    self.agent = AgentCore()
                config = self.agent.get_config()
                self._push_result("_onConfigResult", json.dumps({"ok": True, "config": config}, ensure_ascii=False))
            except Exception as e:
                self._push_result("_onConfigResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        threading.Thread(target=_work, daemon=True).start()
        return json.dumps({"ok": True, "pending": True}, ensure_ascii=False)

    def save_config(self, config_json):
        def _work():
            try:
                if self.agent is None:
                    from agent.core import AgentCore
                    self.agent = AgentCore()
                config = json.loads(config_json)
                self.agent.save_config(config)
                self._push_result("_onSaveConfigResult", json.dumps({"ok": True}, ensure_ascii=False))
            except Exception as e:
                self._push_result("_onSaveConfigResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        threading.Thread(target=_work, daemon=True).start()
        return json.dumps({"ok": True, "pending": True}, ensure_ascii=False)

    def clear_history(self):
        def _work():
            try:
                if self.agent is None:
                    from agent.core import AgentCore
                    self.agent = AgentCore()
                self.agent.clear_history()
                self._push_result("_onClearHistoryResult", json.dumps({"ok": True}, ensure_ascii=False))
            except Exception as e:
                self._push_result("_onClearHistoryResult", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        threading.Thread(target=_work, daemon=True).start()
        return json.dumps({"ok": True, "pending": True}, ensure_ascii=False)



# ---------------------------------------------------------------------------

# Paths

# ---------------------------------------------------------------------------



def _base_dir():

    if getattr(sys, "frozen", False):

        return sys._MEIPASS

    return os.path.dirname(os.path.abspath(__file__))



def get_frontend_path():

    return os.path.join(_base_dir(), "frontend", "index.html")



# ---------------------------------------------------------------------------

# System tray

# ---------------------------------------------------------------------------



def get_tray_icon_image():

    icon_path = os.path.join(_base_dir(), "assets", "logo.png")

    if os.path.exists(icon_path):

        return Image.open(icon_path).convert("RGBA").resize((64, 64), Image.LANCZOS)

    return Image.new("RGBA", (64, 64), (139, 94, 60, 255))



def create_tray_icon(window):

    icon_image = get_tray_icon_image()



    def on_show(icon, item):

        window.show()

        window.focus()



    def on_quit(icon, item):

        icon.stop()

        window.destroy()

        if _pet_process and _pet_process.poll() is None:

            _pet_process.terminate()

        os._exit(0)



    menu = pystray.Menu(

        pystray.MenuItem("Show MollyPaw", on_show, default=True),

        pystray.MenuItem("Quit", on_quit),

    )

    return pystray.Icon("MollyPaw", icon_image, "MollyPaw Agent", menu)



# ---------------------------------------------------------------------------

# Pet subprocess

# ---------------------------------------------------------------------------



_pet_process = None



class PetWindow:

    """Desktop pet tkinter window - polls pet state from HTTP server."""



    PET_SERVER = "http://127.0.0.1:18765"

    WIN_W, WIN_H = 300, 340

    IMG_SIZE = 220



    def __init__(self):

        import tkinter as tk

        from PIL import Image, ImageTk

        import urllib.request

        self._tk = tk

        self._ImageTk = ImageTk

        self._urlopen = urllib.request.urlopen



        self.root = tk.Tk()

        self.root.title("MollyPaw Pet")

        self.root.overrideredirect(True)

        self.root.attributes("-topmost", True)

        self.root.attributes("-transparentcolor", "#FF00FF")

        self.root.configure(bg="#FF00FF")



        sx = self.root.winfo_screenwidth()

        sy = self.root.winfo_screenheight()

        self.root.geometry(

            f"{self.WIN_W}x{self.WIN_H}+{sx - self.WIN_W - 30}+{sy - self.WIN_H - 60}"

        )



        self.canvas = tk.Canvas(

            self.root, width=self.WIN_W, height=self.WIN_H,

            bg="#FF00FF", highlightthickness=0,

        )

        self.canvas.pack()



        self.images = {}

        self.current_state = None

        self.anim_jobs = []

        self.zzz_items = []

        self.tear_items = []



        self._load_images()



        self._drag_x = 0

        self._drag_y = 0

        self.canvas.bind("<Button-1>", self._on_press)

        self.canvas.bind("<B1-Motion>", self._on_drag)



        self.canvas.bind("<Button-3>", self._on_right_click)

        self.menu = tk.Menu(self.root, tearoff=0)

        self.menu.add_command(label="Close", command=self.root.destroy)



        self._poll()

        self.root.mainloop()



    def _load_images(self):

        import collections

        from PIL import Image

        loaded = True

        for state in ("idle", "work", "cry", "sleep"):

            url = f"{self.PET_SERVER}/pet_{state}.png"

            try:

                data = self._urlopen(url, timeout=5).read()

                img = Image.open(io.BytesIO(data)).convert("RGBA")

                img = img.resize((self.IMG_SIZE, self.IMG_SIZE), Image.NEAREST)

                sentinel = (255, 0, 255, 255)

                bg = img.getpixel((0, 0))[:3]

                pixels = img.load()

                w, h = img.size

                visited = set()

                queue = collections.deque()

                for start in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:

                    queue.append(start)

                while queue:

                    px, py = queue.popleft()

                    if (px, py) in visited:

                        continue

                    if px < 0 or px >= w or py < 0 or py >= h:

                        continue

                    r, g, b = pixels[px, py][:3]

                    if abs(r - bg[0]) < 15 and abs(g - bg[1]) < 15 and abs(b - bg[2]) < 15:

                        visited.add((px, py))

                        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:

                            queue.append((px + dx, py + dy))

                for px, py in visited:

                    pixels[px, py] = sentinel

                self.images[state] = self._ImageTk.PhotoImage(img)

            except Exception as e:

                print(f"[Pet] Load failed {state}: {e}")

                loaded = False

        if not loaded:

            self.root.after(2000, self._load_images)



    def _set_state(self, state):

        if state == self.current_state:

            return

        if state not in self.images:

            return

        self.current_state = state

        self._cancel_anims()

        self.canvas.delete("all")

        self.canvas.create_image(

            self.WIN_W // 2, self.WIN_H // 2 + 15,

            image=self.images[state], anchor="center",

        )

        if state == "sleep":

            self._show_bubble("zzZ...")

            self._start_zzz()

        elif state == "cry":

            self._show_bubble("API连不上了...呜呜")

            self._start_tears()

        elif state == "work":

            self._show_bubble("认真翻书中~")



    def _cancel_anims(self):

        for jid in self.anim_jobs:

            try:

                self.root.after_cancel(jid)

            except Exception:

                pass

        self.anim_jobs.clear()

        self.zzz_items.clear()

        self.tear_items.clear()



    def _show_bubble(self, text):

        x, y = self.WIN_W // 2, 18

        w = max(len(text) * 10 + 24, 80)

        self.canvas.create_rectangle(

            x - w // 2, y - 14, x + w // 2, y + 14,

            fill="#FFFFFF", outline="#D2B48C", width=2, tags="overlay",

        )

        self.canvas.create_text(

            x, y, text=text, font=("Microsoft YaHei", 9),

            fill="#6B4226", tags="overlay",

        )



    def _start_zzz(self):

        self._tick_zzz(0)



    def _tick_zzz(self, idx):

        if self.current_state != "sleep":

            return

        for item in self.zzz_items:

            self.canvas.delete(item)

        self.zzz_items.clear()

        chars = [("z", 12), ("z", 16), ("Z", 20)]

        for i, (ch, sz) in enumerate(chars):

            off = ((idx + i) % 4) * 4

            item = self.canvas.create_text(

                160 + i * 16, 40 - off,

                text=ch, font=("Courier", sz, "bold"), fill="#7BA4C8",

            )

            self.zzz_items.append(item)

        jid = self.root.after(500, self._tick_zzz, idx + 1)

        self.anim_jobs.append(jid)



    def _start_tears(self):

        self._tick_tears()



    def _tick_tears(self):

        if self.current_state != "cry":

            return

        for item in self.tear_items:

            self.canvas.delete(item)

        self.tear_items.clear()

        for x_off in [75, 145]:

            y = random.randint(80, 115)

            item = self.canvas.create_oval(

                x_off - 3, y, x_off + 3, y + 8,

                fill="#5BADE5", outline="",

            )

            self.tear_items.append(item)

        jid = self.root.after(400, self._tick_tears)

        self.anim_jobs.append(jid)



    def _poll(self):

        try:

            data = self._urlopen(f"{self.PET_SERVER}/state", timeout=2).read()

            result = json.loads(data)

            self._set_state(result.get("state", "idle"))

        except Exception:

            pass

        self.root.after(1000, self._poll)



    def _on_press(self, event):

        self._drag_x = event.x_root

        self._drag_y = event.y_root



    def _on_drag(self, event):

        dx = event.x_root - self._drag_x

        dy = event.y_root - self._drag_y

        self._drag_x = event.x_root

        self._drag_y = event.y_root

        x = self.root.winfo_x() + dx

        y = self.root.winfo_y() + dy

        self.root.geometry(f"+{x}+{y}")



    def _on_right_click(self, event):

        self.menu.post(event.x_root, event.y_root)



def start_pet():

    """Launch pet in a daemon thread."""

    try:

        PetWindow()

    except Exception as e:

        print("[MollyPaw] Pet failed: " + str(e))

    if not os.path.exists(pet_script):

        print("[MollyPaw] pet.py not found, skipping pet")

        return

    try:

        _pet_process = subprocess.Popen(

            [sys.executable, pet_script],

            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),

        )

        print("[MollyPaw] Pet process started (pid={})".format(_pet_process.pid))

    except Exception as e:

        print("[MollyPaw] Failed to start pet: " + str(e))



# ---------------------------------------------------------------------------

# Entry point

# ---------------------------------------------------------------------------



def main():

    api = MollyPawAPI()

    api.start_pet_server()



    # Main chat window

    window = webview.create_window(

        "MollyPaw",

        get_frontend_path(),

        width=1000,

        height=700,

        min_size=(800, 600),

        js_api=api,

        text_select=True,

    )

    api.set_window(window)



    # Launch tkinter pet in a separate process (avoids pywebview COM issues)

    threading.Thread(target=start_pet, daemon=True).start()



    # Start sleep timer

    threading.Thread(

        target=lambda: (time.sleep(2), api._start_sleep_timer()),

        daemon=True,

    ).start()



    if HAS_TRAY:

        tray_icon = None



        def on_closed():
            pass  # Don't destroy — let tray keep the process alive



        window.events.closed += on_closed



        def start_tray():

            nonlocal tray_icon

            tray_icon = create_tray_icon(window)

            tray_icon.run()



        threading.Thread(target=start_tray, daemon=True).start()

        webview.start(debug=("--debug" in sys.argv))

        # webview.start() returns when window is closed.
        # Keep process alive for tray until os._exit(0) from tray quit.
        try:

            while True:

                time.sleep(1)

        except KeyboardInterrupt:

            pass

    else:

        webview.start(debug=("--debug" in sys.argv))



if __name__ == "__main__":
    import atexit
    atexit.register(lambda: os.remove(_LOCK_PATH) if os.path.exists(_LOCK_PATH) else None)
    main()

