"""MollyPaw - AI Agent Desktop Client + Desktop Pet"""
import os
import sys
import json
import threading
import time
import webview

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
        self.agent = AgentCore()
        self.window = None
        self.pet_window = None
        self.pet_state = "idle"  # idle | work | cry | sleep
        self._last_activity = time.time()
        self._idle_threshold = 30  # seconds before pet goes to sleep
        self._sleep_timer_started = False

    def set_window(self, window):
        self.window = window

    def set_pet_window(self, pet_window):
        self.pet_window = pet_window

    def send_message(self, message: str) -> str:
        """Send a user message to the agent and get a response."""
        self.pet_state = "work"
        self._last_activity = time.time()
        self._sleep_timer_started = False
        self._sync_pet_state()
        try:
            response = self.agent.chat(message)
            self.pet_state = "idle"
            self._last_activity = time.time()
            self._sync_pet_state()
            self._start_sleep_timer()
            return json.dumps({"ok": True, "response": response}, ensure_ascii=False)
        except Exception as e:
            self.pet_state = "cry"
            self._sync_pet_state()
            self._start_sleep_timer()
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def get_pet_state(self) -> str:
        """Return current pet state for the pet window to poll."""
        return json.dumps({"state": self.pet_state}, ensure_ascii=False)

    def set_pet_state(self, state: str) -> str:
        """Manually set pet state."""
        if state in ("idle", "work", "cry", "sleep"):
            self.pet_state = state
            self._last_activity = time.time()
            self._sync_pet_state()
            return json.dumps({"ok": True}, ensure_ascii=False)
        return json.dumps({"ok": False, "error": "Invalid state"}, ensure_ascii=False)

    def _sync_pet_state(self):
        """Push current state to the pet window via evaluate_js."""
        if self.pet_window:
            try:
                self.pet_window.evaluate_js(
                    "window.setPetState('" + self.pet_state + "');"
                )
            except Exception:
                pass

    def _start_sleep_timer(self):
        """Start a background timer that puts the pet to sleep after idle timeout."""
        def _check_sleep():
            while True:
                time.sleep(5)
                elapsed = time.time() - self._last_activity
                if elapsed >= self._idle_threshold and self.pet_state not in ("work", "sleep"):
                    self.pet_state = "sleep"
                    self._sync_pet_state()
                    break

        if not self._sleep_timer_started:
            self._sleep_timer_started = True
            t = threading.Thread(target=_check_sleep, daemon=True)
            t.start()

    def get_config(self) -> str:
        """Get current configuration (API key status, model, etc.)."""
        config = self.agent.get_config()
        return json.dumps(config, ensure_ascii=False)

    def save_config(self, config_json: str) -> str:
        """Save configuration."""
        try:
            config = json.loads(config_json)
            self.agent.save_config(config)
            return json.dumps({"ok": True}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def clear_history(self) -> str:
        """Clear chat history."""
        self.agent.clear_history()
        return json.dumps({"ok": True}, ensure_ascii=False)


def _base_dir():
    """Return the project root (works for both dev and frozen builds)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_frontend_path():
    """Get the path to the frontend directory."""
    return os.path.join(_base_dir(), 'frontend', 'index.html')


def get_pet_frontend_path():
    """Get the path to the pet frontend page."""
    return os.path.join(_base_dir(), 'frontend', 'pet.html')


def get_tray_icon_image():
    """Load the paw-print icon for the system tray."""
    icon_path = os.path.join(_base_dir(), 'assets', 'logo.png')
    if os.path.exists(icon_path):
        return Image.open(icon_path).convert('RGBA').resize((64, 64), Image.LANCZOS)
    return Image.new('RGBA', (64, 64), (139, 94, 60, 255))


def create_tray_icon(window):
    """Create the system tray icon with menu."""
    icon_image = get_tray_icon_image()

    def on_show(icon, item):
        window.show()
        window.focus()

    def on_quit(icon, item):
        icon.stop()
        window.destroy()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Show MollyPaw", on_show, default=True),
        pystray.MenuItem("Quit", on_quit),
    )

    return pystray.Icon("MollyPaw", icon_image, "MollyPaw Agent", menu)


def main():
    api = MollyPawAPI()

    window = webview.create_window(
        'MollyPaw',
        get_frontend_path(),
        width=1000,
        height=700,
        min_size=(800, 600),
        js_api=api,
        text_select=True,
    )
    api.set_window(window)

    # Create floating desktop pet window (transparent, frameless, always on top)
    pet_window = webview.create_window(
        'MollyPaw Pet',
        get_pet_frontend_path(),
        width=200,
        height=220,
        frameless=True,
        transparent=True,
        on_top=True,
        js_api=api,
        resizable=False,
    )
    api.set_pet_window(pet_window)

    # Start idle->sleep timer after pet page loads
    pet_window.events.loaded += lambda: threading.Thread(
        target=lambda: (time.sleep(1), api._start_sleep_timer()),
        daemon=True,
    ).start()

    if HAS_TRAY:
        tray_icon = None

        def on_closed():
            """Minimize to tray instead of quitting."""
            if tray_icon and tray_icon.visible:
                window.hide()

        window.events.closed += on_closed

        def start_tray():
            nonlocal tray_icon
            tray_icon = create_tray_icon(window)
            tray_icon.run()

        tray_thread = threading.Thread(target=start_tray, daemon=True)
        tray_thread.start()

        webview.start(debug=('--debug' in sys.argv))

        if tray_icon and tray_icon.visible:
            tray_icon.stop()
    else:
        webview.start(debug=('--debug' in sys.argv))


if __name__ == '__main__':
    main()
