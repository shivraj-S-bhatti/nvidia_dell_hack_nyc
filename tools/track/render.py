"""render.py -- Track's visual evidence: pictures of what the ranking measured.

    python3 tools/track/render.py                        # read the last report
    python3 tools/track/render.py --scale 4 --out-dir /tmp/ev

For the baseline and every candidate in `.artifacts/track/track-report.json` this
writes:

    mask-<id>.png    the occupancy mask the solver was handed, with the frozen
                     fixture drawn on top -- support pads blue, payload pad
                     orange -- so a viewer can confirm by eye that the test did
                     not move between candidates
    energy-<id>.png  the per-element strain-energy field that produced the
                     compliance number, on one shared colour scale
    diff-<id>.png    baseline vs candidate: material kept / removed / added
    index.html       one self-contained page with every image inlined, plus a
                     copy at `<report dir>/evidence.html`

WHAT THESE IMAGES ARE. Evidence for a stiffness-proxy comparison: 2D
linear-elastic plane-stress strain energy on the frozen Track fixture, summed
over its two declared load cases, used to rank material layouts against each
other on one test. Supports, load magnitude, direction and material are declared
demo test-fixture assumptions (see fixture.py), and the field is computed on a
raster of the plate footprint, not on its solid geometry.

WHAT THEY ARE NOT. They are not stress plots. They carry no factor of safety, no
failure criterion, and no absolute magnitude anyone could sign off against. The
energy scale here is deliberately clipped and log-compressed so that load *paths*
read at a glance -- which is the opposite of what a plot for engineering sign-off
would do. Nothing this file writes is a certification artifact.

numpy + stdlib only. PNGs are encoded here with zlib+struct instead of through
PIL or matplotlib because neither ships as a pure-Python wheel: the whole
pipeline has to run on the ARM64 GB10 with no native build on the path and no
network (tools/depgraph/README.md). A PNG is a signature plus length/type/CRC32
chunks, so hand-rolling it costs ~30 lines and keeps that claim true.
"""
import argparse
import base64
import html as html_mod
import json
import os
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evaluate as ev  # noqa: E402
import fixture as fixture_mod  # noqa: E402
import manifest as mf  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, "..", ".."))
DEFAULT_ARTIFACTS = os.path.join(_REPO, ".artifacts", "depgraph")
DEFAULT_STEP = os.path.join(_REPO, "S500-C1_ASM.step")

# --- palette --------------------------------------------------------------
# Fixed RGB, not a theme: these bytes go into the PNGs, which have to mean the
# same thing whichever way the page around them is themed.
MATERIAL = (34, 40, 49)          # solid cells
VOID_A = (243, 245, 248)         # void, checker light square
VOID_B = (231, 235, 241)         # void, checker dark square
SUPPORT = (37, 99, 190)          # arm-mount support pads
LOAD = (224, 122, 20)            # central payload pad
KEPT = (52, 58, 68)              # diff: material both have
REMOVED = (198, 55, 47)          # diff: baseline had it, candidate does not
ADDED = (26, 140, 118)           # diff: candidate has it, baseline does not
ENERGY_VOID = (150, 156, 165)    # void in an energy image: background, not zero

CHECKER_CELLS = 4                # void checker block, in grid cells
PAD_ALPHA = 0.85                 # pad fill opacity over the mask image

# Perceptually ordered ramp: relative luminance rises monotonically across every
# stop (17 -> 38 -> 61 -> 97 -> 157 -> 205 -> 245), so the image still reads in
# rank order printed greyscale or seen by a colour-blind viewer. Hue is along for
# the ride; luminance carries the data.
RAMP_STOPS = (
    (0.00, (12, 16, 38)),
    (0.20, (62, 24, 100)),
    (0.40, (135, 34, 106)),
    (0.60, (200, 70, 64)),
    (0.80, (240, 145, 28)),
    (0.92, (250, 205, 70)),
    (1.00, (255, 247, 200)),
)

# Strain energy on this fixture spans ~4 orders of magnitude between the plate
# rim and the bolt pads (baseline median 1.8e-6, max 1.4e-3 N*mm). Linear colour
# would paint four dots on a black plate. Both knobs below are declared on the
# page rather than hidden, because they change what the picture emphasises.
VMAX_QUANTILE = 0.995            # clip at this quantile of baseline solid cells
LOG_K = 999.0                    # t -> log1p(K*t)/log1p(K)


# --- PNG ------------------------------------------------------------------
_SIG = b"\x89PNG\r\n\x1a\n"


