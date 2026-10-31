"""md-maker-gui: a small Tk window around the md-maker CLI, with a live log."""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import cli, config


def build_argv(files, out: str, ai: str, ocr: str, rtl: bool, markers: bool, report: bool, plan: bool) -> list[str]:
    argv = [str(f) for f in files] + ["--ai", ai, "--ocr", ocr]
    if out.strip():
        argv += ["-o", out.strip()]
    argv += [flag for on, flag in ((rtl, "--rtl-wrap"), (markers, "--page-markers"),
                                   (report, "--report"), (plan, "--plan")) if on]
    return argv


class _QueueWriter:
    """File-like object the CLI prints into while it runs in the worker thread."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, text: str):
        self.q.put(text)
        return len(text)

    def flush(self):
        pass


def _open_folder(path: Path):
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        root.title("md-maker")
        root.geometry("820x620")
        root.minsize(640, 480)

        files = ttk.LabelFrame(root, text="Files (PDF, DOCX, ODT, RTF, EPUB, HTML) or folders")
        files.pack(fill="x", padx=8, pady=(8, 4))
        self.listbox = tk.Listbox(files, height=6, selectmode="extended")
        self.listbox.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        col = ttk.Frame(files)
        col.pack(side="right", fill="y", padx=6, pady=6)
        for text, cmd in (("Add files…", self.add_files), ("Add folder…", self.add_folder),
                          ("Remove", self.remove), ("Clear", lambda: self.listbox.delete(0, "end"))):
            ttk.Button(col, text=text, command=cmd).pack(fill="x", pady=1)

        outf = ttk.Frame(root)
        outf.pack(fill="x", padx=8, pady=4)
        ttk.Label(outf, text="Output folder:").pack(side="left")
        self.out = tk.StringVar()
        ttk.Entry(outf, textvariable=self.out).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(outf, text="Browse…", command=self.pick_out).pack(side="left")
        ttk.Label(root, text="Leave the output folder empty to write each .md next to its source.",
                  foreground="gray").pack(anchor="w", padx=8)

        opts = ttk.Frame(root)
        opts.pack(fill="x", padx=8, pady=4)
        self.ai = tk.StringVar(value=self._default("ai", "mode", "smart"))
        self.ocr = tk.StringVar(value=self._default("ocr", "mode", "auto"))
        ttk.Label(opts, text="AI:").pack(side="left")
        ttk.Combobox(opts, textvariable=self.ai, values=list(config.AI_MODES), width=7,
                     state="readonly").pack(side="left", padx=(2, 10))
        ttk.Label(opts, text="OCR:").pack(side="left")
        ttk.Combobox(opts, textvariable=self.ocr, values=["auto", "always", "never"], width=7,
                     state="readonly").pack(side="left", padx=(2, 10))
        self.rtl, self.markers, self.report = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
        for text, var in (("RTL wrap", self.rtl), ("Page markers", self.markers), ("Write report", self.report)):
            ttk.Checkbutton(opts, text=text, variable=var).pack(side="left", padx=4)

        acts = ttk.Frame(root)
        acts.pack(fill="x", padx=8, pady=4)
        self.buttons = [ttk.Button(acts, text="Convert", command=lambda: self.run(plan=False)),
                        ttk.Button(acts, text="Plan (free preview)", command=lambda: self.run(plan=True))]
        for b in self.buttons:
            b.pack(side="left", padx=(0, 4))
        ttk.Button(acts, text="Open output folder", command=self.open_out).pack(side="left")
        ttk.Button(acts, text="Clear log", command=lambda: self._log_set("")).pack(side="right")
        self.status = ttk.Label(acts, text="Ready")
        self.status.pack(side="right", padx=8)

        self.log = ScrolledText(root, height=15, state="disabled", wrap="word", font="TkFixedFont")
        self.log.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        root.after(100, self.drain)

    @staticmethod
    def _default(section: str, key: str, fallback: str) -> str:
        try:
            return getattr(getattr(config.load(None, {}), section), key)
        except Exception:
            return fallback

    def add_files(self):
        pattern = " ".join(f"*{ext}" for ext in sorted(cli.SUPPORTED))
        for f in filedialog.askopenfilenames(filetypes=[("Documents", pattern), ("All files", "*")]):
            self.listbox.insert("end", f)

    def add_folder(self):
        if d := filedialog.askdirectory():
            self.listbox.insert("end", d)

    def remove(self):
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)

    def pick_out(self):
        if d := filedialog.askdirectory():
            self.out.set(d)

    def open_out(self):
        target = self.out.get().strip() or (self.listbox.get(0) if self.listbox.size() else "")
        if not target:
            return
        path = Path(target)
        path = path if path.is_dir() else path.parent
        if path.is_dir():
            _open_folder(path)

    def _log_set(self, text: str):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", text)
        self.log.configure(state="disabled")

    def _log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def run(self, plan: bool):
        if self.busy:
            return
        files = self.listbox.get(0, "end")
        if not files:
            messagebox.showinfo("md-maker", "Add at least one file or folder first.")
            return
        argv = build_argv(files, self.out.get(), self.ai.get(), self.ocr.get(),
                          self.rtl.get(), self.markers.get(), self.report.get(), plan)
        self.busy = True
        for b in self.buttons:
            b.state(["disabled"])
        self.status.configure(text="Planning…" if plan else "Converting…")
        self._log(f"\n$ md-maker {' '.join(argv)}\n")
        threading.Thread(target=self._worker, args=(argv,), daemon=True).start()

    def _worker(self, argv: list[str]):
        # Only one run at a time (buttons disabled), so swapping the global streams is safe.
        old = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = _QueueWriter(self.q)
        try:
            code = cli._main(argv)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        except Exception as e:
            print(f"md-maker: {e}")
            code = 1
        finally:
            sys.stdout, sys.stderr = old
        self.q.put(("done", code))

    def drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple):
                    code = item[1]
                    self._log("Done.\n" if code == 0 else f"Finished with errors (exit code {code}).\n")
                    self.status.configure(text="Done" if code == 0 else "Errors, see log")
                    self.busy = False
                    for b in self.buttons:
                        b.state(["!disabled"])
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.root.after(100, self.drain)


def main() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
