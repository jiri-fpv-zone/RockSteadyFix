# RockSteady Fix – (c) 2026 @jiri.fpv.zone – https://www.instagram.com/jiri.fpv.zone/
# SPDX-License-Identifier: GPL-3.0-or-later
"""RockSteady Fix – engine.

Removes RockSteady "gyrogate" snaps from DJI O4 Pro footage that was recorded
with RockSteady ON (no usable gyro data in the file):

1. dense optical flow (DIS) of every frame pair on a grid (analysis copy, 480 px wide)
2. snap detection from the temporal change of the flow field: parallax from flying
   low changes smoothly over time, a RockSteady snap moves the whole image at once,
   so the per-point residual against a short temporal median isolates the snaps
   (fitted as a 3D camera rotation, which also catches pure roll snaps)
3. inside zones around the snaps only the high-frequency part of the camera rotation
   is removed (rotation fitted to flow minus its temporal gaussian, i.e. parallax-free),
   faded in/out at the zone edges; frames outside zones are untouched
4. rolling-shutter split snaps (part of the rows jump one frame earlier) are removed by a
   second, row-wise correction: the per-row high-frequency residual left after the global
   rotation is smoothed the same way and applied as a row-dependent shift (remap)
5. crop zoom is 1.0 outside zones and eases smoothly to what each zone needs
6. render: untouched frames are passed through, corrected frames are warped
   (10-bit); output H.265 10-bit like the source (GPU encoder) or ProRes 422 HQ;
   optional side-by-side preview
"""
import os, json, threading
from collections import deque
from fractions import Fraction
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import cv2
import av

from i18n import tr

cv2.setNumThreads(1)
AW = 960  # reference width for thresholds / focal length
AN_W = 480  # dense-flow analysis width
GRID = 12  # flow sampling grid step [px at AN_W]
ROW_MAX = 4.0  # max row-wise snap residual per frame [px at AN_W]
MAX_RUN = 10  # this many consecutive snap frames = real impact / landing, left alone (RS bursts are <= 8)
CHOICE_MARGIN = 0.15  # a more complex variant must lower the predicted judder by this much
SMOOTH_FACTORS = (1.0, 1.6)  # path-smoothing strengths tried per zone (x smooth_s)
ROW_AGREE = 0.65  # share of columns that must move with the row median
RUN_GAP = 6  # runs closer than this [frames] belong to the same event group
ROW_NOISE = 1.5  # row residual below this [px @960] is treated as noise
F_DEFAULT = 341.0  # focal length [px @960] measured on O4 Pro 4:3 Linear (HFOV ~109 deg)
P_AN, P_REN = 0.25, 0.27  # progress bar: analysis 0-25 %, plan, render 27-100 % (measured ~27 % / 73 % of the time)


class Cancelled(Exception):
    pass


DEFAULTS = dict(
    thr_px=3.0,       # snap threshold, pan jump [px at 960 px width]
    thr_deg=0.15,     # snap threshold, roll jump [deg]
    smooth_s=0.16,    # gaussian sigma of path smoothing inside zones [s]
    margin_s=0.6,     # zone extends this much before first / after last snap [s]
    fade_s=0.3,       # correction fade in/out at zone edges [s]
    zoom_ramp_s=0.8,  # crop zoom ease in/out [s]
    max_crop=10.0,    # crop limit [%]; zones needing more get a proportionally weaker correction
    preview=True,     # write side-by-side preview mp4
    codec='hevc',     # 'hevc' = H.265 10-bit like the source, 'prores' = ProRes 422 HQ
)


# ---------------------------------------------------------------- 1-D helpers
def _pad(x, r):
    return np.concatenate([np.full(r, x[0]), x, np.full(r, x[-1])])


def gauss1d(x, sigma):
    if sigma <= 0:
        return x.copy()
    r = int(4 * sigma + 0.5)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2); k /= k.sum()
    return np.convolve(_pad(x, r), k, mode='valid')


def maxfilt(x, size):
    r = size // 2
    return np.lib.stride_tricks.sliding_window_view(_pad(x, r), 2 * r + 1).max(1)


def medfilt(x, size=7):
    r = size // 2
    return np.median(np.lib.stride_tricks.sliding_window_view(_pad(x, r), 2 * r + 1), axis=1)


# ---------------------------------------------------------- motion estimation
_tls = threading.local()


def dense_flow(a, b):
    """DIS optical flow a -> b (one DIS object per worker thread)"""
    dis = getattr(_tls, 'dis', None)
    if dis is None:
        dis = _tls.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    return dis.calc(a, b, None)


