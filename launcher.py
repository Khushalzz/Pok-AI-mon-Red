"""
launcher.py — AI Pokemon NPC Launcher
Single-click GUI to set up dependencies, patch your ROM, and run the server.
Uses only tkinter (built into Python — nothing to install).
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import subprocess
import sys
import os
import threading
import socket
import time

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
VENV_DIR      = os.path.join(SCRIPT_DIR, "venv")
VENV_PYTHON   = os.path.join(VENV_DIR, "Scripts", "python.exe") if os.name == "nt" else os.path.join(VENV_DIR, "bin", "python")
SERVER_SCRIPT = os.path.join(SCRIPT_DIR, "server.py")
PATCH_SCRIPT  = os.path.join(SCRIPT_DIR, "patch_rom.py")
BRIDGE_LUA    = os.path.join(SCRIPT_DIR, "bridge.lua")

REQUIRED_PACKAGES = ["transformers", "torch", "accelerate", "peft"]

# ── Color palette ──────────────────────────────────────────────────────────────
BG      = "#0F0F1A"
BG2     = "#1A1A2E"
BG3     = "#16213E"
ACCENT  = "#E94560"
GREEN   = "#0F9B58"
YELLOW  = "#F5A623"
TEXT    = "#E0E0E0"
SUBTEXT = "#888899"
BORDER  = "#2A2A4A"


class StatusIndicator(tk.Frame):
    """A colored circle + label status widget."""
    def __init__(self, parent, label, **kw):
        super().__init__(parent, bg=BG2, **kw)
        self.canvas = tk.Canvas(self, width=14, height=14, bg=BG2,
                                highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, padx=(0, 8))
        self.dot = self.canvas.create_oval(2, 2, 12, 12, fill=SUBTEXT, outline="")
        self.lbl = tk.Label(self, text=label, bg=BG2, fg=TEXT,
                            font=("Segoe UI", 10))
        self.lbl.pack(side=tk.LEFT)

    def set_state(self, state):
        """State: 'ok', 'warn', 'error', 'idle'"""
        colors = {"ok": GREEN, "warn": YELLOW, "error": ACCENT, "idle": SUBTEXT}
        self.canvas.itemconfig(self.dot, fill=colors.get(state, SUBTEXT))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Pokémon NPC Launcher")
        self.configure(bg=BG)
        self.resizable(False, False)
        self._server_proc = None
        self._monitor_thread = None
        self._build_ui()
        self._center()
        # Check venv on startup
        self.after(200, self._check_venv)

    # ── UI Construction ─────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        header = tk.Frame(self, bg=ACCENT, height=4)
        header.pack(fill=tk.X)

        title_frame = tk.Frame(self, bg=BG, pady=16)
        title_frame.pack(fill=tk.X, padx=24)

        tk.Label(title_frame, text="🎮 AI Pokémon NPC", bg=BG, fg=TEXT,
                 font=("Segoe UI", 20, "bold")).pack(anchor=tk.W)
        tk.Label(title_frame, text="One-click server launcher for the NPC AI mod",
                 bg=BG, fg=SUBTEXT, font=("Segoe UI", 10)).pack(anchor=tk.W)

        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.pack(fill=tk.X, padx=24)

        # ── Status Panel ──
        status_outer = tk.Frame(self, bg=BG2, pady=12, padx=16)
        status_outer.pack(fill=tk.X, padx=24, pady=(16, 0))

        tk.Label(status_outer, text="STATUS", bg=BG2, fg=SUBTEXT,
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, pady=(0, 8))

        row1 = tk.Frame(status_outer, bg=BG2)
        row1.pack(fill=tk.X)
        self.si_deps   = StatusIndicator(row1, "Dependencies")
        self.si_deps.pack(side=tk.LEFT, padx=(0, 24))
        self.si_server = StatusIndicator(row1, "Server")
        self.si_server.pack(side=tk.LEFT, padx=(0, 24))
        self.si_mgba   = StatusIndicator(row1, "mGBA Connected")
        self.si_mgba.pack(side=tk.LEFT)

        # ── Buttons ──
        btn_frame = tk.Frame(self, bg=BG, pady=16)
        btn_frame.pack(fill=tk.X, padx=24)

        self.btn_deps = self._make_btn(btn_frame, "⬇  Install Dependencies",
                                        ACCENT, self._install_deps)
        self.btn_deps.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_patch = self._make_btn(btn_frame, "🔧  Patch ROM",
                                         BG3, self._patch_rom)
        self.btn_patch.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_server = self._make_btn(btn_frame, "▶  Start Server",
                                          GREEN, self._toggle_server)
        self.btn_server.pack(side=tk.LEFT)

        # ── Log ──
        log_frame = tk.Frame(self, bg=BG, padx=24)
        log_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(log_frame, text="SERVER LOG", bg=BG, fg=SUBTEXT,
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, pady=(0, 4))

        self.log = scrolledtext.ScrolledText(
            log_frame, bg=BG3, fg=TEXT, font=("Consolas", 9),
            height=14, width=72, relief=tk.FLAT,
            insertbackground=TEXT, borderwidth=0,
            state=tk.DISABLED
        )
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log.tag_config("ok",    foreground=GREEN)
        self.log.tag_config("warn",  foreground=YELLOW)
        self.log.tag_config("err",   foreground=ACCENT)
        self.log.tag_config("info",  foreground=TEXT)
        self.log.tag_config("dim",   foreground=SUBTEXT)

        # ── Instructions ──
        inst_frame = tk.Frame(self, bg=BG2, padx=16, pady=12)
        inst_frame.pack(fill=tk.X, padx=24, pady=(0, 16))

        tk.Label(inst_frame, text="HOW TO USE", bg=BG2, fg=SUBTEXT,
                 font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, pady=(0, 6))

        steps = [
            "1. Click 'Patch ROM' to select and patch your Pokemon Red ROM.",
            "2. Click 'Start Server' to launch the AI backend.",
            "3. Open mGBA and load the patched ROM (AI).gb file.",
            "4. In mGBA: Tools → Scripting → File → Load script → bridge.lua",
            "5. Talk to any NPC. 2nd interaction = AI joke! 🎉",
        ]
        for step in steps:
            tk.Label(inst_frame, text=step, bg=BG2, fg=TEXT,
                     font=("Segoe UI", 9), anchor=tk.W, justify=tk.LEFT
                     ).pack(anchor=tk.W)

        # ── Bridge LUA path ──
        lua_path_frame = tk.Frame(self, bg=BG, padx=24)
        lua_path_frame.pack(fill=tk.X, pady=(0, 16))
        tk.Label(lua_path_frame, text="bridge.lua location: ", bg=BG,
                 fg=SUBTEXT, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        tk.Label(lua_path_frame, text=BRIDGE_LUA, bg=BG,
                 fg=YELLOW, font=("Consolas", 8),
                 cursor="hand2").pack(side=tk.LEFT)
        
        btn_copy = tk.Button(lua_path_frame, text="📋 Copy", bg=BG2, fg=TEXT, 
                             font=("Segoe UI", 8), cursor="hand2", relief=tk.FLAT,
                             command=self._copy_lua_path)
        btn_copy.pack(side=tk.LEFT, padx=(10, 0))

    def _copy_lua_path(self):
        self.clipboard_clear()
        self.clipboard_append(BRIDGE_LUA)
        self._log("✔ Copied bridge.lua path to clipboard!", "ok")

    def _make_btn(self, parent, text, color, command):
        btn = tk.Button(
            parent, text=text, command=command,
            bg=color, fg="white", font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT, padx=16, pady=8, cursor="hand2",
            activebackground=color, activeforeground="white",
            borderwidth=0
        )
        return btn

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    # ── Logging ─────────────────────────────────────────────────────────────────

    def _log(self, msg, tag="info"):
        def _write():
            self.log.config(state=tk.NORMAL)
            self.log.insert(tk.END, msg + "\n", tag)
            self.log.see(tk.END)
            self.log.config(state=tk.DISABLED)
        self.after(0, _write)

    # ── Venv & Deps ─────────────────────────────────────────────────────────────

    def _check_venv(self):
        if os.path.exists(VENV_PYTHON):
            self._log("✔ Virtual environment found.", "ok")
            self.si_deps.set_state("warn")  # might still need packages
            self._check_packages()
        else:
            self._log("Virtual environment not found. Click 'Install Dependencies'.", "warn")
            self.si_deps.set_state("idle")

    def _check_packages(self):
        def _run():
            python = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable
            kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
            try:
                result = subprocess.run(
                    [python, "-c", "import transformers, torch, peft, accelerate"],
                    capture_output=True, text=True, **kwargs
                )
                if result.returncode == 0:
                    self._log("✔ All dependencies installed.", "ok")
                    self.si_deps.set_state("ok")
                else:
                    self._log("Some packages missing. Click 'Install Dependencies'.", "warn")
                    self.si_deps.set_state("warn")
            except Exception as e:
                self._log(f"Dependency check error: {e}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _install_deps(self):
        self._log("Starting dependency installation...", "dim")
        self.si_deps.set_state("warn")

        def _run():
            python = sys.executable

            kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
            # Step 1: create venv if not exists
            if not os.path.exists(VENV_DIR):
                self._log("Creating virtual environment...", "dim")
                ret = subprocess.run([python, "-m", "venv", VENV_DIR],
                                     capture_output=True, text=True, **kwargs)
                if ret.returncode != 0:
                    self._log("Failed to create venv: " + ret.stderr, "err")
                    self.si_deps.set_state("error")
                    return
                self._log("✔ Virtual environment created.", "ok")

            # Step 2: upgrade pip
            self._log("Upgrading pip...", "dim")
            subprocess.run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"],
                           capture_output=True, text=True, **kwargs)

            # Step 3: install packages (live output)
            self._log(f"Installing: {', '.join(REQUIRED_PACKAGES)}", "dim")
            self._log("(This may take several minutes for PyTorch...)", "warn")
            proc = subprocess.Popen(
                [VENV_PYTHON, "-m", "pip", "install"] + REQUIRED_PACKAGES,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, **kwargs
            )
            for line in proc.stdout:
                self._log(line.rstrip(), "dim")
            proc.wait()

            if proc.returncode == 0:
                self._log("✔ All dependencies installed!", "ok")
                self.si_deps.set_state("ok")
            else:
                self._log("Installation failed. Check log for details.", "err")
                self.si_deps.set_state("error")

        threading.Thread(target=_run, daemon=True).start()

    # ── ROM Patching ─────────────────────────────────────────────────────────────

    def _patch_rom(self):
        rom_path = filedialog.askopenfilename(
            title="Select your Pokemon Red ROM",
            initialdir=os.path.expanduser("~"),
            filetypes=[("Game Boy ROM", "*.gb *.gbc"), ("All files", "*.*")]
        )
        if not rom_path:
            return

        base, ext = os.path.splitext(rom_path)
        out_path = base + " (AI)" + ext

        self._log(f"Patching ROM: {os.path.basename(rom_path)}", "dim")

        def _run():
            kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
            python = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable
            result = subprocess.run(
                [python, PATCH_SCRIPT, rom_path, out_path],
                capture_output=True, text=True, cwd=SCRIPT_DIR, **kwargs
            )
            for line in (result.stdout + result.stderr).splitlines():
                self._log(line, "ok" if "Success" in line else "info")

            if result.returncode == 0 and os.path.exists(out_path):
                self._log(f"✔ Patched ROM saved: {os.path.basename(out_path)}", "ok")
                self.after(0, lambda: messagebox.showinfo(
                    "ROM Patched!",
                    f"Success!\n\nPatched ROM saved to:\n{out_path}\n\n"
                    "Load this file in mGBA instead of the original."
                ))
            else:
                self._log("ROM patching failed. Check log.", "err")

        threading.Thread(target=_run, daemon=True).start()

    # ── Server Control ───────────────────────────────────────────────────────────

    def _toggle_server(self):
        if self._server_proc and self._server_proc.poll() is None:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self):
        python = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable
        self._log("Starting AI server...", "dim")
        self.si_server.set_state("warn")
        self.btn_server.config(text="⏹  Stop Server", bg=ACCENT)

        try:
            kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
            self._server_proc = subprocess.Popen(
                [python, SERVER_SCRIPT],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=SCRIPT_DIR, **kwargs
            )
        except Exception as e:
            self._log(f"Failed to start server: {e}", "err")
            self.si_server.set_state("error")
            self.btn_server.config(text="▶  Start Server", bg=GREEN)
            return

        # Stream server output to log
        def _stream():
            for line in self._server_proc.stdout:
                stripped = line.rstrip()
                if any(x in stripped for x in ["error", "Error", "ERROR", "failed", "Failed"]):
                    self._log(stripped, "err")
                elif "Connected" in stripped or "loaded" in stripped.lower() or "✔" in stripped:
                    self._log(stripped, "ok")
                    if "mGBA Connected!" in stripped:
                        self.after(0, lambda: self.si_mgba.set_state("ok"))
                    elif "Connected" in stripped and "mGBA" not in stripped:
                        self.after(0, lambda: self.si_server.set_state("ok"))
                elif "Client disconnected" in stripped:
                    self._log(stripped, "warn")
                    self.after(0, lambda: self.si_mgba.set_state("warn"))
                else:
                    self._log(stripped, "info")
            # Process ended
            self.after(0, self._on_server_stopped)

        threading.Thread(target=_stream, daemon=True).start()
        self.si_server.set_state("ok")
        self._log("✔ Server started!", "ok")

    def _stop_server(self):
        if self._server_proc:
            self._server_proc.terminate()
            self._server_proc = None
        self._on_server_stopped()

    def _on_server_stopped(self):
        self.si_server.set_state("idle")
        self.si_mgba.set_state("idle")
        self.btn_server.config(text="▶  Start Server", bg=GREEN)
        self._log("Server stopped.", "warn")

    # ── Cleanup ──────────────────────────────────────────────────────────────────

    def on_close(self):
        if self._server_proc:
            self._server_proc.terminate()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