def _chunk(tag, data):
    """length + type + data + CRC32(type||data), all big-endian."""
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path, rgb):
    """rgb: np.ndarray (h, w, 3) uint8. Writes a valid PNG using zlib+struct only.

    Truecolour 8-bit, no interlace, every scanline on filter 0. Filtering would
    shrink the file; it would also add the one part of the format that can be
    wrong in a way a viewer renders instead of rejecting.
    """
    a = np.ascontiguousarray(rgb)
    if a.dtype != np.uint8 or a.ndim != 3 or a.shape[2] != 3:
        raise ValueError("write_png expects an (h, w, 3) uint8 array, got %s %s"
                         % (a.shape, a.dtype))
    h, w = int(a.shape[0]), int(a.shape[1])
    if h < 1 or w < 1:
        raise ValueError("write_png: empty image %dx%d" % (w, h))

    rows = np.zeros((h, w * 3 + 1), dtype=np.uint8)   # leading 0 = filter "None"
    rows[:, 1:] = a.reshape(h, w * 3)

    png = (_SIG
           + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + _chunk(b"IDAT", zlib.compress(rows.tobytes(), 9))
           + _chunk(b"IEND", b""))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(png)
    return path


def read_png(path):
    """Decode a PNG written by write_png, verifying every chunk CRC.

    Exists so the writer above can be checked against itself without importing a
    decoder. Handles exactly what write_png emits.
    """
    blob = Path(path).read_bytes()
    if blob[:8] != _SIG:
        raise ValueError("%s: not a PNG signature" % path)
    pos, hdr, idat = 8, None, b""
    while pos < len(blob):
        (n,) = struct.unpack_from(">I", blob, pos)
        tag = blob[pos + 4:pos + 8]
        data = blob[pos + 8:pos + 8 + n]
        (crc,) = struct.unpack_from(">I", blob, pos + 8 + n)
        if crc != (zlib.crc32(tag + data) & 0xFFFFFFFF):
            raise ValueError("%s: CRC32 mismatch on %s chunk at byte %d"
                             % (path, tag.decode("ascii", "replace"), pos))
        if tag == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", data)
        elif tag == b"IDAT":
            idat += data
        pos += 12 + n
    if hdr is None:
        raise ValueError("%s: no IHDR" % path)
    w, h, depth, ctype, comp, filt, interlace = hdr
    if (depth, ctype, comp, filt, interlace) != (8, 2, 0, 0, 0):
        raise ValueError("%s: unexpected IHDR %s" % (path, hdr))
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8)
    if raw.size != h * (w * 3 + 1):
        raise ValueError("%s: %d raw bytes, expected %d"
                         % (path, raw.size, h * (w * 3 + 1)))
    rows = raw.reshape(h, w * 3 + 1)
    if rows[:, 0].any():
        raise ValueError("%s: a scanline uses a filter this reader does not "
                         "implement" % path)
    return rows[:, 1:].reshape(h, w, 3)


# --- raster helpers -------------------------------------------------------
def _present(img, scale):
    """Grid array -> screen pixels: zmax on top (the ascii preview's convention,
    and the way a top view of the plate is read), then nearest-neighbour upscale
    so one cell stays one visible square."""
    s = max(1, int(scale))
    return np.repeat(np.repeat(img[::-1], s, axis=0), s, axis=1)


