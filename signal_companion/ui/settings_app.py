"""Generic, plugin-driven settings dialog.

Spawned as `app.py --settings` (a separate process so tkinter owns the main
thread cleanly). Discovers plugins, gives each one a tab via its
build_settings_tab(), and on Save calls each plugin's save_settings() then
writes config.json. No per-feature code lives here — adding a plugin adds its
tab automatically.

Uses ttkbootstrap for a modern themed look (with a live theme switcher),
falling back to plain ttk if it isn't installed so the build never hard-fails.
"""
import logging

import tkinter as tk
from tkinter import messagebox, ttk

from signal_companion import __version__
from signal_companion.core import config as config_mod
from signal_companion.core.manager import PluginManager

try:
    import ttkbootstrap as tb
    _HAS_TB = True
except Exception:
    tb = None
    _HAS_TB = False

# A curated subset of ttkbootstrap themes for the picker (all dark+light look
# good; this keeps the dropdown short and tasteful).
_THEME_CHOICES = ["darkly", "cyborg", "superhero", "vapor", "solar", "flatly", "litera", "morph"]

# bootstyle keywords only exist under ttkbootstrap; degrade to {} on plain ttk.
def _style(**kw):
    return kw if _HAS_TB else {}


def run():
    manager = PluginManager()
    manager.discover()              # seeds config + saves; does not start plugins
    cfg = manager.cfg
    cfg.setdefault("app", {})
    theme = cfg["app"].get("theme", "darkly")

    if _HAS_TB:
        # Create the themed window first, THEN consult its Style for the theme
        # list. Calling tb.Style() before any root exists spawns a stray empty
        # "tk" window (it creates a default Tk root).
        root = tb.Window(themename="darkly")
        if theme != "darkly" and theme in root.style.theme_names():
            root.style.theme_use(theme)
    else:
        root = tk.Tk()
    root.title("SignalCompanion — Settings")
    root.geometry("620x760")
    root.minsize(540, 620)

    # ── header ──
    header = ttk.Frame(root, padding=(14, 12, 14, 6))
    header.pack(fill=tk.X)
    ttk.Label(header, text="SignalCompanion", font=("", 16, "bold"),
              **_style(bootstyle="primary")).pack(side=tk.LEFT)
    ttk.Label(header, text=f"v{__version__}", foreground="#888").pack(side=tk.LEFT, padx=(8, 0), pady=(6, 0))

    if _HAS_TB:
        theme_box = ttk.Frame(header)
        theme_box.pack(side=tk.RIGHT)
        ttk.Label(theme_box, text="Theme:").pack(side=tk.LEFT, padx=(0, 6))
        theme_var = tk.StringVar(value=theme)
        theme_names = root.style.theme_names()
        choices = sorted(set(_THEME_CHOICES) & set(theme_names)) or list(theme_names)
        theme_combo = ttk.Combobox(theme_box, textvariable=theme_var, values=choices,
                                   state="readonly", width=12)
        theme_combo.pack(side=tk.LEFT)
        theme_combo.bind("<<ComboboxSelected>>",
                         lambda e: root.style.theme_use(theme_var.get()))
    else:
        theme_var = None

    ttk.Separator(root, orient="horizontal").pack(fill=tk.X, padx=12, pady=(2, 0))

    nb = ttk.Notebook(root)
    nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    # One tab per plugin; collect (plugin, section, vars) for save.
    tabs = []
    for plugin in manager.plugins:
        section = cfg["plugins"].setdefault(plugin.id, plugin.default_config())
        frame = ttk.Frame(nb, padding=14)
        nb.add(frame, text=plugin.name)
        try:
            vars = plugin.build_settings_tab(frame, section)
        except Exception:
            logging.exception(f"[settings] build_settings_tab failed for {plugin.id}")
            ttk.Label(frame, text="(failed to build settings — see log)",
                      foreground="#c33").pack(anchor="w")
            vars = None
        tabs.append((plugin, section, vars))

    ttk.Label(root, text=f"Config: {config_mod.CONFIG_PATH}\nLog:    {config_mod.LOG_PATH}",
              foreground="#888", justify="left").pack(anchor="w", padx=14, pady=(0, 4))

    bottom = ttk.Frame(root, padding=(10, 6, 10, 12))
    bottom.pack(fill=tk.X)

    def save_and_close():
        for plugin, section, vars in tabs:
            if vars is None:
                continue
            try:
                plugin.save_settings(section, vars)
                cfg["plugins"][plugin.id] = section
            except Exception:
                logging.exception(f"[settings] save_settings failed for {plugin.id}")
                messagebox.showerror("Save error",
                                     f"Failed to save '{plugin.name}' settings — see log.")
                return
        if theme_var is not None:
            cfg["app"]["theme"] = theme_var.get()
        config_mod.save_config(cfg)
        messagebox.showinfo("Saved",
                            "Config saved.\n\nDevice-selection and port/transport changes apply "
                            "on the next SignalCompanion start. Enable/disable + interval changes "
                            "apply within a few seconds.")
        root.destroy()

    ttk.Button(bottom, text="Save", command=save_and_close,
               **_style(bootstyle="success")).pack(side=tk.RIGHT, padx=4)
    ttk.Button(bottom, text="Cancel", command=root.destroy,
               **_style(bootstyle="secondary")).pack(side=tk.RIGHT, padx=4)

    root.mainloop()


if __name__ == "__main__":
    run()
