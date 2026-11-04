# RockSteady Fix – (c) 2026 @jiri.fpv.zone – https://www.instagram.com/jiri.fpv.zone/
# SPDX-License-Identifier: GPL-3.0-or-later
"""RockSteady Fix – Windows GUI (FPV / OSD style).  Author: @jiri.fpv.zone"""
import os, sys, json, time, queue, threading, traceback, ctypes, webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox

import av
import customtkinter as ctk
from PIL import Image
from tkinterdnd2 import TkinterDnD, DND_FILES

import engine
from i18n import tr

APP = 'RockSteady Fix'
VERSION = '1.6.1'
AUTHOR_IG = 'jiri.fpv.zone'
IG_URL = f'https://www.instagram.com/{AUTHOR_IG}/'
BASE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
ASSET = lambda n: os.path.join(BASE, 'assets', n)
VIDEO_EXT = ('.mp4', '.mov')
SETTINGS = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'RockSteadyFix', 'settings.json')

# palette – dark goggles UI with neon accents
BG, PANEL, PANEL2 = '#0a0d12', '#11161d', '#171e27'
LIME, LIME_D, CYAN, RED = '#c6ff00', '#a3d400', '#00e5ff', '#ff3c3c'
TXT, MUTED, LINE = '#e6edf3', '#7d8794', '#26303c'
F_HEAD = ('Bahnschrift SemiBold', 26)
F_SUB = ('Bahnschrift SemiBold', 12)
F_UI = ('Bahnschrift', 13)
F_UIB = ('Bahnschrift SemiBold', 14)
F_MONO = ('Consolas', 11)
F_MONOB = ('Consolas', 12, 'bold')

FIELDS = [('thr_px', 'px @960'), ('thr_deg', '°'), ('smooth_s', 's'), ('margin_s', 's'),
          ('fade_s', 's'), ('zoom_ramp_s', 's'), ('max_crop', '%')]


def load_settings():
    try:
        return json.load(open(SETTINGS, encoding='utf8'))
    except Exception:
        return {}


def save_settings(d):
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        json.dump(d, open(SETTINGS, 'w', encoding='utf8'))
    except Exception:
        pass


def default_lang():
    try:
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
        return 'cs' if lid in (0x05, 0x1B) else 'en'      # Czech, Slovak -> CZ
    except Exception:
        return 'en'


def fmt_time(s):
    s = int(max(0, s))
    return f'{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}' if s >= 3600 else f'{s // 60:02d}:{s % 60:02d}'


def probe(path, T):
    try:
        c = av.open(path); v = c.streams.video[0]
        dur = float(c.duration or 0) / 1e6
        info = f'{v.width}×{v.height}  ·  {float(v.average_rate or 0):g} FPS  ·  {fmt_time(dur)}  ·  {os.path.getsize(path) / 1e9:.1f} GB'
        c.close(); return info
    except Exception as e:
        return T('probe_err', e=e)


