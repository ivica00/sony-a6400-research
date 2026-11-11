"""Offline reference model and quality comparison for CinemaHUD MOTION interpolation.

This is a *research/evaluation* tool, not application code.  It ports the two
shipped Flutter runtime-effect shaders (``shaders/flow.frag`` and
``shaders/interpolate.frag``) to a NumPy reference model, then compares that
baseline against candidate algorithms on deterministic synthetic motion.

Why: MOTION (GPU optical flow x2 midpoint synthesis) was reported unusable due
to artifacts.  Judging "artifacts" on a live camera feed is subjective, so this
tool measures separable numeric error against an exact ground-truth midpoint
for known motion.  It answers two questions:

1. How much of the error is the *flow estimate* and how much is the *synthesis*
   (occlusion / consistency / low-resolution flow upsampling)?
2. Does a candidate algorithm actually improve those numbers before it is
   written as GLSL and flashed to a phone?

The model deliberately mirrors the shader math (same clamps, same encodings,
same fallbacks) so parameter changes transfer to GLSL.  It is not a GPU
implementation and does not measure shader cost.  Real sensor content, lens
distortion, rolling shutter and true 3-D parallax are represented only by a
real-photo translation test, not by a camera model.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ART = Path('artifacts/analysis/motion-eval')

# ---------------------------------------------------------------------------
# Sampling helpers (bilinear, clamp-to-edge) matching GLSL texture() semantics
# ---------------------------------------------------------------------------


def bilinear(img: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Sample HxWxC image at float pixel coordinates (x, y). Clamp to edge."""
    h, w = img.shape[:2]
    x = np.clip(x, 0.0, w - 1.0)
    y = np.clip(y, 0.0, h - 1.0)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx = (x - x0)[..., None]
    fy = (y - y0)[..., None]
    a = img[y0, x0]
    b = img[y0, x1]
    c = img[y1, x0]
    d = img[y1, x1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def luma(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return img[..., 0] * 0.2126 + img[..., 1] * 0.7152 + img[..., 2] * 0.0722


def smoothstep(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def gray3(img: np.ndarray) -> np.ndarray:
    g = luma(img)
    return np.repeat(g[..., None], 3, axis=2)


# ---------------------------------------------------------------------------
# Coordinate grids
# ---------------------------------------------------------------------------

def grid(w: int, h: int):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    return xx, yy


# ---------------------------------------------------------------------------
# Baseline flow: faithful port of shaders/flow.frag
# ---------------------------------------------------------------------------

PATCH_OLD = [(0, 0), (-3, 0), (3, 0), (0, -3), (0, 3)]


def _match_cost_old(prev_g, cur_g, uvx, uvy, dx, dy, sw, sh):
    """mean |prev(uv+p/S-d) - cur(uv+p/S)| over the 5-sample cross."""
    total = 0.0
    for px, py in PATCH_OLD:
        atx = np.clip(uvx + px / sw, 0.0, 1.0)
        aty = np.clip(uvy + py / sh, 0.0, 1.0)
        ax = np.clip(atx - dx / sw, 0.0, 1.0) * (sw - 1)
        ay = np.clip(aty - dy / sh, 0.0, 1.0) * (sh - 1)
        bx = np.clip(atx, 0.0, 1.0) * (sw - 1)
        by = np.clip(aty, 0.0, 1.0) * (sh - 1)
        a = bilinear(prev_g, ax, ay)[..., 0]
        b = bilinear(cur_g, bx, by)[..., 0]
        total = total + np.abs(a - b)
    return total / len(PATCH_OLD)


def flow_old(prev, cur, fw=160, fh=90):
    """Port of the shipped flow.frag at flow resolution fw x fh."""
    sw, sh = cur.shape[1], cur.shape[0]
    xx, yy = grid(fw, fh)
    uvx = (xx + 0.5) / fw
    uvy = (yy + 0.5) / fh
    prev_g, cur_g = gray3(prev), gray3(cur)

    dx = np.zeros((fh, fw))
    dy = np.zeros((fh, fw))
    best = _match_cost_old(prev_g, cur_g, uvx, uvy, dx, dy, sw, sh)
    reg = 0.000002
    for step in (8.0, 4.0, 2.0, 1.0):
        origin_x, origin_y = dx.copy(), dy.copy()
        sel_x, sel_y = dx.copy(), dy.copy()
        score = best + reg * (dx * dx + dy * dy)
        for oy in (-1, 0, 1):
            for ox in (-1, 0, 1):
                cx = origin_x + ox * step
                cy = origin_y + oy * step
                cost = _match_cost_old(prev_g, cur_g, uvx, uvy, cx, cy, sw, sh)
                nexts = cost + reg * (cx * cx + cy * cy)
                better = nexts < score
                score = np.where(better, nexts, score)
                best = np.where(better, cost, best)
                sel_x = np.where(better, cx, sel_x)
                sel_y = np.where(better, cy, sel_y)
        dx, dy = sel_x, sel_y
    conf = 1.0 - smoothstep(0.025, 0.12, best)
    return dx, dy, conf


# ---------------------------------------------------------------------------
# Baseline synthesis: faithful port of shaders/interpolate.frag
# ---------------------------------------------------------------------------

def synth_old(prev, cur, dx_f, dy_f, conf_f, fw, fh):
    """Port of the shipped interpolate.frag (bilinear low-res flow + hard fallback)."""
    h, w = cur.shape[:2]
    xx, yy = grid(w, h)
    uvx = (xx + 0.5) / w
    uvy = (yy + 0.5) / h
    fx = (uvx * fw - 0.5)
    fy = (uvy * fh - 0.5)
    dx = bilinear(dx_f[..., None], fx, fy)[..., 0]
    dy = bilinear(dy_f[..., None], fx, fy)[..., 0]
    conf = bilinear(conf_f[..., None], fx, fy)[..., 0]
    px = uvx * w - dx * 0.5
    py = uvy * h - dy * 0.5
    qx = uvx * w + dx * 0.5
    qy = uvy * h + dy * 0.5
    a = bilinear(prev, px, py)
    b = bilinear(cur, qx, qy)
    fallback = (conf < 0.35) | (np.sqrt(((a - b) ** 2).sum(axis=2)) > 0.24)
    out = (a + b) * 0.5
    real = bilinear(cur, uvx * (w - 1), uvy * (h - 1))
    out = np.where(fallback[..., None], real, out)
    return out


# ---------------------------------------------------------------------------
# Candidate flow: left-right consistent, wider patch, subpixel refinement
# ---------------------------------------------------------------------------

# 9 samples on a 3x3 grid at +/-2 source pixels plus centre.
PATCH_NEW = [(0, 0), (-2, 0), (2, 0), (0, -2), (0, 2),
             (-2, -2), (2, -2), (-2, 2), (2, 2)]


def _cost(prev_g, cur_g, uvx, uvy, dx, dy, sw, sh, patch):
    total = 0.0
    for px, py in patch:
        atx = np.clip(uvx + px / sw, 0.0, 1.0)
        aty = np.clip(uvy + py / sh, 0.0, 1.0)
        ax = np.clip(atx - dx / sw, 0.0, 1.0) * (sw - 1)
        ay = np.clip(aty - dy / sh, 0.0, 1.0) * (sh - 1)
        bx = atx * (sw - 1)
        by = aty * (sh - 1)
        total = total + np.abs(bilinear(prev_g, ax, ay)[..., 0]
                               - bilinear(cur_g, bx, by)[..., 0])
    return total / len(patch)


def _subpixel(cost_c, cost_xm, cost_xp, cost_ym, cost_yp, step):
    """Parabola fit around the best integer vector (step 1 at the last level)."""
    denx = cost_xm - 2 * cost_c + cost_xp
    deny = cost_ym - 2 * cost_c + cost_yp
    with np.errstate(divide='ignore', invalid='ignore'):
        ox = np.where(np.abs(denx) > 1e-6,
                      0.5 * (cost_xm - cost_xp) / denx, 0.0).clip(-0.75, 0.75)
        oy = np.where(np.abs(deny) > 1e-6,
                      0.5 * (cost_ym - cost_yp) / deny, 0.0).clip(-0.75, 0.75)
    return ox * step, oy * step


def flow_new(prev, cur, fw=160, fh=90, patch=PATCH_NEW, reg_lambda=0.0005,
             steps=(8.0, 4.0, 2.0, 1.0), subpixel=True):
    """Candidate flow: 3x3 patch SAD, motion penalty, subpixel final refinement."""
    sw, sh = cur.shape[1], cur.shape[0]
    xx, yy = grid(fw, fh)
    uvx = (xx + 0.5) / fw
    uvy = (yy + 0.5) / fh
    prev_g, cur_g = gray3(prev), gray3(cur)
    dx = np.zeros((fh, fw))
    dy = np.zeros((fh, fw))
    best = _cost(prev_g, cur_g, uvx, uvy, dx, dy, sw, sh, patch)
    score = best + reg_lambda * (dx * dx + dy * dy)
    for step in steps:
        ox0, oy0 = dx.copy(), dy.copy()
        sel_x, sel_y = dx.copy(), dy.copy()
        best_s, score_s = best.copy(), score.copy()
        for oy in (-1, 0, 1):
            for oxx in (-1, 0, 1):
                if oxx == 0 and oy == 0:
                    continue
                cx = ox0 + oxx * step
                cy = oy0 + oy * step
                cost = _cost(prev_g, cur_g, uvx, uvy, cx, cy, sw, sh, patch)
                cand = cost + reg_lambda * (cx * cx + cy * cy)
                better = cand < score_s
                score_s = np.where(better, cand, score_s)
                best_s = np.where(better, cost, best_s)
                sel_x = np.where(better, cx, sel_x)
                sel_y = np.where(better, cy, sel_y)
        dx, dy, best, score = sel_x, sel_y, best_s, score_s
    if subpixel:
        c = _cost(prev_g, cur_g, uvx, uvy, dx, dy, sw, sh, patch)
        cxm = _cost(prev_g, cur_g, uvx, uvy, dx - 1, dy, sw, sh, patch)
        cxp = _cost(prev_g, cur_g, uvx, uvy, dx + 1, dy, sw, sh, patch)
        cym = _cost(prev_g, cur_g, uvx, uvy, dx, dy - 1, sw, sh, patch)
        cyp = _cost(prev_g, cur_g, uvx, uvy, dx, dy + 1, sw, sh, patch)
        sx, sy = _subpixel(c, cxm, cxp, cym, cyp, 1.0)
        dx, dy = dx + sx, dy + sy
        best = np.minimum.reduce([c, cxm, cxp, cym, cyp])
    conf = 1.0 - smoothstep(0.020, 0.10, best)
    return dx, dy, conf


# ---------------------------------------------------------------------------
# Candidate synthesis: joint-bilateral flow upsample + forward/backward check
# ---------------------------------------------------------------------------

def _flow_gather(dx, dy, conf, uvx, uvy, fw, fh, cur_g, radius=1, sigma_l=0.04):
    """Joint-bilateral upsample of the low-res flow field guided by current luma.

    Returns filtered dx, dy, conf and the sample position of the central texel.
    Only (2r+1)^2 taps; no separate smoothing pass is required.
    """
    h, w = cur_g.shape[:2]
    # central texel luma for similarity weights
    px = uvx * (w - 1)
    py = uvy * (h - 1)
    lc = bilinear(gray3(cur_g), px, py)[..., 0]
    fx = uvx * fw - 0.5
    fy = uvy * fh - 0.5
    acc = np.zeros_like(uvx)
    accx = np.zeros_like(uvx)
    accy = np.zeros_like(uvx)
    for oy in range(-radius, radius + 1):
        for ox in range(-radius, radius + 1):
            sx, sy = fx + ox, fy + oy
            # texel-centre luma in current frame for this flow texel
            tx = ((sx + 0.5) / fw)
            ty = ((sy + 0.5) / fh)
            tl = bilinear(gray3(cur_g), tx * (w - 1), ty * (h - 1))[..., 0]
            d = bilinear(dx[..., None], sx, sy)[..., 0]
            e = bilinear(dy[..., None], sx, sy)[..., 0]
            c = bilinear(conf[..., None], sx, sy)[..., 0]
            wgt = c * np.exp(-((tl - lc) ** 2) / (2 * sigma_l * sigma_l))
            acc += wgt
            accx += wgt * d
            accy += wgt * e
    safe = np.maximum(acc, 1e-6)
    return accx / safe, accy / safe, np.clip(acc, 0.0, 1.0)


def synth_new(prev, cur, fdx, fdy, fconf, bdx, bdy, bconf, fw, fh,
              radius=1, sigma_l=0.04, tau=1.25, fallback_current=True):
    """Candidate midpoint: consistent bidirectional warp, no hard 50/50 ghosts."""
    h, w = cur.shape[:2]
    xx, yy = grid(w, h)
    uvx = (xx + 0.5) / w
    uvy = (yy + 0.5) / h
    prev_g = luma(prev)
    cur_g = luma(cur)

    dx, dy, cf = _flow_gather(fdx, fdy, fconf, uvx, uvy, fw, fh, cur_g,
                              radius, sigma_l)
    # Backward flow sampled at the forward-warped position x + F (current coords)
    nfx = uvx + dx / w
    nfy = uvy + dy / h
    ex, ey, cb = _flow_gather(bdx, bdy, bconf, nfx, nfy, fw, fh, cur_g,
                              radius, sigma_l)
    resid = np.sqrt((dx + ex) ** 2 + (dy + ey) ** 2)
    allowed = tau + 0.10 * np.sqrt(dx * dx + dy * dy)
    consistent = (resid <= allowed) & (cf > 0.30) & (cb > 0.30)

    px = uvx * (w - 1) - dx * 0.5
    py = uvy * (h - 1) - dy * 0.5
    # A point visible in the current frame at x is, at the midpoint, at x + 0.5*B
    fx = uvx * fw - 0.5
    fy = uvy * fh - 0.5
    rbx = bilinear(bdx[..., None], fx, fy)[..., 0]
    rby = bilinear(bdy[..., None], fx, fy)[..., 0]
    # backward flow B maps current->previous; the current-frame sample for the
    # midpoint is at x - 0.5*B (equivalently x + 0.5*F).
    qx = uvx * (w - 1) - rbx * 0.5
    qy = uvy * (h - 1) - rby * 0.5
    a = bilinear(prev, px, py)
    b = bilinear(cur, qx, qy)
    mid = (a + b) * 0.5
    real = bilinear(cur, uvx * (w - 1), uvy * (h - 1))
    # Smooth confidence -> avoid hard popping between generated and real frames.
    weight = np.where(consistent, 1.0, 0.0)
    # soften the boundary with a small smoothstep on the consistency residual
    soft = 1.0 - smoothstep(allowed * 0.6, allowed, resid)
    weight = np.minimum(weight, soft)
    return mid * weight[..., None] + real * (1.0 - weight[..., None])


# ---------------------------------------------------------------------------
# Synthetic scenes with exact ground-truth midpoint
# ---------------------------------------------------------------------------

def shift(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    h, w = img.shape[:2]
    xx, yy = grid(w, h)
    return bilinear(img, xx - dx, yy - dy)


def load_reference(size=(1024, 576)) -> np.ndarray:
    candidates = sorted(Path('assets/reference').glob('*.jpg'))
    if not candidates:
        raise SystemExit('no reference image under assets/reference')
    img = Image.open(candidates[0]).convert('RGB')
    # central crop, then resize
    w, h = img.size
    target_ratio = size[0] / size[1]
    crop_h = int(w / target_ratio)
    if crop_h <= h:
        top = (h - crop_h) // 2
        img = img.crop((0, top, w, top + crop_h))
    img = img.resize(size, Image.LANCZOS)
    return np.asarray(img, dtype=np.float64) / 255.0


def jpeg_roundtrip(img: np.ndarray, quality=85) -> np.ndarray:
    data = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    import io
    buf = io.BytesIO()
    Image.fromarray(data).save(buf, 'JPEG', quality=quality)
    buf.seek(0)
    return np.asarray(Image.open(buf).convert('RGB'), dtype=np.float64) / 255.0


def make_scene(kind: str, size=(1024, 576)) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (previous, truth_midpoint, current) with exact known motion."""
    w, h = size
    base = load_reference(size)
    if kind == 'pan2':
        pts = np.asarray(base)
        prev = shift(pts, -1.0, 0.0)
        mid = pts.copy()
        cur = shift(pts, 1.0, 0.0)
    elif kind == 'pan6':
        prev = shift(base, -3.0, -1.0)
        mid = base.copy()
        cur = shift(base, 3.0, 1.0)
    elif kind == 'subpixel':
        prev = shift(base, -0.75, -0.25)
        mid = base.copy()
        cur = shift(base, 0.75, 0.25)
    elif kind == 'occlusion':
        # textured square moves left-to-right over the real background
        prev = base.copy()
        mid = base.copy()
        cur = base.copy()
        rng = np.random.default_rng(7)
        tile = (rng.random((90, 90, 3)) * 0.9 + 0.05)
        tile = np.asarray(Image.fromarray((tile * 255).astype(np.uint8))
                          .filter(ImageFilter.GaussianBlur(0.6)), dtype=np.float64) / 255.0
        for img, dx in ((prev, -12), (mid, 0), (cur, 12)):
            x0, y0 = 380 + dx, 240
            img[y0:y0 + 90, x0:x0 + 90] = tile
    else:
        raise SystemExit(f'unknown scene {kind}')
    # sensor/JPEG-like noise independent per frame
    prev = jpeg_roundtrip(prev, 88)
    mid = jpeg_roundtrip(mid, 88)
    cur = jpeg_roundtrip(cur, 88)
    return prev, mid, cur


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def metrics(out: np.ndarray, truth: np.ndarray) -> dict:
    d = out - truth
    mse = float((d * d).mean())
    psnr = 10 * np.log10(1.0 / max(mse, 1e-12))
    absd = np.abs(d)
    bad = float((absd.max(axis=2) > 24 / 255).mean())
    # error where there is real structure
    gx = np.abs(np.diff(truth, axis=1)).sum(axis=2)
    gy = np.abs(np.diff(truth, axis=0)).sum(axis=2)
    gx = np.pad(gx, ((0, 0), (0, 1)))
    gy = np.pad(gy, ((0, 1), (0, 0)))
    edge = (gx + gy) > np.quantile(gx + gy, 0.90)
    edge_err = float(absd.max(axis=2)[edge].mean()) if edge.any() else 0.0
    return {'mse': mse, 'psnr': psnr, 'bad_px_frac': bad, 'edge_err': edge_err}


def blend(prev, cur):
    return (prev + cur) * 0.5


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

@dataclass
class Variant:
    name: str
    fw: int
    fh: int
    patch: str
    subpixel: bool
    bidirectional: bool
    bilateral_radius: int
    synth: str


def run_variant(scene, variant: Variant) -> dict:
    prev, truth, cur = scene
    if variant.patch == 'cross5':
        patch = PATCH_OLD
    else:
        patch = PATCH_NEW
    fdx, fdy, fconf = flow_new(prev, cur, variant.fw, variant.fh,
                               patch=patch, subpixel=variant.subpixel,
                               reg_lambda=0.0005)
    if variant.bidirectional:
        bdx, bdy, bconf = flow_new(cur, prev, variant.fw, variant.fh,
                                   patch=patch, subpixel=variant.subpixel,
                                   reg_lambda=0.0005)
    else:
        bdx, bdy, bconf = -fdx, -fdy, fconf
    out = synth_new(prev, cur, fdx, fdy, fconf, bdx, bdy, bconf,
                    variant.fw, variant.fh,
                    radius=variant.bilateral_radius)
    return metrics(out, truth)


def old_pipeline(scene, fw=160, fh=90) -> dict:
    prev, truth, cur = scene
    dx, dy, conf = flow_old(prev, cur, fw, fh)
    out = synth_old(prev, cur, dx, dy, conf, fw, fh)
    return metrics(out, truth)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=ART)
    ap.add_argument('--scenes', default='pan2,pan6,subpixel,occlusion')
    ap.add_argument('--dump', action='store_true', help='write comparison PNGs')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    scenes = {}
    for kind in args.scenes.split(','):
        scenes[kind] = make_scene(kind)

    variants = [
        Variant('A-baseline', 160, 90, 'cross5', False, False, 0, 'old-but-new'),
        Variant('B-patch9', 160, 90, 'patch9', True, False, 0, 'new'),
        Variant('C-bidir', 160, 90, 'patch9', True, True, 0, 'new'),
        Variant('D-bidir-bilat', 160, 90, 'patch9', True, True, 1, 'new'),
        Variant('E-bidir-bilat256', 256, 144, 'patch9', True, True, 1, 'new'),
    ]

    report = {'scenes': {}, 'notes': [
        'Ground truth is an exactly known midpoint of a real-photo translation.',
        'Occlusion scene is a textured square translated over a real photo.',
        'Old numbers come from the ported shipped shaders; no GPU timings here.',
    ]}
    for kind, scene in scenes.items():
        rows = {}
        rows['repeat-current'] = metrics(scene[2], scene[1])
        rows['blend-prev-cur'] = metrics(blend(scene[0], scene[2]), scene[1])
        rows['old-160x90'] = old_pipeline(scene)
        if args.dump:
            prev, truth, cur = scene
            dx, dy, conf = flow_old(prev, cur, 160, 90)
            out = synth_old(prev, cur, dx, dy, conf, 160, 90)
            dump(prev, truth, cur, out, args.out / f'{kind}-old.png')
        for v in variants:
            if v.name == 'A-baseline':
                continue
            rows[v.name] = run_variant(scene, v)
            if args.dump:
                prev, truth, cur = scene
                out = _variant_image(prev, cur, v)
                dump(prev, truth, cur, out, args.out / f'{kind}-{v.name}.png')
        report['scenes'][kind] = rows
        print(f'\n== {kind} ==')
        for name, row in rows.items():
            print(f'{name:22s} mse={row["mse"]*255*255:8.2f}  '
                  f'psnr={row["psnr"]:5.2f}  bad={row["bad_px_frac"]*100:5.1f}%  '
                  f'edge={row["edge_err"]*255:6.2f}')
    (args.out / 'report.json').write_text(json.dumps(report, indent=2))
    print(f'\nwritten: {args.out / "report.json"}')


def _variant_image(prev, cur, variant: Variant) -> np.ndarray:
    patch = PATCH_OLD if variant.patch == 'cross5' else PATCH_NEW
    fdx, fdy, fconf = flow_new(prev, cur, variant.fw, variant.fh,
                               patch=patch, subpixel=variant.subpixel)
    if variant.bidirectional:
        bdx, bdy, bconf = flow_new(cur, prev, variant.fw, variant.fh,
                                   patch=patch, subpixel=variant.subpixel)
    else:
        bdx, bdy, bconf = -fdx, -fdy, fconf
    return synth_new(prev, cur, fdx, fdy, fconf, bdx, bdy, bconf,
                     variant.fw, variant.fh, radius=variant.bilateral_radius)


def dump(prev, truth, cur, out, path: Path):
    panels = []
    for img in (prev, truth, cur, out):
        panels.append((np.clip(img, 0, 1) * 255).astype(np.uint8))
    diff = (np.abs(out - truth) * 255 * 4).clip(0, 255).astype(np.uint8)
    panels.append(diff)
    Image.fromarray(np.concatenate(panels, axis=1)).save(path)


if __name__ == '__main__':
    main()
