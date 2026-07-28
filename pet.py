"""MollyPaw Desktop Pet - Standalone tkinter window with animations."""
import tkinter as tk
from PIL import Image, ImageTk
import urllib.request
import io
import json
import time
import random

PET_SERVER = "http://127.0.0.1:18765"
WIN_W, WIN_H = 220, 250
IMG_SIZE = 150


class PetWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("MollyPaw Pet")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", "#FFFFFF")
        self.root.configure(bg="#FFFFFF")

        sx = self.root.winfo_screenwidth()
        sy = self.root.winfo_screenheight()
        self.root.geometry(
            f"{WIN_W}x{WIN_H}+{sx - WIN_W - 30}+{sy - WIN_H - 60}"
        )

        self.canvas = tk.Canvas(
            self.root, width=WIN_W, height=WIN_H,
            bg="#FFFFFF", highlightthickness=0,
        )
        self.canvas.pack()

        self.images = {}
        self.current_state = None
        self.anim_jobs = []
        self.zzz_items = []
        self.tear_items = []

        self._load_images()

        # Drag
        self._drag_x = 0
        self._drag_y = 0
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)

        # Right-click to close
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Close", command=self.root.destroy)

        # Poll state
        self._poll()
        self.root.mainloop()

    # -- Image loading -------------------------------------------------------

    def _load_images(self):
        loaded = True
        for state in ("idle", "work", "cry", "sleep"):
            url = f"{PET_SERVER}/pet_{state}.png"
            try:
                data = urllib.request.urlopen(url, timeout=5).read()
                img = Image.open(io.BytesIO(data)).convert("RGBA")
                img = img.resize((IMG_SIZE, IMG_SIZE), Image.NEAREST)
                self.images[state] = ImageTk.PhotoImage(img)
            except Exception as e:
                print(f"[Pet] Load failed {state}: {e}")
                loaded = False
        if not loaded:
            self.root.after(2000, self._load_images)

    # -- State management ----------------------------------------------------

    def _set_state(self, state):
        if state == self.current_state:
            return
        if state not in self.images:
            return

        self.current_state = state
        self._cancel_anims()

        self.canvas.delete("all")
        self.canvas.create_image(
            WIN_W // 2, WIN_H // 2 + 15,
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

    # -- Bubble text ---------------------------------------------------------

    def _show_bubble(self, text):
        x, y = WIN_W // 2, 18
        w = max(len(text) * 10 + 24, 80)
        self.canvas.create_rectangle(
            x - w // 2, y - 14, x + w // 2, y + 14,
            fill="white", outline="#D2B48C", width=2, tags="overlay",
        )
        self.canvas.create_text(
            x, y, text=text, font=("Microsoft YaHei", 9),
            fill="#6B4226", tags="overlay",
        )

    # -- ZZZ animation (sleep) -----------------------------------------------

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

    # -- Tears animation (cry) -----------------------------------------------

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

    # -- Polling -------------------------------------------------------------

    def _poll(self):
        try:
            data = urllib.request.urlopen(f"{PET_SERVER}/state", timeout=2).read()
            result = json.loads(data)
            self._set_state(result.get("state", "idle"))
        except Exception:
            pass
        self.root.after(1000, self._poll)

    # -- Drag ----------------------------------------------------------------

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


if __name__ == "__main__":
    time.sleep(1)
    PetWindow()