class DropZone(tk.Canvas):
    """OSD-style drop target with corner brackets."""
    def __init__(self, master, on_click, T):
        super().__init__(master, height=int(170 * ctk.ScalingTracker.get_widget_scaling(master)), bg=PANEL,
                         highlightthickness=0, cursor='hand2')
        self.on_click = on_click; self.T = T; self.hover = False
        self.title, self.meta, self.path = T('drop_title'), T('drop_meta'), ''
        self.bind('<Configure>', lambda e: self.redraw())
        self.bind('<Enter>', lambda e: self._hov(True)); self.bind('<Leave>', lambda e: self._hov(False))
        self.bind('<Button-1>', lambda e: self.on_click())

    def _hov(self, v):
        self.hover = v; self.redraw()

    def set(self, title, meta, path):
        self.title, self.meta, self.path = title, meta, path; self.redraw()

    def redraw(self):
        self.delete('all'); w, h = self.winfo_width(), self.winfo_height()
        k = ctk.ScalingTracker.get_widget_scaling(self.master)          # follow CTk DPI scaling
        F = lambda fam, size, *st: (fam, -int(round(size * k * 1.33)), *st)  # negative = pixels
        col = LIME if (self.hover or self.path) else '#4a5563'
        l, t, m = 22 * k, max(2, int(3 * k)), 6 * k
        for x, y, dx, dy in ((m, m, 1, 1), (w - m - 1, m, -1, 1), (m, h - m - 1, 1, -1), (w - m - 1, h - m - 1, -1, -1)):
            self.create_line(x, y, x + dx * l, y, fill=col, width=t); self.create_line(x, y, x, y + dy * l, fill=col, width=t)
        if not self.path:
            cx, cy = w / 2, h / 2 - 24 * k
            for a, b, c, d in ((-14, 0, -5, 0), (5, 0, 14, 0), (0, -14, 0, -5), (0, 5, 0, 14)):
                self.create_line(cx + a * k, cy + b * k, cx + c * k, cy + d * k, fill=col, width=max(2, int(2 * k)))
            self.create_text(w / 2, h / 2 + 12 * k, text=self.title, fill=TXT, font=F('Bahnschrift SemiBold', 17))
            self.create_text(w / 2, h / 2 + 40 * k, text=self.meta, fill=MUTED, font=F('Bahnschrift', 11))
        else:
            x0 = 36 * k
            self.create_oval(x0, 34 * k, x0 + 10 * k, 44 * k, fill=RED, outline='')
            self.create_text(x0 + 18 * k, 39 * k, text='SOURCE', anchor='w', fill=LIME, font=F('Consolas', 12, 'bold'))
            self.create_text(x0, 76 * k, text=self.title, anchor='w', fill=TXT, font=F('Bahnschrift SemiBold', 18))
            self.create_text(x0, 110 * k, text=self.meta, anchor='w', fill=CYAN, font=F('Consolas', 11))
            self.create_text(x0, 138 * k, text=self.path, anchor='w', fill=MUTED, font=F('Bahnschrift', 10))
            self.create_text(w - x0, 39 * k, text=self.T('change_src'), anchor='e', fill=MUTED, font=F('Consolas', 11))


