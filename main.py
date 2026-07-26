"""MollyPaw - AI Agent Desktop Client
Based on Molly (摩尼), a small teddy poodle.
"""
import os
import sys
import json
import threading
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

    def set_window(self, window):
        self.window = window

    def send_message(self, message: str) -> str:
        """Send a user message to the agent and get a response."""
        try:
            response = self.agent.chat(message)
            return json.dumps({"ok": True, "response": response}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

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


def get_frontend_path():
    """Get the path to the frontend directory."""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'frontend', 'index.html')


def get_tray_icon_image():
    """Load the paw-print icon for the system tray."""
    base = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    icon_path = os.path.join(base, 'assets', 'logo.png')
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

        # Cleanup on exit
        if tray_icon and tray_icon.visible:
            tray_icon.stop()
    else:
        webview.start(debug=('--debug' in sys.argv))


if __name__ == '__main__':
    main()