def _checker(shape):
    ys = (np.arange(shape[0]) // CHECKER_CELLS)[:, None]
    xs = (np.arange(shape[1]) // CHECKER_CELLS)[None, :]
    return ((ys + xs) % 2).astype(bool)


def _canvas(shape, colour):
    out = np.empty((shape[0], shape[1], 3), dtype=np.uint8)
    out[:, :] = np.array(colour, dtype=np.uint8)
    return out


def _void_ground(shape):
    """Void reads as "nothing here", not as a pale material. A checker says that
    without needing a legend."""
    out = _canvas(shape, VOID_A)
    out[_checker(shape)] = np.array(VOID_B, dtype=np.uint8)
    return out


def _paint(img, sel, colour):
    if sel.any():
        img[sel] = np.array(colour, dtype=np.uint8)


def _blend(img, sel, colour, alpha):
    if not sel.any():
        return
    c = np.array(colour, dtype=np.float64)
    img[sel] = np.rint(img[sel] * (1.0 - alpha) + c * alpha).astype(np.uint8)


def _outline(sel):
    """One-cell boundary of a boolean region. Outlines, not fills, are what an
    annotation over a data field has to be -- a fill would hide the data it is
    annotating."""
    sel = np.asarray(sel, dtype=bool)
    e = np.zeros_like(sel)
    e[:-1, :] |= sel[:-1, :] & ~sel[1:, :]
    e[1:, :] |= sel[1:, :] & ~sel[:-1, :]
    e[:, :-1] |= sel[:, :-1] & ~sel[:, 1:]
    e[:, 1:] |= sel[:, 1:] & ~sel[:, :-1]
    e[0, :] |= sel[0, :]                      # domain border bounds a region too
    e[-1, :] |= sel[-1, :]
    e[:, 0] |= sel[:, 0]
    e[:, -1] |= sel[:, -1]
    return e


def _dash(shape, size=2):
    ys = (np.arange(shape[0]) // size)[:, None]
    xs = (np.arange(shape[1]) // size)[None, :]
    return ((ys + xs) % 2).astype(bool)


def _stroke(img, sel, colour):
    """Dashed pad outline: `colour` alternating with white. A solid stroke in one
    colour is unreadable somewhere on a full-range heatmap -- blue vanishes into
    the dark end, orange into the bright end. Two alternating tones always leave
    half the stroke visible."""
    e = _outline(sel)
    d = _dash(img.shape[:2])
    _paint(img, e & d, colour)
    _paint(img, e & ~d, (255, 255, 255))


def _ramp(t):
    """t in [0,1] -> (..., 3) uint8 along RAMP_STOPS, linear between stops."""
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    xp = np.array([s[0] for s in RAMP_STOPS], dtype=np.float64)
    out = np.empty(t.shape + (3,), dtype=np.uint8)
    for ch in range(3):
        fp = np.array([s[1][ch] for s in RAMP_STOPS], dtype=np.float64)
        out[..., ch] = np.rint(np.interp(t, xp, fp)).astype(np.uint8)
    return out


def _fixture_pads(fx):
    support = np.zeros(fx.shape, dtype=bool)
    for pad in fx.support_pads:
        support |= np.asarray(pad, dtype=bool)
    load = np.asarray(fx.load_pad, dtype=bool)
    return support, load


def _check_shape(arr, fx, what):
    arr = np.asarray(arr)
    if tuple(arr.shape) != tuple(fx.shape):
        raise ValueError("%s has shape %s but the fixture domain is %s"
                         % (what, tuple(arr.shape), tuple(fx.shape)))
    return arr


# --- the four renderers ---------------------------------------------------
def mask_png(mask, fx, path, scale=3, overlay=True):
    """Occupancy mask -> PNG. Material dark, void light.

    With `overlay`, the frozen fixture is drawn on top: the four arm-mount
    support pads in blue and the central payload pad in orange. Those pads come
    from the fixture, never from the candidate, so every image in a run shows
    them in exactly the same place -- which is how a viewer confirms by eye that
    the test did not move between candidates.
    """
    m = _check_shape(mask, fx, "mask").astype(bool)
    img = _void_ground(fx.shape)
    _paint(img, m, MATERIAL)
    if overlay:
        support, load = _fixture_pads(fx)
        _blend(img, support, SUPPORT, PAD_ALPHA)
        _blend(img, load, LOAD, PAD_ALPHA)
    return write_png(path, _present(img, scale))


def energy_png(energy, mask, fx, path, scale=3, vmax=None):
    """Per-element strain energy -> heatmap PNG on the RAMP_STOPS ramp.

    Void cells are painted as background rather than as the ramp's zero: a hole
    is not a lightly loaded piece of plate, and colouring it as one is the single
    easiest way to make a picture like this lie.

    `vmax` sets the top of the scale. Pass the same value for every candidate in
    a run -- comparability between the images matters more than each one filling
    its own dynamic range, and a per-image scale would make a candidate that got
    softer look identical to one that did not. Values above vmax clip to the top
    colour. Colour is log-compressed (see LOG_K) so load paths are legible; it is
    ordered, not proportional.
    """
    e = _check_shape(energy, fx, "energy field").astype(np.float64)
    m = _check_shape(mask, fx, "mask").astype(bool)
    if vmax is None:
        vmax = field_vmax(e, m)
    vmax = float(vmax)
    if not (vmax > 0.0) or not np.isfinite(vmax):
        raise ValueError("energy_png: vmax must be finite and positive, got %r"
                         % vmax)

    t = np.clip(e, 0.0, vmax) / vmax
    t = np.log1p(LOG_K * t) / np.log1p(LOG_K)
    img = _canvas(fx.shape, ENERGY_VOID)
    img[m] = _ramp(t)[m]

    support, load = _fixture_pads(fx)
    _stroke(img, support, SUPPORT)
    _stroke(img, load, LOAD)
    return write_png(path, _present(img, scale))


def field_vmax(energy, mask, quantile=VMAX_QUANTILE):
    """Top of the shared colour scale: a high quantile of the baseline's solid
    cells, not its max. The max sits in the singular corner of a pinned node and
    would compress every real load path into the bottom of the ramp."""
    e = np.asarray(energy, dtype=np.float64)[np.asarray(mask, dtype=bool)]
    if e.size == 0:
        raise ValueError("field_vmax: no solid cells")
    v = float(np.quantile(e, quantile))
    return v if v > 0.0 else float(e.max())


def diff_png(base_mask, cand_mask, fx, path, scale=3):
    """Baseline vs candidate: kept dark grey, removed red, added teal, on the
    void checker. Three colours and no legend text baked into the pixels -- the
    page carries the legend, so the image stays readable at any scale."""
    b = _check_shape(base_mask, fx, "baseline mask").astype(bool)
    c = _check_shape(cand_mask, fx, "candidate mask").astype(bool)
    img = _void_ground(fx.shape)
    _paint(img, b & c, KEPT)
    _paint(img, b & ~c, REMOVED)
    _paint(img, ~b & c, ADDED)
    support, load = _fixture_pads(fx)
    _stroke(img, support, SUPPORT)
    _stroke(img, load, LOAD)
    return write_png(path, _present(img, scale))


# --- run ------------------------------------------------------------------
def _safe(name):
    return "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in str(name))


def _rebuild_fixture(report, artifacts_dir, step_path):
    """Rebuild the exact fixture the report was measured on, and refuse to draw
    anything if it does not hash the same. A picture of a different fixture than
    the numbers were taken on is worse than no picture."""
    grid = report["fixture"]["grid"]
    over = {}
    if int(grid[1]) != fixture_mod.DEFAULTS["nelx"]:
        over["nelx"] = int(grid[1])
    if int(grid[0]) != fixture_mod.DEFAULTS["nely"]:
        over["nely"] = int(grid[0])
    fx = fixture_mod.build(artifacts_dir, step_path, over or None)
    want = report["fixture"]["fixtureHash"]
    if fx.hash() != want:
        raise SystemExit(
            "fixture hash mismatch: the report was measured on %s, rebuilding "
            "here gives %s. render.py will not illustrate one fixture with "
            "another." % (want, fx.hash()))
    return fx


def _rejected_mask(rej, man, fx):
    """A Rejected record carries no MaskRef by design (manifest.py): rejected
    geometry never enters Track's input. Its evidence path is the sanctioned way
    to see what was rejected, and issue #1 requires it stay visible. Loaded here
    to draw, never to solve."""
    if not rej.evidence_path:
        return None
    p = Path(man.base_dir) / rej.evidence_path
    if not p.is_file():
        return None
    if p.suffix == ".npy":
        arr = np.load(str(p), allow_pickle=False)
    else:
        arr = mf.decode_rle(json.loads(p.read_text(encoding="utf-8")))
    arr = np.asarray(arr)
    if tuple(arr.shape) != tuple(fx.shape):
        raise ValueError("rejected candidate %s: evidence mask %s is not the "
                         "fixture domain %s"
                         % (rej.candidate_id, tuple(arr.shape), tuple(fx.shape)))
    return (arr > 0).astype(np.uint8)


def render_run(report_path=".artifacts/track/track-report.json", out_dir=None,
               scale=3, artifacts_dir=DEFAULT_ARTIFACTS, step_path=DEFAULT_STEP,
               quiet=True):
    """Read the report, rebuild the fixture, re-solve every evaluated candidate
    to recover its strain-energy field, and write every PNG plus the evidence
    sheet. Returns the list of paths written, in write order.

    The re-solve is not a convenience: the report stores compliance, not the
    field behind it. Each recomputed compliance is checked against the number the
    report published, so an image that disagrees with the table is a hard error
    here instead of a plausible-looking picture.
    """
    report_path = os.path.abspath(report_path)
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    report_dir = os.path.dirname(report_path)
    default_out = out_dir is None
    out_dir = os.path.abspath(out_dir or os.path.join(report_dir, "evidence"))
    os.makedirs(out_dir, exist_ok=True)

    fx = _rebuild_fixture(report, artifacts_dir, step_path)
    man = mf.load_manifest(os.path.join(report_dir, report["generatedFrom"]))

    results = {r["candidateId"]: r for r in report["results"]}
    base_id = report["baseline"]["candidateId"]

    masks, energies = {}, {}
    for entry in man.all_entries():
        cid = entry.candidate_id
        mask = mf.load_mask(entry, man.base_dir)          # verifies sha256+shape
        m = ev.measure(mask, fx)
        e = m.pop("_energy")
        recorded = results[cid]["measures"]["complianceNmm"]
        got = round(float(m["complianceNmm"]), 9)
        if abs(got - recorded) > max(1e-9, 1e-9 * abs(recorded)):
            raise SystemExit(
                "re-solve of %s gives compliance %.12g but the report published "
                "%.12g. The images and the table would disagree; fix the input, "
                "not this check." % (cid, got, recorded))
        masks[cid], energies[cid] = mask.astype(np.uint8), e
        if not quiet:
            print("re-solved %-24s compliance %.9g" % (cid, got))

    base_mask, base_energy = masks[base_id], energies[base_id]
    vmax = field_vmax(base_energy, base_mask.astype(bool))

    order = [base_id] + [r["candidateId"] for r in report["ranking"]]
    written, figures = [], {}

    for cid in order:
        tag = _safe(cid)
        f = {}
        f["mask"] = mask_png(masks[cid], fx,
                             os.path.join(out_dir, "mask-%s.png" % tag), scale)
        f["energy"] = energy_png(energies[cid], masks[cid], fx,
                                 os.path.join(out_dir, "energy-%s.png" % tag),
                                 scale, vmax=vmax)
        if cid != base_id:
            f["diff"] = diff_png(base_mask, masks[cid], fx,
                                 os.path.join(out_dir, "diff-%s.png" % tag), scale)
        written.extend(f.values())
        figures[cid] = f

    rejected = []
    for rec in report["gate"]["rejected"]:
        cid = rec["candidateId"]
        rej = man.rejection(cid)
        f = {}
        rm = _rejected_mask(rej, man, fx) if rej is not None else None
        if rm is not None:
            tag = _safe(cid)
            f["mask"] = mask_png(rm, fx,
                                 os.path.join(out_dir, "mask-%s.png" % tag), scale)
            f["diff"] = diff_png(base_mask, rm, fx,
                                 os.path.join(out_dir, "diff-%s.png" % tag), scale)
            written.extend(f.values())
        figures[cid] = f
        rejected.append(rec)

    page = build_html(report, fx, figures, order, rejected, vmax)
    index = os.path.join(out_dir, "index.html")
    Path(index).write_text(page, encoding="utf-8")
    written.append(index)
    # Written twice on purpose, same bytes: the sheet belongs next to its PNGs
    # for anyone browsing the evidence directory, and next to track-report.json
    # for anyone following the report. Only on the default layout -- an explicit
    # --out-dir means "put it there", not "there and also in my artifact dir".
    beside = os.path.join(report_dir, "evidence.html")
    if default_out and os.path.abspath(beside) != os.path.abspath(index):
        Path(beside).write_text(page, encoding="utf-8")
        written.append(beside)
    return written


# --- evidence sheet -------------------------------------------------------
CSS = """
:root{color-scheme:light dark;
 --bg:#ffffff;--fg:#14181d;--muted:#5a6472;--line:#dfe4ea;--card:#f7f9fb;
 --code:#eef1f5;--warn-bg:#fdf0ee;--warn-line:#e3b7b1;--warn-fg:#8c2f24;
 --ok-bg:#e9f6f1;--ok-fg:#125c48;--no-bg:#f2f3f5;--no-fg:#5a6472;}
@media (prefers-color-scheme:dark){:root{
 --bg:#111418;--fg:#e6eaef;--muted:#98a2b3;--line:#2a313a;--card:#171b21;
 --code:#1d222a;--warn-bg:#2a1a18;--warn-line:#5e332d;--warn-fg:#f0a99f;
 --ok-bg:#15291f;--ok-fg:#7fd8b6;--no-bg:#1d222a;--no-fg:#98a2b3;}}
*{box-sizing:border-box}
body{margin:0;padding:28px 22px 60px;background:var(--bg);color:var(--fg);
 font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
main{max-width:1100px;margin:0 auto}
h1{font-size:21px;margin:0 0 4px}
h2{font-size:17px;margin:0 0 6px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
 margin:26px 0 10px;font-weight:600}
p{margin:6px 0}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px}
code{background:var(--code);padding:1px 5px;border-radius:4px}
.sub{color:var(--muted);font-size:13px}
.head{border:1px solid var(--line);background:var(--card);border-radius:10px;
 padding:14px 16px;margin:14px 0 8px}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:3px 16px;font-size:13px}
.kv dt{color:var(--muted)}
.kv dd{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.cand{border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:14px 0}
.cand.rejected{background:var(--warn-bg);border-color:var(--warn-line)}
.figs{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin:12px 0 4px}
figure{margin:0}
figure img{display:block;width:100%;height:auto;border:1px solid var(--line);
 border-radius:6px;background:var(--card);image-rendering:pixelated}
figcaption{font-size:12px;color:var(--muted);margin-top:5px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600}
td.num,th.num{text-align:right;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.wrap{overflow-x:auto}
.tag{font-size:11px;letter-spacing:.04em;text-transform:uppercase;padding:2px 8px;
 border-radius:999px;font-weight:600}
.tag.ok{background:var(--ok-bg);color:var(--ok-fg)}
.tag.no{background:var(--no-bg);color:var(--no-fg)}
.tag.rej{background:var(--warn-bg);color:var(--warn-fg);border:1px solid var(--warn-line)}
.rank{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--muted);font-size:13px}
.swatch{display:inline-block;width:11px;height:11px;border-radius:2px;
 border:1px solid rgba(128,128,128,.45);vertical-align:-1px;margin-right:5px}
.legend{display:flex;flex-wrap:wrap;gap:6px 20px;font-size:12px;color:var(--muted);margin:8px 0 0}
.scale{height:12px;border-radius:3px;margin:6px 0 4px}
footer{max-width:1100px;margin:34px auto 0;border-top:1px solid var(--line);padding-top:14px}
footer p{font-size:13px;color:var(--muted)}
"""


def _esc(v):
    return html_mod.escape("" if v is None else str(v), quote=True)


def _img(path, alt, caption):
    b64 = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return ('<figure><img alt="%s" src="data:image/png;base64,%s">'
            '<figcaption>%s</figcaption></figure>'
            % (_esc(alt), b64, caption))


def _sw(rgb):
    return '<span class="swatch" style="background:rgb(%d,%d,%d)"></span>' % rgb


def _ramp_css():
    """The colour scale as a CSS gradient built from the same stops the PNGs use,
    so the key on the page cannot drift from the pixels."""
    stops = ", ".join("rgb(%d,%d,%d) %.0f%%" % (c[0], c[1], c[2], p * 100)
                      for p, c in RAMP_STOPS)
    return "linear-gradient(90deg, %s)" % stops


def _target_tag(res):
    if res.get("meetsTarget") is None:
        return ""
    return ('<span class="tag ok">meets target</span>' if res["meetsTarget"]
            else '<span class="tag no">below target</span>')


def _numbers_table(res, base):
    m, rel = res["measures"], res["relative"]
    rows = [
        ("compliance, both load cases summed", "%.6g N&middot;mm" % m["complianceNmm"]),
        ("compliance vs baseline", "%.4f&times;" % rel["complianceRatioToBaseline"]),
        ("material fraction of domain", "%.4f" % m["materialFractionOfDomain"]),
        ("solid cells", "%d of %d" % (m["solidCells"],
                                      base["measures"]["solidCells"])),
        ("material vs baseline", "%.4f&times;" % rel["materialRatioToBaseline"]),
        ("specific stiffness vs baseline", "<b>%.4f&times;</b>"
         % rel["specificStiffnessRatio"]),
        ("peak nodal displacement", "%.6g mm (%s)"
         % (m["maxDisplacementMm"], _esc(m["maxDisplacementLoadCase"]))),
        ("solver state", "<code>%s</code>" % _esc(m["state"])),
        ("meets displayed target",
         "&mdash;" if res.get("meetsTarget") is None
         else ("yes" if res["meetsTarget"] else "no")),
    ]
    body = "".join("<tr><th>%s</th><td class=\"num\">%s</td></tr>" % r for r in rows)
    return '<div class="wrap"><table>%s</table></div>' % body


def _summary_table(report, order):
    res = {r["candidateId"]: r for r in report["results"]}
    head = ("<tr><th>rank</th><th>candidate</th><th>state</th>"
            "<th class=\"num\">compliance N&middot;mm</th><th class=\"num\">vs base</th>"
            "<th class=\"num\">material frac</th><th class=\"num\">vs base</th>"
            "<th class=\"num\">specific stiffness</th><th>target</th></tr>")
    rows = []
    for i, cid in enumerate(order):
        r = res[cid]
        m, rel = r["measures"], r["relative"]
        rows.append(
            "<tr><td class=\"mono\">%s</td><td><code>%s</code></td><td>%s</td>"
            "<td class=\"num\">%.6g</td><td class=\"num\">%.3f&times;</td>"
            "<td class=\"num\">%.4f</td><td class=\"num\">%.3f&times;</td>"
            "<td class=\"num\"><b>%.3f&times;</b></td><td>%s</td></tr>"
            % ("base" if i == 0 else str(i), _esc(cid), _esc(m["state"]),
               m["complianceNmm"], rel["complianceRatioToBaseline"],
               m["materialFractionOfDomain"], rel["materialRatioToBaseline"],
               rel["specificStiffnessRatio"],
               "&mdash;" if r.get("meetsTarget") is None
               else ("yes" if r["meetsTarget"] else "no")))
    for rec in report["gate"]["rejected"]:
        rows.append(
            "<tr><td class=\"mono\">&mdash;</td><td><code>%s</code></td>"
            "<td colspan=\"7\">rejected by Factory, not evaluated &mdash; "
            "<code>%s</code>, measured %s of %s %s</td></tr>"
            % (_esc(rec["candidateId"]), _esc(rec["reasonCode"]),
               _esc(rec["measured"]), _esc(rec["tolerance"]), _esc(rec["units"])))
    return ('<div class="wrap"><table><thead>%s</thead><tbody>%s</tbody></table></div>'
            % (head, "".join(rows)))


def build_html(report, fx, figures, order, rejected, vmax):
    """One file, no siblings, no network. Every image is a data: URI and the CSS
    is inline, the same rule tools/depgraph/build_viewer.py follows: the judged
    path runs with the ethernet unplugged, and a page that needs a fetch to look
    right fails exactly at the moment the demo is making its point."""
    f = report["fixture"]
    res = {r["candidateId"]: r for r in report["results"]}
    base_id = report["baseline"]["candidateId"]
    base = res[base_id]

    clusters = ", ".join("(%.2f, %.2f)" % (c["x"], c["z"]) for c in f["boltClusters"])
    pad = fx.params["payloadPadMm"]
    support_desc = (
        "%s bolts in %d arm-mount clusters at %s mm; both in-plane DOF held at "
        "every material-backed node within %.1f mm of a cluster centre "
        "(%d fixed DOF)"
        % (f["supportBolts"], len(f["boltClusters"]), clusters,
           fx.params["supportRadiusMm"], f["fixedDofCount"]))
    load_desc = (
        "%.1f N spread over %d material-backed nodes on the payload pad at "
        "(%.2f, %.2f) mm (radius %.1f mm); load cases %s, solved separately and "
        "their compliances summed"
        % (f["loadTotalN"], f["loadedNodeCount"], pad[0], pad[1],
           fx.params["loadRadiusMm"], ", ".join(f["loadCases"])))

    out = ["<!doctype html>", '<html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           "<title>Track evidence &mdash; %s</title>" % _esc(f["fixtureId"]),
           "<style>%s</style></head><body><main>" % CSS]

    out.append("<h1>Track evidence &mdash; %s</h1>" % _esc(f["fixtureId"]))
    out.append('<p class="sub">Run <code>%s</code> &middot; ranking rule: %s</p>'
               % (_esc(report["runId"]), _esc(report["rankingRule"])))
    out.append('<p class="sub">Metric: %s</p>' % _esc(report["metric"]))

    # (label, already-escaped html). Escaping is done at construction rather than
    # sniffed from the value, so a candidate id containing markup cannot leak in.
    out.append('<div class="head"><dl class="kv">')
    for k, v in [
        ("fixture hash", _esc(f["fixtureHash"])),
        ("grid (nely &times; nelx)", "%d &times; %d" % (f["grid"][0], f["grid"][1])),
        ("cell size", "%.4f &times; %.4f mm" % (f["cellSizeMm"][0], f["cellSizeMm"][1])),
        ("plate thickness", "%.3g mm" % f["thicknessMm"]),
        ("material", "%s, E = %.6g MPa, &nu; = %.3g"
         % (_esc(f["materialId"]), f["youngsModulusMPa"], f["poissonRatio"])),
        ("solver", _esc(f["solver"])),
        ("supports", _esc(support_desc)),
        ("load", _esc(load_desc)),
        ("candidate source", "%s, manifest <code>%s</code>"
         % (_esc(report["manifest"]["producedBy"]), _esc(report["generatedFrom"]))),
        ("git sha", _esc(report["host"].get("gitSha") or "(not recorded)")),
        ("displayed target", "material &le; %.2f&times; baseline and compliance "
         "&le; %.2f&times; baseline" % (report["target"]["materialFractionRatioMax"],
                                        report["target"]["complianceRatioMax"])),
    ]:
        out.append("<dt>%s</dt><dd>%s</dd>" % (k, v))
    out.append("</dl>")
    out.append('<p class="sub">%s</p>' % _esc(f["assumptions"]))
    out.append("</div>")

    out.append("<h3>All candidates</h3>")
    out.append(_summary_table(report, order))

    out.append("<h3>How to read the images</h3>")
    out.append(
        '<p class="legend">'
        '<span>%socclusion mask: material</span>'
        '<span>%svoid</span>'
        '<span>%sarm-mount support pads (fixture)</span>'
        '<span>%spayload load pad (fixture)</span>'
        '<span>%sdiff: kept</span><span>%sdiff: removed</span>'
        '<span>%sdiff: added</span></p>'
        % (_sw(MATERIAL), _sw(VOID_A), _sw(SUPPORT), _sw(LOAD),
           _sw(KEPT), _sw(REMOVED), _sw(ADDED)))
    px = max(1, int(round(_scale_of(figures, f))))
    out.append('<div class="scale" style="background:%s"></div>' % _ramp_css())
    out.append(
        '<p class="sub">Strain-energy scale: left is 0, right is %.6g N&middot;mm '
        'per cell and above (the %.1fth percentile of the baseline\'s solid cells; '
        'higher values clip to the top colour). The same value is used for every '
        'candidate so the images compare directly. Colour is log-compressed, '
        't &rarr; log1p(%g&middot;t)/log1p(%g), which makes load paths legible and '
        'makes the scale ordered rather than proportional. Void cells are drawn as '
        'grey background, not as zero energy. Every image is a top view with model '
        '+z up and +x right, one grid cell per %d&times;%d pixel block.</p>'
        % (vmax, VMAX_QUANTILE * 100, LOG_K, LOG_K, px, px))
    # Two artefacts of the fixture that a viewer would otherwise read as physics.
    out.append(
        '<p class="sub">Two things to expect in these fields. The brightest cells '
        'sit at the payload pad because that is where the load is introduced. The '
        'arm mounts read as <i>dark</i> discs because every node inside a support '
        'pad is held in both DOF, and an element whose four nodes are all held '
        'stores no strain energy &mdash; the loaded material is the fan running '
        'out of the payload pad toward each mount, not the mount itself.</p>')

    out.append("<h3>Baseline and survivors, in rank order</h3>")
    for i, cid in enumerate(order):
        r = res[cid]
        fig = figures.get(cid, {})
        rank_label = "baseline" if i == 0 else "rank %d" % i
        out.append('<section class="cand"><h2><span class="rank">%s</span>'
                   "<code>%s</code>%s</h2>" % (rank_label, _esc(cid),
                                               _target_tag(r)))
        if r.get("notes"):
            out.append('<p class="sub">%s</p>' % _esc(r["notes"]))
        if i > 0:
            d = r["removalDiagnosis"]
            out.append('<p class="sub">Removed %.1f%% of baseline mass, which was '
                       "carrying %.1f%% of the baseline strain energy (%s).</p>"
                       % (100 * d["massFractionRemoved"],
                          100 * d["strainEnergyFractionRemoved"], _esc(d["basis"])))
        out.append('<div class="figs">')
        if fig.get("mask"):
            out.append(_img(fig["mask"], "occupancy mask for %s" % cid,
                            "Occupancy mask handed to the solver, with the frozen "
                            "fixture drawn on top."))
        if fig.get("energy"):
            out.append(_img(fig["energy"], "strain-energy field for %s" % cid,
                            "Per-element strain energy, both load cases summed, "
                            "on the shared scale above."))
        if fig.get("diff"):
            out.append(_img(fig["diff"], "diff against baseline for %s" % cid,
                            "Against the baseline: kept, removed, added."))
        out.append("</div>")
        out.append(_numbers_table(r, base))
        out.append("</section>")

    if rejected:
        out.append("<h3>Rejected by Factory &mdash; not evaluated</h3>")
        out.append('<p class="sub">%s. Enforced by %s. These candidates were '
                   "never solved, so they have no compliance and no strain-energy "
                   "field; their geometry is shown from the evidence path recorded "
                   "in the manifest so a veto stays visible instead of "
                   "disappearing.</p>"
                   % (_esc(report["gate"]["rule"]),
                      "<code>%s</code>" % _esc(report["gate"]["enforcedBy"])))
        for rec in rejected:
            cid = rec["candidateId"]
            fig = figures.get(cid, {})
            out.append('<section class="cand rejected"><h2>'
                       '<span class="rank">&mdash;</span><code>%s</code>'
                       '<span class="tag rej">rejected &mdash; not evaluated</span>'
                       "</h2>" % _esc(cid))
            out.append('<div class="wrap"><table>'
                       "<tr><th>reason code</th><td class=\"num\"><code>%s</code></td></tr>"
                       "<tr><th>measured</th><td class=\"num\">%s</td></tr>"
                       "<tr><th>tolerance</th><td class=\"num\">%s</td></tr>"
                       "<tr><th>units</th><td class=\"num\">%s</td></tr>"
                       "<tr><th>implicated</th><td class=\"num\">%s</td></tr>"
                       "</table></div>"
                       % (_esc(rec["reasonCode"]), _esc(rec["measured"]),
                          _esc(rec["tolerance"]), _esc(rec["units"]),
                          _esc(", ".join(rec.get("implicated") or [])) or "&mdash;"))
            if fig:
                out.append('<div class="figs">')
                if fig.get("mask"):
                    out.append(_img(fig["mask"], "occupancy mask for %s" % cid,
                                    "Occupancy mask as submitted, with the frozen "
                                    "fixture drawn on top. Not solved."))
                if fig.get("diff"):
                    out.append(_img(fig["diff"], "diff against baseline for %s" % cid,
                                    "Against the baseline: kept, removed, added."))
                out.append("</div>")
            else:
                out.append('<p class="sub">No evidence mask recorded in the '
                           "manifest for this candidate, so there is no geometry "
                           "to draw.</p>")
            out.append("</section>")

    out.append("</main><footer>")
    out.append("<p><b>Boundary of the claim.</b> %s</p>" % _esc(report["boundary"]))
    out.append('<p class="sub">These images are evidence for the stiffness-proxy '
               "comparison described above. They are not stress plots and carry no "
               "factor of safety or failure criterion.</p>")
    out.append("</footer></body></html>")
    return "\n".join(out) + "\n"


def _scale_of(figures, f):
    """Pixels per grid cell, read back off a written PNG rather than trusted from
    the argument, so the caption cannot describe an image that was not made."""
    for fig in figures.values():
        for p in fig.values():
            return read_png(p).shape[1] / float(f["grid"][1])
    return 1.0


# --- cli ------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", default=".artifacts/track/track-report.json",
                    help="track.report/1 document to illustrate")
    ap.add_argument("--out-dir", default=None,
                    help="where the PNGs and index.html go "
                         "(default: <report dir>/evidence)")
    ap.add_argument("--scale", type=int, default=3,
                    help="pixels per grid cell (default 3)")
    ap.add_argument("--artifacts", default=DEFAULT_ARTIFACTS,
                    help="depgraph artifact directory, for rebuilding the fixture")
    ap.add_argument("--step", default=DEFAULT_STEP)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.scale < 1:
        ap.error("--scale must be >= 1")

    paths = render_run(a.report, a.out_dir, a.scale, a.artifacts, a.step,
                       quiet=a.quiet)
    if not a.quiet:
        for p in paths:
            print("%9d  %s" % (os.path.getsize(p), p))
        print("\n%d files" % len(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