def grid_points(w, h, step=GRID, margin=2 * GRID):
    return np.mgrid[margin:h - margin + 1:step, margin:w - margin + 1:step]


def temporal(fn, G, *args):
    """apply a 1-D temporal filter to every series of G (n, P, 2)"""
    flat = G.reshape(G.shape[0], -1)
    out = np.empty_like(flat)
    for j in range(flat.shape[1]):
        out[:, j] = fn(flat[:, j], *args)
    return out.reshape(G.shape)


def rays(p, f, cx, cy):
    r = np.column_stack([(p[:, 0] - cx) / f, (p[:, 1] - cy) / f, np.ones(len(p))])
    return r / np.linalg.norm(r, axis=1, keepdims=True)


def kabsch(u, v, w):
    Hm = (u * w[:, None]).T @ v
    U, S, Vt = np.linalg.svd(Hm)
    D = np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))])
    return Vt.T @ D @ U.T


def fit_rot(p, q, f, cx, cy, iters=3, thr=0.5):
    p = p.astype(np.float64); q = q.astype(np.float64)
    u, v = rays(p, f, cx, cy), rays(q, f, cx, cy); w = np.ones(len(u)); e = np.zeros(len(u))
    R = np.eye(3)
    for _ in range(iters):
        R = kabsch(u, v, w)
        r = u @ R.T
        pr = np.column_stack([r[:, 0] / r[:, 2] * f + cx, r[:, 1] / r[:, 2] * f + cy])
        e = np.linalg.norm(pr - q, axis=1)
        w = (e < max(thr, np.median(e) * 2.5)).astype(float)
        if w.sum() < 20:
            break
    err = np.median(e[w > 0]) if w.sum() else np.inf
    return R, err


def rodr(v):
    return cv2.Rodrigues(np.asarray(v, float).reshape(3, 1))[0]


def rotvec(R):
    return cv2.Rodrigues(R)[0].ravel()


# ------------------------------------------------------------------- planning
def detect_snaps(snap, fast, f960, thr_px, thr_deg, row_mag=None, raw_row_mag=None, fast_px=40.0):
    """snap: (n-1, 3) rotation vectors of the flow residual; fast: median flow magnitude [px @960];
    row_mag: largest row-wise residual left after the global snap rotation [px @960] (rolling-shutter split snaps)"""
    shift = f960 * np.hypot(snap[:, 0], snap[:, 1]); roll = np.degrees(np.abs(snap[:, 2]))
    raw = shift if raw_row_mag is None else np.maximum(shift, raw_row_mag)   # every suspicious frame (impact finding)
    if row_mag is not None:
        shift = np.maximum(shift, row_mag)
    hit = ((shift > thr_px) | (roll > thr_deg)) & (fast < fast_px)
    sus = ((raw > thr_px) | (roll > thr_deg)) & (fast < fast_px)
    n = len(snap); ev = []
    hit[:3] = False; hit[n - 4:] = False                               # clip edges
    sus[:3] = False; sus[n - 4:] = False
    runs, i = [], 0
    while i < n:                                                       # runs of consecutive suspicious frames
        if not sus[i]:
            i += 1; continue
        j = i
        while j + 1 < n and sus[j + 1]:
            j += 1
        runs.append([i, j]); i = j + 1
    groups = []                                                        # runs separated by short gaps
    for r in runs:
        if groups and r[0] - groups[-1][-1][1] <= RUN_GAP:
            groups[-1].append(r)
        else:
            groups.append([r])
    for g in groups:
        if max(b - a + 1 for a, b in g) >= MAX_RUN:                    # contains a long run = real impact / landing
            continue
        ev += [dict(frame=int(k), jump_px=float(shift[k]), roll_deg=float(roll[k])) for a, b in g for k in range(a, b + 1) if hit[k]]
    return ev


def make_zones(events, n, margin, fade):
    idx = sorted(e['frame'] for e in events); z = []
    for i in idx:
        if z and i - z[-1][1] <= 2 * margin:
            z[-1][1] = i
        else:
            z.append([i, i])
    zones = [(max(0, a - margin), min(n - 1, b + margin)) for a, b in z]
    w = np.zeros(n)
    for a, b in zones:
        for j in range(a, b + 1):
            e = min(j - a, b - j)
            w[j] = max(w[j], 1.0 if e >= fade else 0.5 - 0.5 * np.cos(np.pi * e / fade))
    return zones, w


def homography(delta, f, w, h, zoom):
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
    Z = np.array([[zoom, 0, w / 2 * (1 - zoom)], [0, zoom, h / 2 * (1 - zoom)], [0, 0, 1]])
    return Z @ K @ rodr(delta) @ np.linalg.inv(K)