class App(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, initial=None):
        super().__init__(fg_color=BG)
        self.TkdndVersion = TkinterDnD._require(self)
        self.settings = load_settings()
        self.lang = self.settings.get('lang') or default_lang()
        self.title(f'{APP}  ·  by @{AUTHOR_IG}'); self.geometry('820x600'); self.minsize(720, 420)
        try: self.iconbitmap(default=ASSET('icon.ico')); self.after(250, lambda: self.iconbitmap(ASSET('icon.ico')))
        except Exception: pass
        self.q = queue.Queue(); self.job = None; self.t0 = None; self.result = None; self.result_state = None
        self.src = ''; self.out = tk.StringVar(); self.preview = tk.BooleanVar(value=True)
        self.codec = self.settings.get('codec', 'hevc')
        self.vars = {k: tk.StringVar(value=f'{engine.DEFAULTS[k]:g}') for k, _ in FIELDS}
        self.status = tk.StringVar(); self.eta = tk.StringVar(); self.status_key = 'ready'
        self.log_lines = []; self._adv_open = self._log_open = False
        self.build()
        self.drop_target_register(DND_FILES); self.dnd_bind('<<Drop>>', self.on_drop)
        if initial: self.set_source(initial)
        self.after(50, self.fit)
        self.after(100, self.poll)
        self.protocol('WM_DELETE_WINDOW', self.on_close)

    def T(self, key, **kw):
        return tr(self.lang, key, **kw)

    # ------------------------------------------------------------------ layout
    def build(self):
        T = self.T
        self.root = root = ctk.CTkFrame(self, fg_color=BG); root.pack(fill='both', expand=True, padx=22, pady=(18, 10))
        root.grid_columnconfigure(0, weight=1)

        # header
        head = ctk.CTkFrame(root, fg_color='transparent'); head.grid(row=0, column=0, sticky='ew')
        head.grid_columnconfigure(1, weight=1)
        logo = ctk.CTkImage(Image.open(ASSET('icon.png')), size=(64, 64))
        ctk.CTkLabel(head, image=logo, text='').grid(row=0, column=0, rowspan=2, padx=(0, 14))
        tt = ctk.CTkFrame(head, fg_color='transparent'); tt.grid(row=0, column=1, sticky='w')
        ctk.CTkLabel(tt, text='ROCKSTEADY', font=F_HEAD, text_color=TXT).pack(side='left')
        ctk.CTkLabel(tt, text=' FIX', font=F_HEAD, text_color=LIME).pack(side='left')
        ctk.CTkLabel(head, text='GYROGATE KILLER  ·  DJI O4 PRO', font=F_SUB, text_color=CYAN)\
            .grid(row=1, column=1, sticky='nw')
        sw = ctk.CTkFrame(head, fg_color=PANEL2, corner_radius=8); sw.grid(row=0, column=2, rowspan=2, sticky='e', padx=(0, 10))
        self.lang_btns = {}
        for code, lab in (('cs', 'CZ'), ('en', 'EN')):
            on = code == self.lang
            b = ctk.CTkButton(sw, text=lab, width=42, height=28, corner_radius=6, font=F_MONOB,
                              fg_color=LIME if on else PANEL2, hover_color=LIME_D if on else LINE,
                              text_color='#0a0d12' if on else MUTED, text_color_disabled=MUTED,
                              command=lambda c=code: self.set_lang(c))
            b.pack(side='left', padx=2, pady=2); self.lang_btns[code] = b
        if self.job: self.lock_lang(True)
        ctk.CTkButton(head, text=T('about_btn'), font=F_MONOB, fg_color='transparent', hover_color=PANEL2, text_color=MUTED,
                      corner_radius=18, height=36, width=120, command=self.show_about)\
            .grid(row=0, column=3, rowspan=2, sticky='e', padx=(0, 8))
        ig = ctk.CTkImage(Image.open(ASSET('ig.png')), size=(20, 20))
        ctk.CTkButton(head, image=ig, text=f'@{AUTHOR_IG}', font=F_UIB, fg_color=PANEL2, hover_color=LINE,
                      text_color=TXT, corner_radius=18, height=36, command=lambda: webbrowser.open(IG_URL))\
            .grid(row=0, column=4, rowspan=2, sticky='e')

        # drop zone
        self.drop = DropZone(root, self.pick_src, T); self.drop.grid(row=1, column=0, sticky='ew', pady=(18, 10))

        # output + preview
        of = ctk.CTkFrame(root, fg_color='transparent'); of.grid(row=2, column=0, sticky='ew'); of.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(of, text=T('save_to'), font=F_MONOB, text_color=MUTED).grid(row=0, column=0, padx=(2, 10))
        ctk.CTkEntry(of, textvariable=self.out, font=F_UI, fg_color=PANEL, border_color=LINE, height=34)\
            .grid(row=0, column=1, sticky='ew')
        ctk.CTkButton(of, text=T('change'), width=90, height=34, font=F_UIB, fg_color=PANEL2, hover_color=LINE,
                      text_color=TXT, command=self.pick_out).grid(row=0, column=2, padx=(8, 0))
        ff = ctk.CTkFrame(root, fg_color='transparent'); ff.grid(row=3, column=0, sticky='ew', pady=(8, 0))
        ctk.CTkLabel(ff, text=T('fmt_label'), font=F_MONOB, text_color=MUTED).pack(side='left', padx=(2, 10))
        self.fmt_names = {'hevc': T('fmt_hevc'), 'prores': T('fmt_prores')}
        self.fmt_menu = ctk.CTkOptionMenu(ff, values=list(self.fmt_names.values()), command=self.set_codec, font=F_UI,
                                          dropdown_font=F_UI, fg_color=PANEL2, button_color=PANEL2, button_hover_color=LINE,
                                          text_color=TXT, dropdown_fg_color=PANEL2, dropdown_hover_color=LINE, width=380, height=32)
        self.fmt_menu.set(self.fmt_names[self.codec]); self.fmt_menu.pack(side='left')
        opts = ctk.CTkFrame(root, fg_color='transparent'); opts.grid(row=4, column=0, sticky='ew', pady=(10, 0))
        ctk.CTkSwitch(opts, text=T('preview_sw'), variable=self.preview, font=F_UI,
                      progress_color=LIME, button_color=TXT, text_color=TXT).pack(side='left')
        self.adv_btn = ctk.CTkButton(opts, text='', width=150, height=30, font=F_MONOB, fg_color='transparent',
                                     hover_color=PANEL2, text_color=MUTED, command=self.toggle_adv)
        self.adv_btn.pack(side='right')

        self.adv = ctk.CTkFrame(root, fg_color=PANEL, corner_radius=10)
        for r, (k, unit) in enumerate(FIELDS):
            ctk.CTkLabel(self.adv, text=T('f_' + k), font=F_UI, text_color=TXT).grid(row=r, column=0, sticky='w', padx=(16, 8), pady=3)
            ctk.CTkEntry(self.adv, textvariable=self.vars[k], width=70, height=28, font=F_MONO, fg_color=BG, border_color=LINE,
                         justify='right').grid(row=r, column=1, pady=3)
            ctk.CTkLabel(self.adv, text=unit, font=F_MONO, text_color=MUTED).grid(row=r, column=2, sticky='w', padx=8)
        ctk.CTkButton(self.adv, text=T('defaults'), width=100, font=F_MONOB, fg_color=PANEL2, hover_color=LINE, text_color=TXT,
                      command=self.reset).grid(row=0, column=3, padx=20, pady=(10, 0), sticky='n')
        ctk.CTkLabel(self.adv, text=T('adv_hint'), font=('Bahnschrift', 11), text_color=MUTED, justify='left')\
            .grid(row=1, column=3, rowspan=3, padx=20, sticky='nw')

        # start / cancel
        self.btn_start = ctk.CTkButton(root, text=T('start'), height=52, corner_radius=12, font=('Bahnschrift SemiBold', 18),
                                       fg_color=LIME, hover_color=LIME_D, text_color='#0a0d12', command=self.start)
        self.btn_cancel = ctk.CTkButton(root, text=T('cancel'), height=52, corner_radius=12, font=('Bahnschrift SemiBold', 18),
                                        fg_color=PANEL2, hover_color=LINE, text_color=RED, border_width=2, border_color=RED,
                                        command=self.cancel)
        (self.btn_cancel if self.job else self.btn_start).grid(row=6, column=0, sticky='ew', pady=(16, 8))

        # progress HUD
        hud = ctk.CTkFrame(root, fg_color='transparent'); hud.grid(row=7, column=0, sticky='ew'); hud.grid_columnconfigure(0, weight=1)
        self.pb = ctk.CTkProgressBar(hud, height=8, progress_color=LIME, fg_color=PANEL2, corner_radius=4)
        self.pb.set(getattr(self, '_pb_val', 0)); self.pb.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(2, 6))
        ctk.CTkLabel(hud, textvariable=self.status, font=F_MONOB, text_color=LIME).grid(row=1, column=0, sticky='w')
        ctk.CTkLabel(hud, textvariable=self.eta, font=F_MONO, text_color=MUTED).grid(row=1, column=1, sticky='e')

        # result card
        self.res = ctk.CTkFrame(root, fg_color=PANEL, corner_radius=12, border_width=1, border_color=LINE)
        self.res.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform='tile')
        self.tiles = {}
        for c, k in enumerate(('snaps', 'zones', 'crop', 'time')):
            f = ctk.CTkFrame(self.res, fg_color=PANEL2, corner_radius=8); f.grid(row=0, column=c, sticky='ew', padx=6, pady=(12, 6))
            v = ctk.CTkLabel(f, text='–', font=('Bahnschrift SemiBold', 26), text_color=LIME); v.pack(pady=(8, 0))
            ctk.CTkLabel(f, text=T('t_' + k), font=F_MONO, text_color=MUTED).pack(pady=(0, 8)); self.tiles[k] = v
        self.res_text = ctk.CTkLabel(self.res, text='', font=('Bahnschrift', 12), text_color=TXT, justify='left', wraplength=700)
        self.res_text.grid(row=1, column=0, columnspan=4, sticky='w', padx=14, pady=(4, 4))
        rb = ctk.CTkFrame(self.res, fg_color='transparent'); rb.grid(row=2, column=0, columnspan=4, sticky='w', padx=10, pady=(4, 12))
        self.btn_play = ctk.CTkButton(rb, text=T('play'), font=F_UIB, fg_color=LIME, hover_color=LIME_D,
                                      text_color='#0a0d12', height=36, command=self.play_preview)
        self.btn_play.pack(side='left', padx=4)
        for key, cmd in (('open_dir', self.open_out), ('new_job', self.new_job)):
            ctk.CTkButton(rb, text=T(key), font=F_UIB, fg_color=PANEL2, hover_color=LINE, text_color=TXT, height=36, command=cmd)\
                .pack(side='left', padx=4)

        # log
        root.grid_rowconfigure(10, weight=1)
        self.log_btn = ctk.CTkButton(root, text='', width=80, height=26, font=F_MONOB, fg_color='transparent',
                                     hover_color=PANEL2, text_color=MUTED, anchor='w', command=self.toggle_log)
        self.log_btn.grid(row=9, column=0, sticky='w', pady=(10, 0))
        self.log = ctk.CTkTextbox(root, height=120, font=('Consolas', 10), fg_color=PANEL, text_color='#b7c3d0', wrap='word')
        self.log.insert('end', ''.join(l + '\n' for l in self.log_lines)); self.log.see('end')
        self.log.configure(state='disabled')

        # footer – author
        self.foot = foot = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, height=34); foot.pack(fill='x', side='bottom', before=root)
        ctk.CTkLabel(foot, text=f'v{VERSION}', font=F_MONO, text_color=MUTED).pack(side='left', padx=(14, 10))
        about = ctk.CTkLabel(foot, text=T('about_btn'), font=F_MONO, text_color=MUTED, cursor='hand2')
        about.pack(side='left'); about.bind('<Button-1>', lambda e: self.show_about())
        link = ctk.CTkLabel(foot, text=f'@{AUTHOR_IG}', font=('Bahnschrift SemiBold', 12), text_color=CYAN, cursor='hand2')
        link.pack(side='right', padx=(0, 14)); link.bind('<Button-1>', lambda e: webbrowser.open(IG_URL))
        ig_s = ctk.CTkImage(Image.open(ASSET('ig.png')), size=(16, 16))
        igl = ctk.CTkLabel(foot, image=ig_s, text='', cursor='hand2'); igl.pack(side='right', padx=(0, 6))
        igl.bind('<Button-1>', lambda e: webbrowser.open(IG_URL))
        ctk.CTkLabel(foot, text=T('author'), font=('Bahnschrift', 12), text_color=MUTED).pack(side='right', padx=(0, 8))

        # restore view state (after a language switch)
        self._show_adv(self._adv_open); self._show_log(self._log_open)
        if self.src:
            self.drop.set(os.path.basename(self.src), probe(self.src, T), os.path.dirname(self.src))
        self.refresh_status()
        if self.result_state: self.render_result(*self.result_state)

    def lock_lang(self, locked):
        for b in self.lang_btns.values(): b.configure(state='disabled' if locked else 'normal')

    def set_lang(self, lang):
        if lang == self.lang or self.job:
            return
        self.lang = lang; self.settings['lang'] = lang; save_settings(self.settings)
        self._pb_val = self.pb.get()
        self.root.destroy(); self.foot.destroy()
        if getattr(self, '_about', None) and self._about.winfo_exists():
            self._about.destroy()
        self.build(); self.fit()

    def set_codec(self, label):
        self.codec = next(k for k, v in self.fmt_names.items() if v == label)
        self.settings['codec'] = self.codec; save_settings(self.settings)

    def refresh_status(self):
        k = self.status_key
        if k in ('ready', 'ready_src', 'arming', 'disarming', 'done', 'done_none', 'cancelled'):
            self.status.set(self.T(k))

    # ------------------------------------------------------------------ about
    def show_about(self):
        T = self.T
        if getattr(self, '_about', None) and self._about.winfo_exists():
            self._about.focus(); return
        d = ctk.CTkToplevel(self, fg_color=BG); self._about = d
        d.title(T('about_title', app=APP)); d.resizable(False, False); d.transient(self)
        d.after(250, lambda: d.iconbitmap(ASSET('icon.ico')))
        f = ctk.CTkFrame(d, fg_color=BG); f.pack(fill='both', expand=True, padx=24, pady=20)
        top = ctk.CTkFrame(f, fg_color='transparent'); top.pack(fill='x')
        ctk.CTkLabel(top, image=ctk.CTkImage(Image.open(ASSET('icon.png')), size=(52, 52)), text='').pack(side='left', padx=(0, 12))
        tt = ctk.CTkFrame(top, fg_color='transparent'); tt.pack(side='left')
        r = ctk.CTkFrame(tt, fg_color='transparent'); r.pack(anchor='w')
        ctk.CTkLabel(r, text='ROCKSTEADY', font=('Bahnschrift SemiBold', 20), text_color=TXT).pack(side='left')
        ctk.CTkLabel(r, text=' FIX', font=('Bahnschrift SemiBold', 20), text_color=LIME).pack(side='left')
        ctk.CTkLabel(tt, text=T('about_ver', v=VERSION), font=F_MONO, text_color=CYAN).pack(anchor='w')
        ctk.CTkLabel(f, text=T('about_intro'), font=F_UI, text_color=TXT, justify='left', wraplength=520)\
            .pack(anchor='w', pady=(16, 8))
        for head, body in T('about_items'):
            box = ctk.CTkFrame(f, fg_color=PANEL, corner_radius=8); box.pack(fill='x', pady=4)
            ctk.CTkLabel(box, text='▌' + head, font=F_MONOB, text_color=LIME).pack(anchor='w', padx=12, pady=(8, 0))
            ctk.CTkLabel(box, text=body, font=('Bahnschrift', 12), text_color=TXT, justify='left', wraplength=500)\
                .pack(anchor='w', padx=12, pady=(2, 8))
        ctk.CTkLabel(f, text=T('about_legal'), font=('Bahnschrift', 11), text_color=MUTED, justify='left', wraplength=520)\
            .pack(anchor='w', pady=(10, 0))
        au = ctk.CTkFrame(f, fg_color='transparent'); au.pack(fill='x', pady=(14, 0))
        ctk.CTkLabel(au, text=T('author'), font=F_UI, text_color=MUTED).pack(side='left')
        ctk.CTkButton(au, image=ctk.CTkImage(Image.open(ASSET('ig.png')), size=(18, 18)), text=f'@{AUTHOR_IG}', font=F_UIB,
                      fg_color=PANEL2, hover_color=LINE, text_color=CYAN, corner_radius=16, height=34,
                      command=lambda: webbrowser.open(IG_URL)).pack(side='left', padx=10)
        ctk.CTkButton(au, text=T('close'), font=F_UIB, fg_color=LIME, hover_color=LIME_D, text_color='#0a0d12', width=100, height=34,
                      command=d.destroy).pack(side='right')
        d.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - d.winfo_width()) // 2; y = self.winfo_rooty() + 40
        d.geometry(f'+{max(0, x)}+{max(0, y)}'); d.after(10, d.lift); d.after(20, d.focus_force); d.grab_set()

    # ---------------------------------------------------------------- helpers
    def fit(self):
        """size the window to its content (CTk geometry() works in unscaled units)"""
        self.update_idletasks()
        sc = ctk.ScalingTracker.get_window_scaling(self)
        need = min(self.winfo_reqheight(), self.winfo_screenheight() - 80)
        self.geometry(f'{int(self.winfo_width() / sc)}x{int(need / sc)}')

    def _show_adv(self, on):
        (self.adv.grid(row=5, column=0, sticky='ew', pady=(8, 0), ipady=6) if on else self.adv.grid_remove())
        self.adv_btn.configure(text=self.T('advanced') + '  ' + ('▾' if on else '▸'))

    def _show_log(self, on):
        (self.log.grid(row=10, column=0, sticky='nsew', pady=(4, 6)) if on else self.log.grid_remove())
        self.log_btn.configure(text='LOG  ' + ('▾' if on else '▸'))

    def toggle_adv(self):
        self._adv_open = not self._adv_open; self._show_adv(self._adv_open); self.fit()

    def toggle_log(self, force=None):
        self._log_open = (not self._log_open) if force is None else force
        self._show_log(self._log_open); self.fit()

    def set_status(self, key):
        self.status_key = key; self.status.set(self.T(key))

    def set_source(self, path):
        path = os.path.normpath(path)
        if not path.lower().endswith(VIDEO_EXT) or not os.path.isfile(path):
            messagebox.showwarning(APP, self.T('err_not_video')); return
        self.src = path
        self.drop.set(os.path.basename(path), probe(path, self.T), os.path.dirname(path))
        self.out.set(os.path.join(os.path.dirname(path), '_stabilized'))
        self.res.grid_remove(); self.result_state = None; self.pb.set(0); self.set_status('ready_src'); self.eta.set('')

    def on_drop(self, e):
        files = [f for f in self.tk.splitlist(e.data) if f.lower().endswith(VIDEO_EXT)]
        if files and not self.job: self.set_source(files[0])

    def pick_src(self):
        if self.job: return
        f = filedialog.askopenfilename(title=self.T('dlg_pick_src'),
                                       filetypes=[('Video', '*.mp4 *.MP4 *.mov *.MOV'), (self.T('dlg_all'), '*.*')])
        if f: self.set_source(f)

    def pick_out(self):
        d = filedialog.askdirectory(title=self.T('dlg_pick_out'))
        if d: self.out.set(os.path.normpath(d))

    def reset(self):
        for k, v in self.vars.items(): v.set(f'{engine.DEFAULTS[k]:g}')

    def write(self, msg):
        self.log_lines.append(msg)
        self.log.configure(state='normal'); self.log.insert('end', msg + '\n'); self.log.see('end'); self.log.configure(state='disabled')

    # -------------------------------------------------------------------- run
    def start(self):
        src, out = self.src, self.out.get().strip()
        if not os.path.isfile(src):
            self.pick_src(); return
        try:
            params = {k: float(v.get().replace(',', '.')) for k, v in self.vars.items()}
        except ValueError:
            messagebox.showerror(APP, self.T('err_bad_num')); return
        params['preview'] = self.preview.get(); params['codec'] = self.codec
        target = engine.output_path(src, out, self.codec)
        if os.path.exists(target) and not messagebox.askyesno(APP, self.T('ask_overwrite', p=target)):
            return
        self.log_lines = []
        self.log.configure(state='normal'); self.log.delete('1.0', 'end'); self.log.configure(state='disabled')
        self.res.grid_remove(); self.result = None; self.result_state = None
        self.job = engine.Job(src, out, params, log=lambda m: self.q.put(('log', m)),
                              progress=lambda p, m='': self.q.put(('prog', p, m)), lang=self.lang)
        self.btn_start.grid_remove(); self.btn_cancel.grid(row=6, column=0, sticky='ew', pady=(16, 8))
        self.lock_lang(True)
        self.t0 = time.time(); self.set_status('arming')
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        try:
            res = self.job.run(); self.q.put(('done', res, self.job))
        except Exception as e:
            self.q.put(('log', 'ERROR: ' + ''.join(traceback.format_exception_only(type(e), e)).strip()))
            self.q.put(('log', traceback.format_exc())); self.q.put(('error', str(e)))

    def cancel(self):
        if self.job: self.job.cancel.set(); self.set_status('disarming')

    def poll(self):
        try:
            while True:
                it = self.q.get_nowait()
                if it[0] == 'log':
                    self.write(it[1])
                elif it[0] == 'prog':
                    p = it[1]; self.pb.set(p)
                    if it[2]:
                        self.status_key = 'progress'; self.status.set(f'{it[2].upper()}  ·  {p * 100:4.1f} %')
                    el = time.time() - self.t0
                    if 0.03 < p < 1: self.eta.set(self.T('elapsed', a=fmt_time(el), b=fmt_time(el / p - el)))
                elif it[0] == 'done':
                    self.finish(it[1], it[2])
                elif it[0] == 'error':
                    self.finish(None, None); self.toggle_log(True)
                    messagebox.showerror(APP, self.T('err_run', e=it[1]))
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def finish(self, out, job):
        self.btn_cancel.grid_remove(); self.btn_start.grid(row=6, column=0, sticky='ew', pady=(16, 8))
        self.lock_lang(False)
        el = time.time() - self.t0 if self.t0 else 0; self.job = None; self.eta.set(self.T('total', a=fmt_time(el)))
        if out and job:
            self.result = job; self.result_state = (out, job, el)
            self.render_result(out, job, el); self.pb.set(1); self.bell()
        elif job is not None and not job.cancel.is_set():
            self.result_state = (None, job, el); self.render_result(None, job, el)
        else:
            self.set_status('cancelled'); self.pb.set(0)

    def render_result(self, out, job, el):
        T = self.T
        if out:
            self.tiles['snaps'].configure(text=f'{len(job.events)}'); self.tiles['zones'].configure(text=f'{len(job.zones)}')
            self.tiles['crop'].configure(text=f'{(job.zoom.max() - 1) * 100:.1f} %'); self.tiles['time'].configure(text=fmt_time(el))
            z = ', '.join(f'{a / job.fps:.1f}–{b / job.fps:.1f} s' for a, b in job.zones[:8]) + ('…' if len(job.zones) > 8 else '')
            self.res_text.configure(text=T('res_zones', z=z) + f'\n{os.path.basename(out)}  ·  {getattr(job, "codec_label", "")}')
            self.btn_play.configure(state='normal' if job.prev_path else 'disabled')
            self.set_status('done')
        else:
            for k in self.tiles: self.tiles[k].configure(text='0' if k in ('snaps', 'zones') else '–')
            self.res_text.configure(text=T('res_none')); self.btn_play.configure(state='disabled')
            self.set_status('done_none')
        self.eta.set(T('total', a=fmt_time(el)))
        self.res.grid(row=8, column=0, sticky='ew', pady=(12, 0)); self.fit()

    def play_preview(self):
        if self.result and self.result.prev_path and os.path.exists(self.result.prev_path):
            os.startfile(self.result.prev_path)

    def open_out(self):
        if self.result and os.path.exists(self.result.out_path):
            os.system(f'explorer /select,"{self.result.out_path}"')
        elif os.path.isdir(self.out.get()):
            os.startfile(self.out.get())

    def new_job(self):
        self.res.grid_remove(); self.result_state = None; self.src = ''; self.pb.set(0); self.set_status('ready'); self.eta.set('')
        self.drop.set(self.T('drop_title'), self.T('drop_meta'), '')

    def on_close(self):
        if self.job and not messagebox.askyesno(APP, self.T('ask_quit')):
            return
        if self.job: self.job.cancel.set()
        self.destroy()


def cli(src, out):
    """RockSteadyFix.exe <video> <output folder> – runs without the window, log goes to the output folder."""
    os.makedirs(out, exist_ok=True)
    lang = load_settings().get('lang') or default_lang()
    with open(os.path.join(out, 'RockSteadyFix_log.txt'), 'w', encoding='utf8') as lf:
        def log(m): lf.write(m + '\n'); lf.flush()
        try: engine.Job(src, out, log=log, lang=lang).run()
        except Exception: log(traceback.format_exc())


def main():
    try: ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('jirifpvzone.RockSteadyFix')
    except Exception: pass
    if len(sys.argv) == 3:
        cli(sys.argv[1], sys.argv[2]); return
    ctk.set_appearance_mode('dark')
    app = App(sys.argv[1] if len(sys.argv) == 2 else None)  # video dropped on the .exe icon
    try:
        import pyi_splash; pyi_splash.close()
    except Exception:
        pass
    app.mainloop()


if __name__ == '__main__':
    main()