def frame_need(Hm, w, h):
    """smallest crop zoom so that no border is exposed"""
    if np.allclose(Hm, np.eye(3)):
        return 1.0
    Hi = np.linalg.inv(Hm); corners = np.array([[0, 0], [w, 0], [0, h], [w, h]], float)
    def ok(z):
        c = (corners - [w / 2, h / 2]) / z + [w / 2, h / 2]
        s = cv2.perspectiveTransform(c[None], Hi)[0]
        return (s[:, 0] >= 0).all() and (s[:, 0] <= w).all() and (s[:, 1] >= 0).all() and (s[:, 1] <= h).all()
    lo, hi = 1.0, 1.5
    if ok(lo):
        return 1.0
    for _ in range(25):
        mid = (lo + hi) / 2
        if ok(mid): hi = mid
        else: lo = mid
    return hi


def row_shift_maps(Hm, rows_y, drow, w, h, an_scale, step=8):
    """inverse maps for: out = Hm(src + D(src_y)), D = per-row shift (analysis px) interpolated over rows.
    Returns float32 (mx, my) for luma and (mxc, myc) for half-resolution chroma."""
    gh, gw = -(-h // step), -(-w // step)
    v, u = np.mgrid[0:gh, 0:gw].astype(np.float64)
    pts = np.stack([((u + 0.5) * step - 0.5).ravel(), ((v + 0.5) * step - 0.5).ravel()], 1)
    m = cv2.perspectiveTransform(pts[None], np.linalg.inv(Hm))[0]
    ya = m[:, 1] / an_scale
    sx = (m[:, 0] - np.interp(ya, rows_y, drow[:, 0]) * an_scale).reshape(gh, gw).astype(np.float32)
    sy = (m[:, 1] - np.interp(ya, rows_y, drow[:, 1]) * an_scale).reshape(gh, gw).astype(np.float32)
    mx = cv2.resize(sx, (w, h), interpolation=cv2.INTER_LINEAR); my = cv2.resize(sy, (w, h), interpolation=cv2.INTER_LINEAR)
    mxc = cv2.resize((sx + 0.5) / 2 - 0.5, (w // 2, h // 2), interpolation=cv2.INTER_LINEAR)
    myc = cv2.resize((sy + 0.5) / 2 - 0.5, (w // 2, h // 2), interpolation=cv2.INTER_LINEAR)
    return mx, my, mxc, myc


# H.265 10-bit encoders in order of preference (GPU first); options tuned for "visually lossless"
HEVC_ENCODERS = [
    ('hevc_nvenc', 'p010le', {'preset': 'p7', 'tune': 'hq', 'rc': 'vbr', 'profile': 'main10', 'multipass': 'fullres',
                              'spatial-aq': '1', 'temporal-aq': '1', 'bf': '3'}),
    ('hevc_amf', 'p010le', {'usage': 'transcoding', 'quality': 'quality', 'rc': 'vbr_peak', 'profile': 'main10'}),
    ('hevc_qsv', 'p010le', {'preset': 'slower', 'profile': 'main10'}),
    ('libx265', 'yuv420p10le', {'preset': 'medium', 'x265-params': 'log-level=error'}),
]
HEVC_LABEL = {'hevc_nvenc': 'H.265 10-bit (NVIDIA)', 'hevc_amf': 'H.265 10-bit (AMD)', 'hevc_qsv': 'H.265 10-bit (Intel)',
              'libx265': 'H.265 10-bit (CPU)'}


def output_path(src, out_dir, codec):
    base = os.path.splitext(os.path.basename(src))[0]
    return os.path.join(out_dir, base + ('_fix.mp4' if codec == 'hevc' else '_fix.mov'))


def pick_hevc_encoder(w, h, rate, bit_rate):
    """first H.265 10-bit encoder that actually opens on this machine"""
    for name, pix, opts in HEVC_ENCODERS:
        if name not in av.codecs_available:
            continue
        try:
            cc = av.CodecContext.create(name, 'w')
            cc.width, cc.height, cc.pix_fmt = w, h, pix
            cc.time_base = 1 / Fraction(rate); cc.framerate = Fraction(rate); cc.bit_rate = int(bit_rate)
            cc.options = dict(opts)
            cc.open()
            del cc                                              # released by garbage collection
            return name, pix, opts
        except Exception:
            continue
    return None


def copy_color_tags(src, dst):
    """carry colour metadata (matrix, primaries, transfer, range) from the source frame;
    ProRes stores them per frame, so frames without them decode with a different matrix"""
    for a in ('colorspace', 'color_primaries', 'color_trc', 'color_range'):
        try:
            setattr(dst, a, getattr(src, a))
        except Exception:
            pass


def zoom_curve(need, active, ramp):
    need = need * np.where(active, 1.003, 1.0)
    if need.max() <= 1.0:
        return np.ones_like(need)
    z = gauss1d(maxfilt(need, 2 * ramp + 1), ramp / 3)
    for _ in range(20):
        z = np.maximum(z, need)
        z = gauss1d(np.maximum(z, maxfilt(need, ramp | 1)), ramp / 6)
    z = np.maximum(z, need)
    z[z < 1.0005] = 1.0
    return z


# --------------------------------------------------------------------- engine
class Job:
    def __init__(self, src, out_dir, params=None, log=print, progress=lambda p, msg='': None, lang='cs'):
        self.src, self.out_dir = src, out_dir
        self.T = lambda key, **kw: tr(lang, key, **kw)
        self.p = dict(DEFAULTS, **(params or {}))
        self.log, self.progress = log, progress
        self.cancel = threading.Event()

    def _chk(self):
        if self.cancel.is_set():
            raise Cancelled()

    # -- pass 1: analysis ------------------------------------------------------
    def analyse(self):
        c = av.open(self.src); vs = c.streams.video[0]; vs.thread_type = 'AUTO'
        self.w, self.h = vs.width, vs.height
        self.fps = float(vs.average_rate or vs.guessed_rate or 50)
        n_est = vs.frames or int(float(c.duration or 0) / 1e6 * self.fps) or 1
        self.ah = int(round(AN_W * self.h / self.w / 2) * 2)
        self.log(self.T('e_source', w=self.w, h=self.h, fps=self.fps, n=n_est, codec=vs.codec_context.name, fmt=vs.format.name))
        gy, gx = grid_points(AN_W, self.ah)
        flows, fast = {}, {}
        pool = ThreadPoolExecutor(max(2, (os.cpu_count() or 4) - 2))
        futs = []
        def pair(i, a, b):
            fl = cv2.blur(dense_flow(a, b), (7, 7))
            flows[i] = fl[gy, gx].astype(np.float32)                       # (gh, gw, 2)
            fast[i] = float(np.median(np.hypot(fl[..., 0], fl[..., 1]))) * AW / AN_W
        prev = None; i = 0
        for fr in c.decode(vs):
            self._chk()
            g = fr.reformat(width=AN_W, height=self.ah, format='gray').to_ndarray()
            if prev is not None:
                futs.append(pool.submit(pair, i - 1, prev, g))
            prev = g; i += 1
            if i % 25 == 0:
                self.progress(P_AN * min(i / n_est, 1), self.T('e_prog_analyse', i=i, n=n_est))
            if len(futs) > 400:
                for fu in futs[:200]: fu.result()
                futs = futs[200:]
        for fu in futs: fu.result()
        pool.shutdown(); c.close()
        self.n = i
        self.G = np.array([flows[k] for k in range(self.n - 1)])          # (n-1, gh, gw, 2)
        self.fast = np.array([fast[k] for k in range(self.n - 1)])
        self.pts = np.column_stack([gx.ravel(), gy.ravel()]).astype(np.float64)
        self.log(self.T('e_analysed', n=self.n))

    # -- planning ----------------------------------------------------------------
    def _rot(self, field):
        """3D camera rotation (rotvec) that best explains a flow field sampled on the grid"""
        q = self.pts + field.reshape(-1, 2)
        R, _ = fit_rot(self.pts, q, self.f_an * AN_W / AW, AN_W / 2, self.ah / 2)
        return rotvec(R)

    def _need(self, j, s=1.0):
        """crop zoom frame j needs for its rotation + row-shift correction (scaled by s)"""
        return self._need_of(s * self.delta[j], s * self.drow[j])

    def _need_of(self, d, dr):
        if not (np.abs(d).sum() > 0 or np.abs(dr).sum() > 0):
            return 1.0
        z = frame_need(homography(d, self.f_full, self.w, self.h, 1.0), self.w, self.h)
        sc = self.w / AN_W
        return z * (1 + 2 * max(np.abs(dr[:, 0]).max() * sc / self.w, np.abs(dr[:, 1]).max() * sc / self.h))

    def _predicted_judder(self, G, delta, drow, a, b):
        """RMS of the per-band flow jerk the corrected frames a..b would have (no rendering needed):
        corrected flow = measured flow + displacement of the correction at k+1 - at k"""
        f_a = self.f_an * AN_W / AW
        r0, r1 = max(1, a - 3), min(self.n - 3, b + 3)
        D = {}
        for j in range(r0 - 1, r1 + 2):
            Hm = homography(delta[j], f_a, AN_W, self.ah, 1.0)
            q = cv2.perspectiveTransform(self.pts[None], Hm)[0] - self.pts
            q[:, 0] += np.interp(self.pts[:, 1], self.rows_y, drow[j, :, 0])
            q[:, 1] += np.interp(self.pts[:, 1], self.rows_y, drow[j, :, 1])
            D[j] = q
        F = {k: G[k] + D[k + 1] - D[k] for k in range(r0 - 1, r1 + 1)}
        gh = len(self.rows_y); band = np.repeat(np.minimum(np.arange(gh) * 4 // gh, 3), len(self.pts) // gh)
        mags = []
        for k in range(r0, r1):
            J = F[k] - 0.5 * (F[k - 1] + F[k + 1])
            for bi in range(4):
                m = np.median(J[band == bi], axis=0)
                mags.append(np.hypot(m[0], m[1]))
        return float(np.sqrt(np.mean(np.square(mags)))) if mags else 0.0

    def plan(self):
        p, fps = self.p, self.fps
        self.f_an = F_DEFAULT
        G = self.G.reshape(self.G.shape[0], -1, 2).astype(np.float64)
        # residual of every grid point against its short temporal median -> parallax-free snaps
        resid = G - temporal(medfilt, G, 7)
        self.snap = np.array([self._rot(r) for r in resid])
        # row-wise residual after the global snap rotation (rolling-shutter split snaps), every transition
        gh, gw = self.G.shape[1], self.G.shape[2]
        f_a, cx, cy = self.f_an * AN_W / AW, AN_W / 2, self.ah / 2
        u = rays(self.pts, f_a, cx, cy)
        # a row counts only if most of its columns moved together (a rolling-shutter split shifts
        # whole rows, local motion under the drone does not)
        rowres = np.zeros((self.n - 1, gh, 2)); rowres_all = np.zeros_like(rowres); raw_mag = np.zeros(self.n - 1)
        for k in range(self.n - 1):
            r = u @ rodr(self.snap[k]).T
            pred = np.column_stack([r[:, 0] / r[:, 2] * f_a + cx, r[:, 1] / r[:, 2] * f_a + cy]) - self.pts
            res = (resid[k] - pred).reshape(gh, gw, 2)
            med = np.median(res, axis=1); mag = np.hypot(med[:, 0], med[:, 1])
            dev = np.hypot(res[..., 0] - med[:, None, 0], res[..., 1] - med[:, None, 1])
            agree = (dev < np.maximum(0.5 * mag, 1.0)[:, None]).mean(1)       # tolerance >= flow noise
            raw_mag[k] = min(mag.max(), ROW_MAX) * AW / AN_W
            if mag.max() <= 2 * ROW_MAX:
                rowres_all[k] = np.clip(med, -ROW_MAX, ROW_MAX)
            med[agree < ROW_AGREE] = 0
            if mag.max() > 2 * ROW_MAX:                                   # flow failure, not a snap
                continue
            rowres[k] = np.clip(med, -ROW_MAX, ROW_MAX)
        row_mag = np.hypot(rowres[..., 0], rowres[..., 1]).max(1) * AW / AN_W
        self.events = detect_snaps(self.snap, self.fast, self.f_an, p['thr_px'], p['thr_deg'], row_mag, raw_mag)
        self.log(self.T('e_snaps', n=len(self.events)) +
                 (self.T('e_snaps_at', t=', '.join(f"{e['frame'] / fps:.2f} s" for e in self.events[:40])) if self.events else ''))
        if not self.events:
            return False
        margin, fade = max(1, round(p['margin_s'] * fps)), max(1, round(p['fade_s'] * fps))
        self.zones, wgt = make_zones(self.events, self.n, margin, fade)
        self.log(self.T('e_zones', z=', '.join(f'{a / fps:.2f}–{b / fps:.2f} s' for a, b in self.zones)))
        # every zone gets the best of several correction variants: path smoothing strength x
        # row-wise correction (none / column-consistent rows / all rows), chosen by the predicted
        # remaining judder after scaling to the crop limit
        self.rows_y = self.pts[::gw, 1].copy()                             # analysis-px y of each grid row
        self.f_full = self.f_an * self.w / AW
        lim = (1 + p['max_crop'] / 100) / 1.003                 # zoom_curve adds a 0.3 % safety margin

        def rotation_path(sig):                                            # HF camera rotation, parallax-free
            rad = int(4 * sig)
            need = np.zeros(self.n - 1, bool)
            for a, b in self.zones:
                need[max(0, a - 2 * rad):min(self.n - 1, b + 2 * rad + 1)] = True
            idx = np.where(need)[0]
            lo, hi = max(0, idx[0] - 2 * rad), min(self.n - 1, idx[-1] + 2 * rad + 1)
            Gs = temporal(gauss1d, G[lo:hi], sig)
            hf = np.zeros((self.n - 1, 3))
            for k in idx:
                hf[k] = self._rot(G[k] - Gs[k - lo])
            Q = np.vstack([np.zeros(3), np.cumsum(hf, 0)])
            Qs = np.stack([gauss1d(Q[:, j], sig) for j in range(3)], 1)
            return wgt[:, None] * (Qs - Q)

        def build_drow(rr, sig):                                           # per-row HF path correction
            rr = rr.copy()
            mg = np.hypot(rr[..., 0], rr[..., 1]).max(1) * AW / AN_W
            rr[(mg < ROW_NOISE) | (wgt[1:] == 0)] = 0
            P = np.concatenate([np.zeros((1, gh, 2)), np.cumsum(rr, 0)])
            d = wgt[:, None, None] * (temporal(gauss1d, P, sig) - P)
            return np.stack([np.stack([gauss1d(d[j, :, c], 1.0) for c in range(2)], 1) for j in range(self.n)])

        cands = {}
        for sf in SMOOTH_FACTORS:
            sig = max(0.5, p['smooth_s'] * fps * sf)
            dl = rotation_path(sig)
            cands[(sf, 'none')] = (dl, np.zeros((self.n, gh, 2)))
            cands[(sf, 'rows')] = (dl, build_drow(rowres, sig))
            cands[(sf, 'rows_all')] = (dl, build_drow(rowres_all, sig))
        self.delta = np.zeros((self.n, 3)); self.drow = np.zeros((self.n, gh, 2)); self.zone_method = []
        for a, b in self.zones:
            scores = {}
            for key, (dl, dr) in cands.items():
                worst = max(self._need_of(dl[j], dr[j]) for j in range(a, b + 1))
                sc = 1.0 if worst <= lim else max(0.5, (lim - 1) / (worst - 1))   # what the crop limit allows
                scores[key] = self._predicted_judder(G, sc * dl, sc * dr, a, b)
            # conservative: start from the plain rotation fix; a more complex variant must beat the
            # current choice clearly (flow under the drone can be unreliable)
            best = (SMOOTH_FACTORS[0], 'none')
            for key in sorted(scores, key=lambda k_: (['none', 'rows', 'rows_all'].index(k_[1]), k_[0])):
                if scores[key] < scores[best] * (1 - CHOICE_MARGIN):
                    best = key
            self.delta[a:b + 1] = cands[best][0][a:b + 1]; self.drow[a:b + 1] = cands[best][1][a:b + 1]
            self.zone_method.append(dict(start_s=a / fps, end_s=b / fps, smoothing=best[0], rows=best[1],
                                         predicted_judder=round(scores[best], 3),
                                         predicted_without_rows=round(scores[(best[0], 'none')], 3)))
        # crop zoom
        active = (np.abs(self.delta).sum(1) > 0) | (np.abs(self.drow).sum((1, 2)) > 0)
        needz = np.array([self._need(j) if a else 1.0 for j, a in enumerate(active)])
        zone_need = lambda a, b, s: max(self._need(j, s) for j in range(a, b + 1))
        for a, b in list(self.zones):
            full = needz[a:b + 1].max()
            if full <= lim:
                continue
            if zone_need(a, b, 0.5) > lim:                      # even half the correction does not fit
                self.log(self.T('e_zone_skip', a=a / fps, b=b / fps, c=100 * (full - 1), lim=p['max_crop']))
                self.delta[a:b + 1] = 0; self.drow[a:b + 1] = 0; needz[a:b + 1] = 1.0; active[a:b + 1] = False
                self.zones.remove((a, b))
                continue
            lo_s, hi_s = 0.5, 1.0                                 # strongest correction that fits the crop limit
            for _ in range(12):
                mid = (lo_s + hi_s) / 2
                if zone_need(a, b, mid) <= lim: lo_s = mid
                else: hi_s = mid
            self.delta[a:b + 1] *= lo_s; self.drow[a:b + 1] *= lo_s
            needz[a:b + 1] = [self._need(j) if active[j] else 1.0 for j in range(a, b + 1)]
            if lo_s < 0.995: self.log(self.T('e_zone_scaled', a=a / fps, b=b / fps, c=100 * (full - 1), lim=p['max_crop'], s=100 * lo_s))
        if not self.zones:
            return False
        self.zoom = zoom_curve(needz, active, max(1, round(p['zoom_ramp_s'] * fps)))
        self.log(self.T('e_touched', t=int(active.sum()), n=self.n, c=100 * (self.zoom.max() - 1), u=int((self.zoom == 1).sum())))
        return True

    # -- pass 2: render ----------------------------------------------------------
    def render(self):
        w, h = self.w, self.h
        base = os.path.splitext(os.path.basename(self.src))[0]
        os.makedirs(self.out_dir, exist_ok=True)
        codec = self.p.get('codec', 'hevc')
        out_path = output_path(self.src, self.out_dir, codec)
        prev_path = os.path.join(self.out_dir, base + '_compare.mp4') if self.p['preview'] else None
        tmp_out = out_path + '.part' + os.path.splitext(out_path)[1]

        ic = av.open(self.src); ivs = ic.streams.video[0]; ivs.thread_type = 'AUTO'
        rate = ivs.average_rate or 50
        enc = None
        if codec == 'hevc':                                     # same codec / bit rate as the DJI source
            src_br = ivs.bit_rate or ic.bit_rate or 120_000_000
            enc = pick_hevc_encoder(w, h, rate, src_br)
            if enc is None:                                     # no H.265 encoder at all -> ProRes
                codec = 'prores'; out_path = output_path(self.src, self.out_dir, codec)
                tmp_out = out_path + '.part' + os.path.splitext(out_path)[1]
        oc = av.open(tmp_out, 'w')
        if enc:
            name, opix, opts = enc
            os_ = oc.add_stream(name, rate=rate)
            os_.width, os_.height, os_.pix_fmt = w, h, opix
            os_.bit_rate = int(src_br)
            os_.options = dict(opts)
            os_.codec_context.gop_size = int(round(float(rate)))   # keyframe every second (smooth scrubbing)
            try: os_.codec_context.codec_tag = 'hvc1'                # QuickTime / Resolve friendly
            except Exception: pass
            self.codec_label = HEVC_LABEL.get(name, 'H.265 10-bit')
        else:
            opix = 'yuv422p10le'
            os_ = oc.add_stream('prores_ks', rate=rate)
            os_.width, os_.height, os_.pix_fmt = w, h, opix
            os_.options = {'profile': '3', 'vendor': 'apl0'}
            os_.thread_type = 'FRAME'                           # ~3x faster than slice threading
            os_.thread_count = min(16, os.cpu_count() or 4)
            self.codec_label = 'ProRes 422 HQ'
        for k, v in (('color_primaries', 1), ('color_trc', 1), ('colorspace', 1), ('color_range', 1)):
            try: setattr(os_.codec_context, k, v)
            except Exception: pass
        pc = ps = None
        if prev_path:
            pc = av.open(prev_path + '.part.mp4', 'w')
            for enc in ('h264_nvenc', 'libx264', 'h264_mf', 'mpeg4'):
                try:
                    ps = pc.add_stream(enc, rate=rate); break
                except Exception:
                    ps = None
            if ps is not None:
                ph = int(round(960 * h / w / 2) * 2)
                ps.width, ps.height, ps.pix_fmt = 1920, ph, 'yuv420p'
                ps.bit_rate = 25_000_000
                for k, v in (('color_primaries', 1), ('color_trc', 1), ('colorspace', 1), ('color_range', 1)):
                    try: setattr(ps.codec_context, k, v)
                    except Exception: pass
        tb = 1 / Fraction(rate)
        S = np.diag([0.5, 0.5, 1.0])
        prev_h = ps.height if ps is not None else None

        def job(i, fr):
            """warp + pixel-format conversion of one frame (runs in a worker thread)"""
            k = min(i, self.n - 1)
            Hm = homography(self.delta[k], self.f_full, w, h, self.zoom[k])
            dr = self.drow[k]
            if np.allclose(Hm, np.eye(3)) and not dr.any():
                out = fr.reformat(format=opix)                   # untouched frame
            else:
                a = fr.to_ndarray(format='yuv420p10le')
                Y = a[:h]; uv = a[h:].reshape(-1)
                U = uv[:uv.size // 2].reshape(h // 2, w // 2); V = uv[uv.size // 2:].reshape(h // 2, w // 2)
                if dr.any():                                     # rotation + row-wise shift in one remap
                    mx, my, mxc, myc = row_shift_maps(Hm, self.rows_y, dr, w, h, w / AN_W)
                    rm = lambda img, X, Yy: cv2.remap(img, X, Yy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
                    yo, uo, vo = rm(Y, mx, my), rm(U, mxc, myc), rm(V, mxc, myc)
                else:
                    Hc = S @ Hm @ np.linalg.inv(S)
                    wp = lambda img, M, sz: cv2.warpPerspective(img, M, sz, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
                    yo, uo, vo = wp(Y, Hm, (w, h)), wp(U, Hc, (w // 2, h // 2)), wp(V, Hc, (w // 2, h // 2))
                b_ = np.concatenate([yo, np.concatenate([uo.ravel(), vo.ravel()]).reshape(-1, w)])
                nf = av.VideoFrame.from_ndarray(b_, format='yuv420p10le')
                copy_color_tags(fr, nf)                          # else tagged "unspecified" -> other matrix -> colour jump
                out = nf.reformat(format=opix)
            copy_color_tags(fr, out)
            out.pts, out.time_base = i, tb
            pf = None
            if prev_h:
                l = fr.reformat(width=960, height=prev_h, format='rgb24').to_ndarray()
                r = out.reformat(width=960, height=prev_h, format='rgb24').to_ndarray()
                fmt = getattr(_tls, 'pfmt', None)
                if fmt is None:                                  # one reformatter per worker thread
                    fmt = _tls.pfmt = av.video.reformatter.VideoReformatter()
                pf = fmt.reformat(av.VideoFrame.from_ndarray(np.hstack([l, r]), format='rgb24'), format='yuv420p',
                                        dst_colorspace='ITU709', dst_color_range='MPEG')
                for a_, v_ in (('colorspace', 1), ('color_primaries', 1), ('color_trc', 1), ('color_range', 1)):
                    setattr(pf, a_, v_)
                pf.pts, pf.time_base = i, tb
            return out, pf

        cv2.setNumThreads(os.cpu_count() or 8)                 # render: let OpenCV use every core
        pool = ThreadPoolExecutor(4); pending = deque()

        def drain(limit):
            while len(pending) > limit:
                out, pf = pending.popleft().result()
                for pk in os_.encode(out): oc.mux(pk)
                if pf is not None:
                    for pk in ps.encode(pf): pc.mux(pk)

        i = 0
        try:
            for fr in ic.decode(ivs):
                self._chk()
                pending.append(pool.submit(job, i, fr)); i += 1
                drain(12)
                if i % 10 == 0:
                    self.progress(P_REN + (1 - P_REN) * min(i / self.n, 1), self.T('e_prog_render', i=i, n=self.n))
            drain(0)
            for pk in os_.encode(): oc.mux(pk)
            if ps is not None:
                for pk in ps.encode(): pc.mux(pk)
        finally:
            for fu in pending: fu.cancel()
            pool.shutdown(wait=True); cv2.setNumThreads(1)
            oc.close(); ic.close()
            if pc is not None: pc.close()
        os.replace(tmp_out, out_path)
        if prev_path and ps is not None:
            os.replace(prev_path + '.part.mp4', prev_path)
        elif prev_path and os.path.exists(prev_path + '.part.mp4'):
            os.remove(prev_path + '.part.mp4')
        self.out_path, self.prev_path = out_path, (prev_path if ps is not None else None)
        return out_path

    def report(self):
        path = os.path.splitext(self.out_path)[0] + '_report.json'
        json.dump(dict(source=self.src, output=self.out_path, fps=self.fps, frames=self.n,
                       params=self.p, focal_px_at_960=self.f_an, snaps=self.events,
                       zones_s=[(a / self.fps, b / self.fps) for a, b in self.zones],
                       max_crop_percent=100 * (float(self.zoom.max()) - 1),
                       zone_methods=getattr(self, 'zone_method', []), output_codec=getattr(self, 'codec_label', '')),
                  open(path, 'w', encoding='utf8'), ensure_ascii=False, indent=1)

    def run(self):
        try:
            self.analyse(); self._chk()
            self.progress(P_AN + 0.01, self.T('e_prog_plan'))
            if not self.plan():
                self.progress(1.0, self.T('e_prog_none'))
                self.log(self.T('e_none'))
                return None
            self._chk()
            out = self.render()
            self.report()
            self.progress(1.0, self.T('e_prog_done'))
            self.log(self.T('e_done', p=out) + ('\n' + self.T('e_preview', p=self.prev_path) if self.prev_path else ''))
            return out
        except Cancelled:
            self.log(self.T('e_cancelled'))
            self.progress(0, self.T('e_prog_cancelled'))
            self._cleanup()
            return None

    def _cleanup(self):
        base = os.path.splitext(os.path.basename(self.src))[0]
        for f in (base + '_fix.mov.part.mov', base + '_fix.mp4.part.mp4', base + '_compare.mp4.part.mp4'):
            fp = os.path.join(self.out_dir, f)
            try:
                if os.path.exists(fp): os.remove(fp)
            except OSError:
                pass
