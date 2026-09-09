#!/usr/bin/env python3
"""
generate_bead_glb.py

Turn a photo of a gemstone/crystal bead into a glTF 2.0 binary (.glb) sphere
mesh, ready to drop into a three.js bracelet-builder scene.

Design notes (why it's built this way):
- No npm / three.js runtime dependency. The sandbox this was built in has no
  package-registry access (npm/pip installs are blocked), and there's no
  guarantee the *next* machine running this skill will have registry access
  either. glTF 2.0 is a fully documented, stable binary format, so this
  script builds the JSON + binary buffer by hand and packs a spec-compliant
  .glb. The only third-party dependency is Pillow (PIL), used purely to
  decode the input photo and sample its color -- everything else (sphere
  geometry, glTF packing) is pure Python stdlib, so this runs anywhere.
- The output is a PBR sphere with a *procedurally generated* pattern
  texture (marble/mottle or banding), not the actual photo projected onto
  a sphere. A flat product photo doesn't unwrap onto a sphere in any way
  that looks good (no matter how you UV-map it, seams and distortion
  show). Instead, the script bakes a small synthetic texture -- blurred
  noise for a mottled/marbled look (quartz-family "flecks"), or sine-wave
  bands for a banded look (rhodochrosite-style growth rings) -- blending
  between the two colors you give it. This gets the "there's a pattern,
  not just a flat color" read right without pretending to reproduce the
  exact real pattern.
- Translucency (`--translucent`) uses KHR_materials_transmission +
  KHR_materials_ior + KHR_materials_volume. These only render correctly
  in a viewer that (a) has GLTFLoader upgrade the material to
  MeshPhysicalMaterial (any reasonably current three.js does this
  automatically) and (b) has *something for the material to transmit* --
  an environment map/background and/or other objects behind it. Drop a
  bead into a bare scene with flat gray nothing behind it and no
  environment map, and transmission will just look like a slightly duller
  opaque material -- that's the viewer/scene missing an environment, not
  the file being wrong. See the bundled `viewer_test.html` template this
  skill can generate for a minimal correct setup.
- `--hole-diameter-mm` drills a real stringing channel. This needs no CSG
  library: a sphere with a cylindrical bore is a surface of revolution with
  a piece removed, so it is built directly -- keep the spherical band whose
  polar angle clears the hole, then close the openings with an inward-facing
  cylinder wall. Both parts are generated at the same radius and height at
  the seam, so the join is exact. UVs keep the undrilled mapping, so the same
  baked textures work on both variants.

Usage:
    python3 generate_bead_glb.py --image photo.jpg --out bead.glb \\
        --name "StrawberryQuartz" --diameter-mm 8 --translucent

    # No photo available yet -- specify the color directly:
    python3 generate_bead_glb.py --color "#f2c9c2" --out bead.glb \\
        --name "StrawberryQuartz" --diameter-mm 8 --translucent
"""

import argparse
import json
import math
import struct
import sys


# ---------------------------------------------------------------------------
# Color extraction
# ---------------------------------------------------------------------------

def extract_average_color(image_path):
    """Return (r, g, b) in 0..255, sampled from the center of the image.

    Center-cropping to the middle ~60% avoids most background/table
    pixels around the bead in a typical product photo, then a heavy
    downsample (LANCZOS to 1x1) acts as a cheap area-average.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "Pillow (PIL) is required to read an image. Install it with "
            "'pip install Pillow', or pass --color '#rrggbb' instead of "
            "--image to skip photo analysis entirely."
        ) from exc

    with Image.open(image_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        cx0, cy0 = int(w * 0.2), int(h * 0.2)
        cx1, cy1 = int(w * 0.8), int(h * 0.8)
        if cx1 <= cx0 or cy1 <= cy0:
            cropped = im
        else:
            cropped = im.crop((cx0, cy0, cx1, cy1))
        tiny = cropped.resize((1, 1), Image.LANCZOS)
        r, g, b = tiny.getpixel((0, 0))
        return (r, g, b)


def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        raise SystemExit(f"--color must look like '#rrggbb', got {hex_color!r}")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def srgb_to_linear(c):
    """c in 0..1 sRGB -> linear, per the glTF spec (baseColorFactor is linear)."""
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def rgb255_to_linear_factor(rgb):
    return [srgb_to_linear(c / 255.0) for c in rgb]


def _value_noise(shape, grid_x, grid_y, rng):
    """One octave of tileable value noise, as a float array in 0..1.

    Tileable matters here: the texture wraps around the sphere's longitude,
    so a non-wrapping noise leaves a visible vertical seam at u=0/1. The
    lattice indices are taken modulo the grid, so the field is periodic by
    construction, and quintic smoothstep interpolation keeps it free of the
    grid-aligned creases bilinear interpolation would leave.

    Separate x/y grid sizes allow anisotropic noise -- a lattice that is
    much finer along one axis than the other produces stretched, directional
    streaks instead of round blobs. That is the difference between a stone
    that looks *fibrous* (charoite, tiger's eye, satin spar) and one that
    looks merely cloudy.
    """
    import numpy as np

    h, w = shape
    lat = rng.random((grid_y, grid_x))

    ys = np.linspace(0, grid_y, h, endpoint=False)
    xs = np.linspace(0, grid_x, w, endpoint=False)
    X, Y = np.meshgrid(xs, ys)

    x0 = np.floor(X).astype(np.int64) % grid_x
    y0 = np.floor(Y).astype(np.int64) % grid_y
    x1 = (x0 + 1) % grid_x
    y1 = (y0 + 1) % grid_y

    fx = X - np.floor(X)
    fy = Y - np.floor(Y)
    u = fx * fx * fx * (fx * (fx * 6 - 15) + 10)
    v = fy * fy * fy * (fy * (fy * 6 - 15) + 10)

    n00, n10 = lat[y0, x0], lat[y0, x1]
    n01, n11 = lat[y1, x0], lat[y1, x1]
    nx0 = n00 * (1 - u) + n10 * u
    nx1 = n01 * (1 - u) + n11 * u
    return nx0 * (1 - v) + nx1 * v


def _fbm(shape, grid, octaves, seed, ridged=False, aniso=1.0):
    """Fractal Brownian motion: octaves of value noise at doubling frequency
    and halving amplitude.

    This is the whole reason natural stone reads as natural. A single octave
    of blurred noise only has ONE feature size, so it looks like soft blobs
    (or, at high frequency, like even speckle) -- never like rock. Real
    mineral texture has structure at every scale at once: big cloudy masses,
    veins inside them, fine mottling inside those. Summing octaves is the
    cheapest way to get that.

    `ridged` folds each octave around its midpoint (1 - |2n-1|), which turns
    smooth blobs into sharp filaments -- the fibrous/veined look of jade,
    serpentine, charoite and tiger's eye.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    total = np.zeros(shape)
    amplitude = 1.0
    norm = 0.0
    g = grid
    for _ in range(octaves):
        # Anisotropy stretches features along ONE axis. More lattice cells on
        # an axis = higher frequency = features narrower along it, so:
        #   aniso > 1  -> extra cells in x -> fibres run vertically (along v)
        #   aniso < 1  -> extra cells in y -> fibres run horizontally (along u)
        # The un-stretched axis always keeps the full base resolution `g`.
        # (Scaling one axis DOWN instead would collide with the minimum-2
        # lattice floor and dissolve the fine detail into coarse blobs.)
        # Clamp: aniso <= 0 would divide the lattice by ~zero and allocate a
        # multi-million-cell grid, hanging the process. Anything outside this
        # range is past the point of visual usefulness anyway.
        a = min(50.0, max(0.02, aniso))
        if a >= 1.0:
            gx, gy = g * a, g
        else:
            gx, gy = g, g / a
        layer = _value_noise(shape, max(2, int(gx)), max(2, int(gy)), rng)
        if ridged:
            layer = 1.0 - np.abs(2.0 * layer - 1.0)
        total += layer * amplitude
        norm += amplitude
        amplitude *= 0.5
        g *= 2
    return total / norm


def _normalize(a):
    import numpy as np
    lo, hi = float(a.min()), float(a.max())
    if hi - lo < 1e-9:
        return np.zeros_like(a)
    return (a - lo) / (hi - lo)


def _voronoi_edges(shape, n_cells, seed, width=0.008):
    """Distance to the nearest CELL BOUNDARY in a Voronoi tessellation,
    returned as bright thin lines (1 on a boundary, 0 away from one).

    This is how you draw fracture networks. Cracks are not noise -- they are
    the *boundaries between regions*, which is exactly what the difference
    between the nearest and second-nearest seed distance measures: that gap
    goes to zero precisely on a cell edge and grows away from it. fBm can
    make something crack-ish and blurry, but only an edge construction gives
    the thin, continuous, branching lines that read as 冰裂 in a crystal.
    """
    import numpy as np

    size = shape[0]
    rng = np.random.default_rng(seed)
    ys, xs = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
    d1 = np.full(shape, np.inf)
    d2 = np.full(shape, np.inf)
    for _ in range(int(n_cells)):
        cy, cx = rng.integers(0, size), rng.integers(0, size)
        dy = np.abs(ys - cy); dy = np.minimum(dy, size - dy)
        dx = np.abs(xs - cx); dx = np.minimum(dx, size - dx)
        d = np.sqrt(dy * dy + dx * dx) / size
        d2 = np.minimum(d2, np.maximum(d1, d))
        d1 = np.minimum(d1, d)
    return np.clip(1.0 - (d2 - d1) / max(1e-6, width), 0.0, 1.0)


def _noise_field(pattern, size=1024, seed=0, scale=8, octaves=6, warp=0.35, ridged=False,
                 contrast=1.0, aniso=1.0, bias=1.0, speck_count=7000.0, speck_size=4.0, speck_cluster=0.6, speck_cluster_size=22.0, speck_aspect=3.0,
                 speck_angles=0, speck_align=0.0, speck_align_spread=0.22,
                 band_centers=0, band_freq=0.0, band_irregularity=0.0,
                 wisp_amount=0.0, crack_amount=0.0, crack_cells=22, crack_width=0.008, crack_coverage=0.3, wisp_sparsity=5.0):
    """Build the grayscale field (PIL 'L' image) that drives colour,
    roughness and normal detail.

    `warp` is domain warping: instead of sampling the noise at (x, y), sample
    it at (x, y) displaced by *another* noise field. This is what turns
    concentric/blobby noise into the swirled, stretched, wispy filaments you
    see in real polished stone -- without it, even good fBm still reads as
    "clouds" rather than "mineral". Because the displacement field is itself
    tileable, the warped result stays tileable.

    `scale` is now the base lattice size of the FIRST octave (small, e.g.
    6-12), not the final feature size -- the octaves supply the fine detail.

    Returns None if pattern == 'none'.
    """
    if pattern == "none":
        return None

    import numpy as np
    from PIL import Image

    shape = (size, size)

    if pattern in ("marble", "fiber"):
        ridge = ridged or pattern == "fiber"
        if warp > 0:
            wx = _fbm(shape, scale, max(3, octaves - 2), seed + 101)
            wy = _fbm(shape, scale, max(3, octaves - 2), seed + 202)
            # Re-sample the base field through the displacement by rolling
            # index grids -- cheap, and stays periodic.
            base = _fbm(shape, scale, octaves, seed, ridged=ridge, aniso=aniso)
            ys, xs = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
            amt = warp * size * 0.35
            sx = (xs + (wx - 0.5) * 2 * amt).astype(np.int64) % size
            sy = (ys + (wy - 0.5) * 2 * amt).astype(np.int64) % size
            field = base[sy, sx]
            # A second, finer pass layers small-scale detail on top of the
            # warped mass so the result has both structure and grain.
            field = field * 0.75 + _fbm(shape, scale * 4, 4, seed + 303,
                                        ridged=ridge, aniso=aniso) * 0.25
        else:
            field = _fbm(shape, scale, octaves, seed, ridged=ridge, aniso=aniso)

    elif pattern == "speckle":
        # Discrete mineral inclusions (strawberry quartz, sunstone, goldstone):
        # a mostly-clear body with separate flecks suspended in it.
        #
        # Neither fBm nor thresholded noise works here. fBm makes connected
        # swirls, and gamma-crushed value noise makes the lattice cells show
        # up as visible squares -- flecks are *objects*, so they get stamped
        # as objects, wrapped at the edges so the texture still tiles.
        #
        # Two things make stamped flecks read as real inclusions rather than
        # as confetti:
        #  1. They CLUSTER. Real inclusions settled onto growth planes, so
        #     they bunch into veils and clouds with genuinely clear quartz
        #     in between -- never an even sprinkle across the whole stone.
        #  2. They are FLAKES, not dots. Hematite/lepidocrocite inclusions
        #     are platelets, so they read as small irregular slivers at
        #     assorted angles, not as a field of identical circles.
        rng = np.random.default_rng(seed + 606)

        count = max(1, int(speck_count * (size / 1024.0) ** 2))
        density = _normalize(_fbm(shape, max(3, scale // 2), 4, seed + 707))
        # Sharpen the density field so there are truly empty zones, not a
        # mild variation on "everywhere".
        density = density ** 2.2

        n_clustered = int(count * speck_cluster)
        n_loose = count - n_clustered

        pys, pxs = [], []
        if n_clustered > 0:
            # Cluster seeds land preferentially where the density field is
            # high; flecks then scatter around each seed with a gaussian
            # spread, which is what produces veil-like clouds of inclusions.
            n_seeds = max(1, int(n_clustered / 45))
            sy = rng.integers(0, size, n_seeds * 6)
            sx = rng.integers(0, size, n_seeds * 6)
            keep = rng.random(sy.size) < density[sy, sx]
            sy, sx = sy[keep][:n_seeds], sx[keep][:n_seeds]
            if sy.size:
                per = int(np.ceil(n_clustered / sy.size))
                sigma = max(4.0, speck_cluster_size)
                cy = np.repeat(sy, per) + rng.normal(0, sigma, sy.size * per)
                cx = np.repeat(sx, per) + rng.normal(0, sigma * rng.uniform(0.7, 1.5), sy.size * per)
                pys.append(cy.astype(np.int64) % size)
                pxs.append(cx.astype(np.int64) % size)
        if n_loose > 0:
            ly = rng.integers(0, size, n_loose * 3)
            lx = rng.integers(0, size, n_loose * 3)
            keep = rng.random(ly.size) < (0.15 + 0.85 * density[ly, lx])
            pys.append(ly[keep][:n_loose])
            pxs.append(lx[keep][:n_loose])

        py = np.concatenate(pys) if pys else np.array([], dtype=np.int64)
        px = np.concatenate(pxs) if pxs else np.array([], dtype=np.int64)

        # Varied radii: a few larger flakes among many small ones.
        radii = np.maximum(1, rng.gamma(1.7, max(0.5, speck_size) / 2.6, py.size).astype(np.int64))
        radii = np.clip(radii, 1, max(2, int(speck_size * 2.5)))
        # Each flake gets an elongation and an orientation, quantised into a
        # small set so stamping stays vectorised per (radius, shape) group.
        aspects = np.array([1.0, 1.5, 2.2, 3.0]) * max(0.34, speck_aspect) / 3.0
        a_idx = rng.integers(0, aspects.size, py.size)

        # Orientation. The quantisation bin count matters a lot for long
        # needles and not at all for dots: with only a handful of global
        # directions, needles all land on the same few angles and the result
        # reads as a wire cage rather than as mineral. Dots are round enough
        # that nobody can tell -- so the default scales with elongation
        # rather than being a fixed number someone has to know to override.
        # Below aspect 10 (flakes and slivers) it stays at 6, which is what
        # every dot-based recipe was tuned against; needles get enough bins
        # to stop forming a lattice.
        if speck_angles and speck_angles > 0:
            n_angles = int(speck_angles)
        elif speck_aspect < 10:
            n_angles = 6
        else:
            n_angles = int(min(40, round(speck_aspect * 0.6)))
        angles = np.linspace(0, math.pi, max(2, n_angles), endpoint=False)

        if speck_align > 0:
            # Rutile (and tourmaline, and actinolite) grows in SHEAVES:
            # locally near-parallel bundles that fan and change direction
            # across the stone, which is why 金发晶 reads as *hair* rather
            # than as scratches. Independently-random angles can never
            # produce that, however many bins you give them.
            #
            # A smooth low-frequency field supplies the local sweep
            # direction, so needles that are near each other are near
            # parallel; `speck_align_spread` is the fan within a bundle, and
            # the unaligned remainder are the stray needles that cross the
            # bundles in every real specimen.
            ang_field = _normalize(_fbm(shape, max(2, scale // 2), 3, seed + 909))
            local = ang_field[py, px] * math.pi * 2.0
            local = local + rng.normal(0.0, max(0.0, speck_align_spread), py.size)
            stray = rng.random(py.size) * math.pi
            follow = rng.random(py.size) < speck_align
            ang_cont = np.where(follow, local, stray) % math.pi
            g_idx = np.clip((ang_cont / math.pi * angles.size).astype(np.int64),
                            0, angles.size - 1)
        else:
            g_idx = rng.integers(0, angles.size, py.size)

        specks = np.zeros(shape)
        for r in np.unique(radii):
            for ai in range(aspects.size):
                for gi in range(angles.size):
                    sel = (radii == r) & (a_idx == ai) & (g_idx == gi)
                    if not sel.any():
                        continue
                    k = int(r)
                    oy, ox = np.meshgrid(np.arange(-k, k + 1), np.arange(-k, k + 1), indexing="ij")
                    ang = angles[gi]
                    xr = ox * math.cos(ang) + oy * math.sin(ang)
                    yr = -ox * math.sin(ang) + oy * math.cos(ang)
                    d = np.sqrt((xr / (k + 0.5)) ** 2 + (yr / max(0.6, (k + 0.5) / aspects[ai])) ** 2)
                    kernel = np.clip(1.0 - d, 0.0, 1.0) ** 0.6
                    ty = (py[sel][:, None, None] + oy[None, :, :]) % size
                    tx = (px[sel][:, None, None] + ox[None, :, :]) % size
                    np.add.at(specks, (ty.ravel(), tx.ravel()),
                              np.broadcast_to(kernel, ty.shape).ravel())

        specks = np.clip(specks, 0.0, 1.0)
        # Gentle body cloudiness so the clear areas aren't dead flat.
        body = _fbm(shape, max(3, scale // 2), 5, seed + 808)
        # Body sits at mid-tone; flecks pull downward, so the colour ramp
        # reads: dark flecks -> base body -> light clear areas.
        field = 0.64 + (body - 0.5) * 0.24 - specks * 0.68

    elif pattern == "ice":
        # High-grade "ice" material (6A rhodochrosite, icy jade): a clean,
        # near-uniform translucent body whose whole character comes from a
        # SMALL number of discrete defects -- a few white wisps and a sparse
        # network of internal fractures -- rather than from overall figuring.
        # Getting this right is mostly about restraint: broad cloudiness is
        # what LOWER grades look like, so the body stays almost plain and the
        # wisps and cracks are what the eye actually lands on.
        body = _fbm(shape, max(2, scale), 5, seed)
        field = 0.52 + (body - 0.5) * 0.22

        if wisp_amount > 0:
            # 白紋: sinuous white filaments. Ridged + anisotropic + warped so
            # they stretch and curve like real veining rather than blotching.
            # Deliberately COARSE (few octaves, lattice no finer than the
            # body): high-grade 白紋 are a few broad soft wisps. Adding fine
            # octaves here turns them into an all-over streaky weave, which
            # reads as brushed fabric rather than as a clean crystal with a
            # couple of veils in it.
            wisp = _fbm(shape, max(2, scale), 4, seed + 31,
                        ridged=True, aniso=max(1.0, aniso if aniso > 1 else 2.0))
            if warp > 0:
                wx = _fbm(shape, max(2, scale), 4, seed + 41)
                wy = _fbm(shape, max(2, scale), 4, seed + 51)
                ys_, xs_ = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
                amt = warp * size * 0.3
                sx = (xs_ + (wx - 0.5) * 2 * amt).astype(np.int64) % size
                sy = (ys_ + (wy - 0.5) * 2 * amt).astype(np.int64) % size
                wisp = wisp[sy, sx]
            # Keep only the strongest ridges so this stays "a few wisps".
            wisp = _normalize(wisp) ** wisp_sparsity
            field = field + wisp * wisp_amount

        if crack_amount > 0:
            crack = _voronoi_edges(shape, crack_cells, seed + 61, crack_width)
            if warp > 0:
                cwx = _fbm(shape, max(2, scale + 3), 4, seed + 71)
                cwy = _fbm(shape, max(2, scale + 3), 4, seed + 81)
                ys_, xs_ = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
                amt = warp * size * 0.10
                sx = (xs_ + (cwx - 0.5) * 2 * amt).astype(np.int64) % size
                sy = (ys_ + (cwy - 0.5) * 2 * amt).astype(np.int64) % size
                crack = crack[sy, sx]
            # Cracks occupy ZONES, not the whole stone. This is the single
            # thing that separates a high grade ("only a few ice cracks") from
            # crackle glaze: an evenly fractured surface always reads as a
            # manufactured craze pattern. Threshold the zone field at an exact
            # area quantile so `crack_coverage` means what it says.
            zraw = _normalize(_fbm(shape, max(2, scale), 4, seed + 91))
            cov = min(max(crack_coverage, 0.01), 1.0)
            thresh = float(np.quantile(zraw, 1.0 - cov))
            zone = np.clip((zraw - thresh) / max(1e-6, (1.0 - thresh) * 0.55), 0.0, 1.0)
            field = field + crack * zone * crack_amount

    elif pattern == "band":
        rng = np.random.default_rng(seed)
        freq = band_freq if band_freq else (4.0 + rng.random() * 3.0)
        phase = rng.random() * math.pi
        # Parallel layering runs along v, which must wrap: a non-integer number
        # of sine cycles across v leaves a visible seam, and that seam becomes
        # visible for real as soon as anyone uses the per-bead UV-offset trick.
        # (Concentric banding is driven by a distance field, which is already
        # periodic, so it only matters here.)
        if not band_centers:
            freq = max(1.0, round(freq))

        if band_centers > 0:
            # Botryoidal (concentric) banding -- rhodochrosite, malachite,
            # most agate "eyes". The layers grew outward from nodule centres,
            # so they read as NESTED closed rings, not parallel stripes
            # running across the stone. Banding a distance field is what
            # produces that: iso-lines of distance-to-centre are exactly the
            # nested contours the mineral actually has.
            ys, xs = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
            # Exponential smooth-minimum rather than a hard min(): a hard
            # nearest-centre test leaves sharp Voronoi creases where two
            # nodules meet, which read as unnatural star/diamond spikes.
            # Smooth-min lets neighbouring nodules merge the way real
            # botryoidal masses grow into each other.
            k = 85.0
            acc = np.zeros(shape)
            for _ in range(int(band_centers)):
                cy, cx = rng.integers(0, size), rng.integers(0, size)
                dy = np.abs(ys - cy); dy = np.minimum(dy, size - dy)
                dx = np.abs(xs - cx); dx = np.minimum(dx, size - dx)
                d = np.sqrt(dy * dy + dx * dx) / size
                acc += np.exp(-k * d)
            potential = -np.log(np.maximum(acc, 1e-12)) / k
        else:
            # Parallel layering (classic agate/onyx banding).
            potential = np.repeat(np.linspace(0.0, 1.0, size, endpoint=False)[:, None], size, axis=1)

        # Push the layers around so they undulate like real mineral growth
        # instead of reading as printed stripes. Too much and they stop
        # reading as layers at all -- keep well below marble warp values.
        potential = potential + (_fbm(shape, scale, octaves, seed + 404) - 0.5) * warp
        # Uneven layer spacing: real banding alternates thick zones with
        # tight clusters of thin lines, which evenly-spaced sine never does.
        # Exactly 2*pi so this term is periodic in `potential` too, for the
        # same wrap reason as the frequency above.
        potential = potential + band_irregularity * np.sin(potential * math.pi * 2 + phase)

        field = 0.5 + 0.5 * np.sin(potential * math.pi * 2 * freq + phase)
        field = field * 0.88 + _fbm(shape, scale * 6, 4, seed + 505) * 0.12

    else:
        raise SystemExit(f"unknown pattern {pattern!r} (use none/marble/band/fiber/speckle)")

    field = _normalize(field)
    if bias != 1.0:
        # Gamma on the field: >1 pushes the surface toward the dark end
        # (less of it reads as light veining), <1 toward the light end.
        # This is the knob for "there's too much white" without having to
        # change the colours themselves.
        field = np.clip(field, 0.0, 1.0) ** bias
    if contrast != 1.0:
        # S-curve about the midpoint: pushes light veins lighter and dark
        # matrix darker without clipping, which is what separates "clearly
        # a vein" from "vaguely a lighter area".
        field = np.clip((field - 0.5) * contrast + 0.5, 0.0, 1.0)
        field = _normalize(field)
    return Image.fromarray((field * 255).astype(np.uint8), mode="L")


def _png_bytes(img):
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_pattern_texture(pattern, color1, color2, size=1024, seed=0, scale=8,
                          noise=None, color3=None):
    """Bake a colour texture from the noise field.

    With `color3` the ramp is three-stop (dark accent -> base -> light):
    real stone almost always has a dark vein/matrix tone as well as a light
    one, and a two-stop ramp between base and highlight can only ever look
    washed-out by comparison.

    Pass a pre-built `noise` (from _noise_field) to reuse the exact same
    field that drives roughness and normals, so a cloudy patch is
    consistently a different colour AND rougher AND slightly displaced --
    that correlation is what reads as one physical feature instead of three
    unrelated effects layered on top of each other.
    """
    if pattern == "none":
        return None
    if noise is None:
        noise = _noise_field(pattern, size=size, seed=seed, scale=scale)

    import numpy as np
    from PIL import Image

    t = np.asarray(noise, dtype=np.float64) / 255.0
    c1 = np.array(color1, dtype=np.float64)
    c2 = np.array(color2, dtype=np.float64)

    if color3 is None:
        rgb = c1[None, None, :] + (c2 - c1)[None, None, :] * t[:, :, None]
    else:
        c3 = np.array(color3, dtype=np.float64)
        pivot = 0.4
        lo = np.clip(t / pivot, 0.0, 1.0)[:, :, None]
        hi = np.clip((t - pivot) / (1.0 - pivot), 0.0, 1.0)[:, :, None]
        dark_to_base = c3[None, None, :] + (c1 - c3)[None, None, :] * lo
        base_to_light = c1[None, None, :] + (c2 - c1)[None, None, :] * hi
        rgb = np.where(t[:, :, None] < pivot, dark_to_base, base_to_light)

    return _png_bytes(Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode="RGB"))


def build_metal_mask(noise, mode, threshold, softness):
    """Mask selecting which end of the pattern field is a METALLIC inclusion.

    Some inclusions are not coloured stone, they are metal or submetallic
    mineral: rutile needles (金发晶), pyrite, hematite platelets, copper in
    goldstone. Painting them into baseColor alone can never make them read
    as metal, because in a PBR renderer "gold" is not a colour -- it is
    metallic=1 plus a coloured specular reflection. A yellow diffuse patch
    inside a transmissive bead just looks like printed ink, and the higher
    the transmission the more washed out it gets.

    `mode` picks the end of the field the inclusions occupy: 'dark' for
    patterns where they pull the field down (speckle does), 'light' where
    they push it up. Smoothstep edges, or the mask aliases into jagged
    metal/dielectric steps along every needle.
    """
    import numpy as np

    t = np.asarray(noise, dtype=np.float64) / 255.0
    s = max(1e-4, softness)
    if mode == "dark":
        m = np.clip((threshold - t) / s, 0.0, 1.0)
    else:
        m = np.clip((t - threshold) / s, 0.0, 1.0)
    return m * m * (3.0 - 2.0 * m)


def build_roughness_texture(rough_min, rough_max, noise,
                            metal_mask=None, metal_roughness=0.3):
    """Bake a metallicRoughness (ORM-style) texture from the shared field:
    G carries roughness (rough_min..rough_max), R is occlusion (unused, 255),
    B is metallic. Cloudier areas get rougher -- soft diffuse patches --
    while clear areas stay glossy. This is what breaks a bead out of the
    "one hard glare dot on a uniformly glassy sphere" look: the specular
    highlight becomes soft and patchy, like a real polished natural stone.

    With `metal_mask`, B goes to 1 on the inclusions and their roughness is
    overridden with `metal_roughness` -- metal needs its own roughness,
    since the stone body's range is tuned for a dielectric surface and would
    leave the metal either mirror-perfect or chalky.
    """
    import numpy as np
    from PIL import Image

    t = np.asarray(noise, dtype=np.float64) / 255.0
    rough = np.clip(rough_min + (rough_max - rough_min) * t, 0.0, 1.0)
    h, w = t.shape
    metal = np.zeros((h, w), dtype=np.float64)
    if metal_mask is not None:
        metal = np.clip(metal_mask, 0.0, 1.0)
        rough = rough * (1.0 - metal) + np.clip(metal_roughness, 0.0, 1.0) * metal
    out = np.zeros((h, w, 3), dtype=np.uint8)
    out[:, :, 0] = 255
    out[:, :, 1] = (rough * 255).astype(np.uint8)
    out[:, :, 2] = (metal * 255).astype(np.uint8)
    return _png_bytes(Image.fromarray(out, mode="RGB"))


def build_transmission_texture(metal_mask):
    """transmissionTexture (R channel, multiplied by transmissionFactor).

    Metal does not transmit light. Without this the needles keep the body's
    transmission and you see straight through them, which is exactly what
    makes them look like ink printed on glass rather than solid crystals
    suspended inside it.
    """
    import numpy as np
    from PIL import Image

    m = np.clip(metal_mask, 0.0, 1.0)
    h, w = m.shape
    out = np.zeros((h, w, 3), dtype=np.uint8)
    out[:, :, 0] = ((1.0 - m) * 255).astype(np.uint8)
    return _png_bytes(Image.fromarray(out, mode="RGB"))


def build_normal_texture(size=1024, seed=1, scale=10, strength=0.25, octaves=6,
                         noise=None):
    """Bake a tangent-space normal map from a height field.

    Derived from fBm (optionally the same field as the colour, so bumps line
    up with veins) so the micro-relief has detail at several scales, like a
    polished-but-not-perfect stone surface. Gradients are taken with wrap so
    the map tiles seamlessly around the sphere.
    """
    import numpy as np
    from PIL import Image

    if noise is None:
        height = _fbm((size, size), scale, octaves, seed)
    else:
        height = np.asarray(noise, dtype=np.float64) / 255.0

    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * strength * height.shape[1] / 256.0
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * strength * height.shape[0] / 256.0

    nx, ny, nz = -dx, -dy, np.ones_like(height)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / length, ny / length, nz / length

    out = np.stack([(nx * 0.5 + 0.5), (ny * 0.5 + 0.5), (nz * 0.5 + 0.5)], axis=-1)
    return _png_bytes(Image.fromarray((out * 255).astype(np.uint8), mode="RGB"))


def lighten(rgb, amount=0.55):
    """Blend rgb toward white by `amount` (0..1) -- a cheap secondary tone
    for the pattern texture when the user doesn't specify --pattern-color2."""
    return tuple(int(c + (255 - c) * amount) for c in rgb)


def guess_finish_from_color(rgb):
    """Cheap heuristic: brighter/more saturated -> glossier polished look.

    Returns (roughness, metallic). Gemstone beads are never metallic;
    metallic is always 0 here, kept as a parameter for clarity/override.
    """
    r, g, b = [c / 255.0 for c in rgb]
    brightness = (r + g + b) / 3.0
    mx, mn = max(r, g, b), min(r, g, b)
    saturation = 0.0 if mx == 0 else (mx - mn) / mx
    # Polished stones: roughly 0.12 (very glossy) to 0.35 (softer sheen).
    roughness = max(0.12, min(0.35, 0.4 - 0.2 * brightness - 0.1 * saturation))
    return round(roughness, 3), 0.0


# ---------------------------------------------------------------------------
# Sphere geometry (pure Python, mirrors three.js SphereGeometry's layout)
# ---------------------------------------------------------------------------

def build_uv_sphere(radius, width_segments=64, height_segments=32):
    positions = []
    normals = []
    uvs = []
    indices = []

    grid = []
    for iy in range(height_segments + 1):
        row = []
        v = iy / height_segments
        phi = v * math.pi
        for ix in range(width_segments + 1):
            u = ix / width_segments
            theta = u * math.pi * 2

            x = -radius * math.cos(theta) * math.sin(phi)
            y = radius * math.cos(phi)
            z = radius * math.sin(theta) * math.sin(phi)

            positions.extend([x, y, z])
            length = math.sqrt(x * x + y * y + z * z) or 1.0
            normals.extend([x / length, y / length, z / length])
            uvs.extend([u, 1 - v])

            row.append(len(positions) // 3 - 1)
        grid.append(row)

    for iy in range(height_segments):
        for ix in range(width_segments):
            a = grid[iy][ix + 1]
            b = grid[iy][ix]
            c = grid[iy + 1][ix]
            d = grid[iy + 1][ix + 1]
            if iy != 0:
                indices.extend([a, b, d])
            if iy != height_segments - 1:
                indices.extend([b, c, d])

    return positions, normals, uvs, indices


def build_drilled_sphere(radius, hole_radius, width_segments=96, height_segments=48,
                         bore_rings=3):
    """A bead with a real drill channel through it, built parametrically.

    No CSG required. A sphere with a cylindrical bore is not a general boolean
    problem -- it is just a surface of revolution with a piece removed, so it
    can be constructed directly: keep the spherical band whose polar angle
    clears the hole (phi from phi0 to pi-phi0, where sin(phi0) = r/R), then
    close the two openings with an inward-facing cylinder wall. The band's
    edge rings and the bore's end rings are generated at the same radius and
    height, so the seam is exact rather than approximately stitched.

    UVs keep the SAME mapping as the undrilled sphere (v = 1 - phi/pi), so the
    identical baked textures work on both variants -- the drilled bead simply
    stops short of the texture's pole regions.
    """
    positions, normals, uvs, indices = [], [], [], []
    hole_radius = max(1e-4, min(hole_radius, radius * 0.9))
    phi0 = math.asin(hole_radius / radius)
    r_ring = radius * math.sin(phi0)   # == hole_radius, by construction
    y_top = radius * math.cos(phi0)

    # --- spherical band (outward facing) ---
    grid = []
    for iy in range(height_segments + 1):
        row = []
        phi = phi0 + (math.pi - 2 * phi0) * iy / height_segments
        for ix in range(width_segments + 1):
            u = ix / width_segments
            theta = u * math.pi * 2
            x = -radius * math.cos(theta) * math.sin(phi)
            y = radius * math.cos(phi)
            z = radius * math.sin(theta) * math.sin(phi)
            positions.extend([x, y, z])
            length = math.sqrt(x * x + y * y + z * z) or 1.0
            normals.extend([x / length, y / length, z / length])
            uvs.extend([u, 1 - phi / math.pi])
            row.append(len(positions) // 3 - 1)
        grid.append(row)

    for iy in range(height_segments):
        for ix in range(width_segments):
            a, b = grid[iy][ix + 1], grid[iy][ix]
            c, d = grid[iy + 1][ix], grid[iy + 1][ix + 1]
            indices.extend([a, b, d, b, c, d])

    # --- bore wall (inward facing: normals point at the axis, winding flipped) ---
    v_top = 1 - phi0 / math.pi
    v_bot = phi0 / math.pi
    bgrid = []
    for iy in range(bore_rings + 1):
        row = []
        t = iy / bore_rings
        y = y_top + (-y_top - y_top) * t
        for ix in range(width_segments + 1):
            u = ix / width_segments
            theta = u * math.pi * 2
            x = -r_ring * math.cos(theta)
            z = r_ring * math.sin(theta)
            positions.extend([x, y, z])
            normals.extend([math.cos(theta), 0.0, -math.sin(theta)])
            uvs.extend([u, v_top + (v_bot - v_top) * t])
            row.append(len(positions) // 3 - 1)
        bgrid.append(row)

    for iy in range(bore_rings):
        for ix in range(width_segments):
            a, b = bgrid[iy][ix + 1], bgrid[iy][ix]
            c, d = bgrid[iy + 1][ix], bgrid[iy + 1][ix + 1]
            indices.extend([a, d, b, b, d, c])

    return positions, normals, uvs, indices


# ---------------------------------------------------------------------------
# Minimal glTF 2.0 / GLB writer
# ---------------------------------------------------------------------------

def pad_to_4(data, pad_byte):
    remainder = len(data) % 4
    if remainder:
        data += pad_byte * (4 - remainder)
    return data


def build_glb(positions, normals, uvs, indices, base_color_linear, roughness,
              metallic, mesh_name, transmission=None, ior=None, thickness=None,
              texture_png=None, roughness_texture_png=None, normal_texture_png=None,
              attenuation_color_linear=None, attenuation_distance=None,
              tangents=None, anisotropy=None, anisotropy_rotation=0.0,
              transmission_texture_png=None):
    # --- binary buffer: positions, normals, uvs, indices, each 4-byte aligned ---
    pos_bytes = struct.pack(f"<{len(positions)}f", *positions)
    norm_bytes = struct.pack(f"<{len(normals)}f", *normals)
    uv_bytes = struct.pack(f"<{len(uvs)}f", *uvs)
    idx_bytes = struct.pack(f"<{len(indices)}I", *indices)

    buffer_parts = []
    buffer_views = []
    offset = 0

    def add_view(data, target):
        nonlocal offset
        data = pad_to_4(data, b"\x00")
        view = {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(data),
        }
        if target is not None:
            view["target"] = target
        buffer_views.append(view)
        buffer_parts.append(data)
        offset += len(data)
        return len(buffer_views) - 1

    ARRAY_BUFFER = 34962
    ELEMENT_ARRAY_BUFFER = 34963

    pos_view = add_view(pos_bytes, ARRAY_BUFFER)
    norm_view = add_view(norm_bytes, ARRAY_BUFFER)
    uv_view = add_view(uv_bytes, ARRAY_BUFFER)
    idx_view = add_view(idx_bytes, ELEMENT_ARRAY_BUFFER)
    tan_view = add_view(struct.pack(f"<{len(tangents)}f", *tangents), ARRAY_BUFFER) if tangents else None

    n_verts = len(positions) // 3
    xs, ys, zs = positions[0::3], positions[1::3], positions[2::3]

    accessors = [
        {
            "bufferView": pos_view, "componentType": 5126, "count": n_verts,
            "type": "VEC3",
            "min": [min(xs), min(ys), min(zs)],
            "max": [max(xs), max(ys), max(zs)],
        },
        {"bufferView": norm_view, "componentType": 5126, "count": n_verts, "type": "VEC3"},
        {"bufferView": uv_view, "componentType": 5126, "count": n_verts, "type": "VEC2"},
        {"bufferView": idx_view, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
    ]
    tangent_accessor = None
    if tan_view is not None:
        accessors.append({"bufferView": tan_view, "componentType": 5126,
                          "count": n_verts, "type": "VEC4"})
        tangent_accessor = len(accessors) - 1

    # glTF constrains these to 0..1; writing anything else produces a file
    # that validators reject and renderers interpret inconsistently.
    roughness = min(1.0, max(0.0, roughness))
    metallic = min(1.0, max(0.0, metallic))
    if transmission is not None:
        transmission = min(1.0, max(0.0, transmission))
    if anisotropy is not None:
        anisotropy = min(1.0, max(0.0, anisotropy))
    if ior is not None:
        ior = max(1.0, ior)

    material = {
        "name": mesh_name,
        "pbrMetallicRoughness": {
            # With a pattern texture, let the texture carry the color
            # variation and keep the factor neutral (texture x factor = texture).
            "baseColorFactor": [1.0, 1.0, 1.0, 1.0] if texture_png else
                               [round(c, 4) for c in base_color_linear] + [1.0],
            "roughnessFactor": roughness,
            "metallicFactor": metallic,
        },
        "doubleSided": False,
    }

    images, textures, samplers = [], [], []
    samplers.append({"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497})

    def add_texture(png_bytes):
        idx = len(images)
        bv = add_view(png_bytes, None)
        images.append({"bufferView": bv, "mimeType": "image/png"})
        textures.append({"sampler": 0, "source": idx})
        return idx

    if texture_png:
        tex_idx = add_texture(texture_png)
        material["pbrMetallicRoughness"]["baseColorTexture"] = {"index": tex_idx, "texCoord": 0}
    if roughness_texture_png:
        tex_idx = add_texture(roughness_texture_png)
        material["pbrMetallicRoughness"]["metallicRoughnessTexture"] = {"index": tex_idx, "texCoord": 0}
    if normal_texture_png:
        tex_idx = add_texture(normal_texture_png)
        material["normalTexture"] = {"index": tex_idx, "texCoord": 0}

    extensions_used = []
    if transmission is not None:
        transmission_ext = {"transmissionFactor": transmission}
        if transmission_texture_png:
            tex_idx = add_texture(transmission_texture_png)
            transmission_ext["transmissionTexture"] = {"index": tex_idx, "texCoord": 0}
        material.setdefault("extensions", {})["KHR_materials_transmission"] = transmission_ext
        extensions_used.append("KHR_materials_transmission")
    if ior is not None:
        material.setdefault("extensions", {})["KHR_materials_ior"] = {"ior": ior}
        extensions_used.append("KHR_materials_ior")
    if thickness is not None:
        # KHR_materials_volume: thicknessFactor has minimum 0 and
        # attenuationDistance is exclusiveMinimum 0 -- a zero distance is a
        # divide-by-zero in the renderer's volume math, not just an odd look.
        thickness = max(0.0, thickness)
        if attenuation_distance is None:
            attenuation_distance = thickness * 2
        attenuation_distance = max(1e-4, attenuation_distance)
        volume_ext = {
            "thicknessFactor": thickness,
            "attenuationDistance": attenuation_distance,
        }
        if attenuation_color_linear is not None:
            volume_ext["attenuationColor"] = [round(c, 4) for c in attenuation_color_linear]
        material.setdefault("extensions", {})["KHR_materials_volume"] = volume_ext
        extensions_used.append("KHR_materials_volume")
    if anisotropy:
        material.setdefault("extensions", {})["KHR_materials_anisotropy"] = {
            "anisotropyStrength": anisotropy,
            "anisotropyRotation": anisotropy_rotation,
        }
        extensions_used.append("KHR_materials_anisotropy")

    gltf = {
        "asset": {"version": "2.0", "generator": "gem-bead-to-glb (hand-rolled glTF writer)"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": mesh_name}],
        "meshes": [{
            "name": mesh_name,
            "primitives": [{
                "attributes": ({"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}
                               if tangent_accessor is None else
                               {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2,
                                "TANGENT": tangent_accessor}),
                "indices": 3,
                "material": 0,
                "mode": 4,
            }],
        }],
        "materials": [material],
        "buffers": [{"byteLength": offset}],
        "bufferViews": buffer_views,
        "accessors": accessors,
    }
    if images:
        gltf["images"] = images
        gltf["textures"] = textures
        gltf["samplers"] = samplers
    if extensions_used:
        gltf["extensionsUsed"] = sorted(set(extensions_used))

    bin_chunk = b"".join(buffer_parts)
    json_chunk = pad_to_4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")

    def chunk(chunk_type, data):
        return struct.pack("<II", len(data), chunk_type) + data

    JSON_CHUNK_TYPE = 0x4E4F534A  # 'JSON'
    BIN_CHUNK_TYPE = 0x004E4942   # 'BIN\0'

    body = chunk(JSON_CHUNK_TYPE, json_chunk) + chunk(BIN_CHUNK_TYPE, bin_chunk)
    header = struct.pack("<III", 0x46546C67, 2, 12 + len(body))  # 'glTF', version 2
    return header + body


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", help="Path to a photo of the bead/gemstone")
    parser.add_argument("--color", help="Hex color '#rrggbb' to use instead of analyzing --image")
    parser.add_argument("--out", required=True, help="Output .glb path")
    parser.add_argument("--name", default="Bead", help="Name baked into the node/mesh/material")
    parser.add_argument("--diameter-mm", type=float, default=8.0, help="Bead diameter in millimeters (default 8mm, a common bracelet bead size)")
    parser.add_argument("--roughness", type=float, default=None, help="Override the auto-guessed roughness (0=mirror, 1=fully matte)")
    parser.add_argument("--translucent", action="store_true", help="Add KHR_materials_transmission/ior/volume for a crystal-like translucent look")
    parser.add_argument("--ior", type=float, default=1.54, help="Index of refraction for translucent materials (1.54 ~ quartz-family minerals)")
    parser.add_argument("--pattern", choices=["none", "marble", "band", "fiber", "speckle", "ice"], default="none",
                         help="Bake a procedural pattern texture instead of a flat color: "
                              "'marble' for cloudy/mottled stones, 'band' for growth-ring banding, "
                              "'fiber' for ridged filament/vein structure (jade, serpentine, charoite, tiger's eye), "
                              "'speckle' for discrete suspended inclusions in a clear body (strawberry quartz, sunstone)")
    parser.add_argument("--pattern-aniso", type=float, default=1.0, help="Stretch the noise along one axis. 1 = isotropic. >1 (3-6) elongates along v so fibres run pole-to-pole. <1 (e.g. 0.15) elongates along u so fibres ring the bead perpendicular to the drill hole -- what banded fibrous stones need, since pole-to-pole fibres pinch together at the hole")
    parser.add_argument("--pattern-bias", type=float, default=1.0, help="Gamma on the pattern field. >1 = less of the surface reads as the LIGHT tone (use when there is too much white), <1 = more. The fix for 'the white patches look wrong' before touching colours")
    parser.add_argument("--speck-aspect", type=float, default=3.0, help="--pattern speckle: maximum elongation of the flakes. ~3 = mixed flakes/dots. 4-6 makes them short fibrous slivers, which is what densely included quartz (草莓晶) looks like up close -- packed slivers read as felted mineral wool, packed dots read as printed spots")
    parser.add_argument("--speck-cluster", type=float, default=0.6, help="--pattern speckle: fraction of flecks that bunch into veils/clouds rather than scattering evenly (0 = even sprinkle, which always looks like confetti; 0.6-0.85 = natural inclusion veils with genuinely clear quartz between them)")
    parser.add_argument("--speck-cluster-size", type=float, default=22.0, help="--pattern speckle: spread of each inclusion cloud in texture px. Larger = broader, softer veils; smaller = tight dense knots")
    parser.add_argument("--wisp-amount", type=float, default=0.0, help="--pattern ice: strength of the sparse white filaments (白紋). 0.15-0.35 for a high grade with only a few wisps; higher starts looking like a lower, cloudier grade")
    parser.add_argument("--wisp-sparsity", type=float, default=5.0, help="--pattern ice: how much of the wisp field survives. Higher = fewer, more isolated wisps in an otherwise clean body; lower = more veiling")
    parser.add_argument("--crack-amount", type=float, default=0.0, help="--pattern ice: strength of the internal fracture network (冰裂). 0.2-0.4 reads as a few catching-the-light cracks in an otherwise clean crystal")
    parser.add_argument("--crack-cells", type=int, default=22, help="--pattern ice: number of Voronoi cells -- more cells = finer, denser crack net. Keep low (15-30) for a high grade; a dense net reads as crackle glaze")
    parser.add_argument("--crack-coverage", type=float, default=0.3, help="--pattern ice: fraction of the surface that has any cracking at all (0.2-0.35 for a high grade). Cracks confined to a few zones is what 'only a few ice cracks' actually looks like; spread them everywhere and it stops looking like a crystal")
    parser.add_argument("--crack-width", type=float, default=0.008, help="--pattern ice: crack line thickness. Keep small (0.004-0.012); thick cracks read as crackle glaze, not as fractures inside a crystal")
    parser.add_argument("--band-centers", type=int, default=0, help="--pattern band: 0 = parallel layers (agate/onyx). 1-5 = CONCENTRIC layers nested around that many growth centres -- the botryoidal structure of rhodochrosite, malachite and agate eyes. Concentric is what most people picture when they say a stone is 'banded'")
    parser.add_argument("--band-freq", type=float, default=0.0, help="--pattern band: number of layers across the texture (0 = pick randomly). Lower = broader, chunkier layers")
    parser.add_argument("--band-irregularity", type=float, default=0.0, help="--pattern band: alternates thick zones with tight clusters of thin lines (0.1-0.3). Evenly spaced bands are the giveaway of a fake-looking banded stone")
    parser.add_argument("--speck-count", type=float, default=7000.0, help="--pattern speckle: how many flecks to scatter (measured at 1024px texture; auto-scaled for other sizes). Higher = busier/denser inclusions")
    parser.add_argument("--speck-size", type=float, default=4.0, help="--pattern speckle: approximate fleck diameter in texture pixels. HIGHER = bigger, more clearly individual inclusions; LOWER (2-3) = fine grain that reads as noise rather than flecks. Scale it with --texture-size")
    parser.add_argument("--pattern-color2", help="Light hex tone for the pattern (default: --color lightened toward white)")
    parser.add_argument("--pattern-color3", help="Dark accent hex tone (veins/matrix). Adding this is the single easiest way to stop a texture looking washed out -- real stone has a dark tone as well as a light one")
    parser.add_argument("--pattern-scale", type=int, default=8, help="Base lattice size of the FIRST fBm octave -- small (6-12) since later octaves add the fine detail. Lower = larger overall masses, higher = busier")
    parser.add_argument("--octaves", type=int, default=6, help="fBm octaves. More = more fine detail layered inside the big shapes (6-8 looks like real stone; 1-2 looks like flat blobs)")
    parser.add_argument("--warp", type=float, default=0.35, help="Domain-warp strength: displaces the noise by another noise field, turning round blobs into stretched, swirled, wispy filaments. 0 = no warp (cloudy), 0.3-0.6 = natural stone swirl")
    parser.add_argument("--pattern-contrast", type=float, default=1.0, help="S-curve contrast on the pattern field (>1 separates dark matrix from light veins more strongly; 1.5-2.5 for boldly figured stone, 1.0 for soft)")
    parser.add_argument("--ridged", action="store_true", help="Fold each fBm octave to create sharp filaments/veins instead of soft blobs (implied by --pattern fiber)")
    parser.add_argument("--texture-size", type=int, default=1024, help="Pattern texture resolution (square). 1024 is a good default for a bead viewed large; 512 halves file size with little visible loss at small sizes; 2048 for hero shots")
    parser.add_argument("--seed", type=int, default=0, help="Pattern RNG seed -- change this to get a different mottle/band layout for the same colors")
    parser.add_argument("--transmission", type=float, default=None, help="Override transmission factor when --translucent (0..1, default 0.55 -- push toward 0.85-0.95 for a genuinely glassy/watery crystal instead of a slightly-dull look)")
    parser.add_argument("--attenuation-color", help="Hex color light picks up passing through the stone (KHR_materials_volume) -- defaults to a paled version of --color. This is what gives depth/coolness to translucent stones instead of looking uniformly flat")
    parser.add_argument("--attenuation-distance-mm", type=float, default=None, help="Distance (mm) over which attenuation-color saturates -- smaller = more visible color falloff/depth BUT also darker/murkier, larger = clearer and brighter. If a translucent bead looks too dark, raise this first. Default: diameter")
    parser.add_argument("--thickness-mm", type=float, default=None, help="KHR_materials_volume thickness (default: diameter). Lower values = less light absorbed inside the stone = brighter, airier crystal; raise for a denser, deeper stone")
    parser.add_argument("--anisotropy", type=float, default=0.0, help="Chatoyancy / cat-eye sheen via KHR_materials_anisotropy (0 = off, 0.6-0.9 for tiger's eye, satin spar, fibrous jade). Stretches the specular highlight along the fibre direction instead of leaving a round dot. Emits TANGENT vectors automatically, which the extension requires")
    parser.add_argument("--speck-angles", type=int, default=0,
                        help="How many distinct orientations the flecks can take. 0 = auto (6 for flakes, scaling to 40 for long needles), which is almost always right. Only set it by hand to deliberately flatten or exaggerate the directional variety")
    parser.add_argument("--speck-align", type=float, default=0.0,
                        help="0..1 -- fraction of flecks that follow a local sweep direction instead of pointing randomly. Rutile, tourmaline and actinolite grow in near-parallel SHEAVES, which is what makes 金发晶 read as hair rather than scratches. 0.75-0.9 with the remainder left as stray crossing needles")
    parser.add_argument("--speck-align-spread", type=float, default=0.22,
                        help="Angular fan within one sheaf, in radians. 0.1 = tight silky bundle, 0.35 = loose spray")
    parser.add_argument("--metallic-inclusions", choices=["none", "dark", "light"], default="none",
                        help="Make the inclusions actual METAL (rutile needles in 金发晶, pyrite, hematite, goldstone) instead of coloured stone. 'dark' when the inclusions are the dark end of the pattern (speckle puts them there), 'light' when they are the light end. Bakes metallic=1 and transmission=0 over them, which is what makes gold read as gold instead of as yellow ink")
    parser.add_argument("--metallic-threshold", type=float, default=0.35,
                        help="Pattern-field cutoff for --metallic-inclusions (0..1). Lower with 'dark' = only the needle cores are metal; raise to include their soft edges")
    parser.add_argument("--metallic-softness", type=float, default=0.10,
                        help="Width of the metal/stone transition. Too small and every needle edge aliases into a jagged step")
    parser.add_argument("--metallic-roughness", type=float, default=0.3,
                        help="Roughness of the metallic inclusions only (0.2-0.35 for bright rutile, 0.45+ for dull pyrite). The stone body keeps --roughness-min/--roughness-max")
    parser.add_argument("--anisotropy-rotation", type=float, default=0.0, help="Rotation of the anisotropy direction in radians. 0 = along the u (longitude) tangent. If the sheen runs the wrong way in your viewer, pass 1.5708 (pi/2) to flip it")
    parser.add_argument("--hole-diameter-mm", type=float, default=0.0, help="Drill a real stringing channel of this diameter through the bead (0 = solid sphere). Bracelet beads are typically 1.0-1.5mm on an 8mm bead. The hole is built parametrically, not boolean-cut, and reuses the same textures as the solid version")
    parser.add_argument("--segments", type=int, default=64, help="Sphere longitude segments (latitude = half this). Default 64x32 (~4k tris) reads as a smooth bead at typical configurator sizes. Drop to 32 for very low-poly/many-bead scenes; raise to 96-128 if beads are shown large or close-up and you can see facets on the silhouette")
    parser.add_argument("--frosted", action="store_true", help="Add a roughness-variation texture (glossy where clear, rougher where the pattern is 'cloudy') plus a subtle normal-map bump -- this is what breaks up a single hard pinpoint specular highlight into the soft, patchy glints of a real polished-but-natural stone instead of a 'shiny candy ball' look. Only makes sense combined with --pattern marble/band")
    parser.add_argument("--roughness-min", type=float, default=0.03, help="--frosted: roughness at the clearest/glossiest patches")
    parser.add_argument("--roughness-max", type=float, default=0.28, help="--frosted: roughness at the cloudiest/mistiest patches")
    parser.add_argument("--normal-strength", type=float, default=0.25, help="--frosted: how strong the subtle surface bump is (0 = perfectly smooth sphere, higher = more visible ice-crack/cotton-wisp irregularity). Keep this small -- it's meant to be felt, not seen")
    parser.add_argument("--normal-scale", type=int, default=10, help="--frosted: normal-map fBm base lattice -- independent of --pattern-scale so surface micro-relief can be finer than the big colour masses")
    parser.add_argument("--normal-follows-pattern", action="store_true", help="--frosted: derive the normal map from the SAME field as the colour, so bumps line up with the veins (a vein you can see is also a vein you can feel). Otherwise the relief is independent fine grain")
    args = parser.parse_args()

    if not args.image and not args.color:
        parser.error("pass either --image PATH or --color '#rrggbb'")
    if args.diameter_mm <= 0:
        parser.error("--diameter-mm must be positive")
    if args.hole_diameter_mm < 0:
        parser.error("--hole-diameter-mm cannot be negative")
    if args.hole_diameter_mm >= args.diameter_mm:
        parser.error("--hole-diameter-mm must be smaller than --diameter-mm")
    if args.octaves < 1:
        parser.error("--octaves must be at least 1")
    if args.texture_size < 8:
        parser.error("--texture-size must be at least 8")
    if args.crack_cells < 1:
        parser.error("--crack-cells must be at least 1 (use --crack-amount 0 for no cracks)")
    if args.thickness_mm is not None and args.thickness_mm < 0:
        parser.error("--thickness-mm cannot be negative")
    if args.attenuation_distance_mm is not None and args.attenuation_distance_mm <= 0:
        parser.error("--attenuation-distance-mm must be positive")
    if args.speck_angles and 0 < args.speck_angles < 2:
        parser.error("--speck-angles must be at least 2 (or 0 for auto)")
    # Octaves past the texture's Nyquist limit add no visible detail and cost
    # quadratic memory -- octaves 20 at 128px tries to allocate 8 GB.
    max_octaves = max(1, int(math.log2(args.texture_size)) - 1)
    if args.octaves > max_octaves:
        print(f"note: --octaves {args.octaves} exceeds what {args.texture_size}px can show; "
              f"using {max_octaves}", file=sys.stderr)
        args.octaves = max_octaves
    if args.metallic_inclusions != "none" and args.roughness is not None and args.roughness < 1.0:
        print(f"warning: --roughness {args.roughness} multiplies the baked roughness map, so "
              f"--metallic-roughness {args.metallic_roughness} will actually render as "
              f"{args.roughness * args.metallic_roughness:.3f}. Pass --roughness 1.0 unless "
              f"you mean this.", file=sys.stderr)
    if args.metallic_inclusions != "none":
        if not 0.0 <= args.metallic_threshold <= 1.0:
            parser.error("--metallic-threshold must be between 0 and 1")
        if args.metallic_softness <= 0:
            parser.error("--metallic-softness must be positive")
        if not 0.0 <= args.metallic_roughness <= 1.0:
            parser.error("--metallic-roughness must be between 0 and 1")
        if args.pattern == "none":
            parser.error("--metallic-inclusions needs a pattern to mark the inclusions (not --pattern none)")

    if args.color:
        rgb = hex_to_rgb(args.color)
    else:
        rgb = extract_average_color(args.image)

    auto_roughness, metallic = guess_finish_from_color(rgb)
    roughness = args.roughness if args.roughness is not None else auto_roughness
    base_color_linear = rgb255_to_linear_factor(rgb)

    radius_mm = args.diameter_mm / 2.0
    seg_w = max(8, args.segments)
    if args.hole_diameter_mm > 0:
        positions, normals, uvs, indices = build_drilled_sphere(
            radius_mm, args.hole_diameter_mm / 2.0,
            width_segments=seg_w, height_segments=max(4, seg_w // 2))
    else:
        positions, normals, uvs, indices = build_uv_sphere(radius_mm, width_segments=seg_w,
                                                            height_segments=max(4, seg_w // 2))

    transmission = ior = thickness = None
    attenuation_color_linear = attenuation_distance = None
    if args.translucent:
        transmission = args.transmission if args.transmission is not None else 0.55
        ior = args.ior
        thickness = args.thickness_mm if args.thickness_mm is not None else args.diameter_mm
        atten_rgb = hex_to_rgb(args.attenuation_color) if args.attenuation_color else lighten(rgb, amount=0.35)
        attenuation_color_linear = rgb255_to_linear_factor(atten_rgb)
        attenuation_distance = args.attenuation_distance_mm if args.attenuation_distance_mm is not None else args.diameter_mm

    texture_png = roughness_texture_png = normal_texture_png = None
    transmission_texture_png = None
    if args.pattern != "none":
        color2 = hex_to_rgb(args.pattern_color2) if args.pattern_color2 else lighten(rgb)
        color3 = hex_to_rgb(args.pattern_color3) if args.pattern_color3 else None
        shared_noise = _noise_field(args.pattern, size=args.texture_size, seed=args.seed,
                                     scale=args.pattern_scale, octaves=args.octaves,
                                     warp=args.warp, ridged=args.ridged,
                                     contrast=args.pattern_contrast,
                                     aniso=args.pattern_aniso, bias=args.pattern_bias,
                                     speck_count=args.speck_count,
                                     speck_size=args.speck_size, speck_cluster=args.speck_cluster, speck_aspect=args.speck_aspect,
                                     speck_cluster_size=args.speck_cluster_size,
                                     speck_angles=args.speck_angles, speck_align=args.speck_align,
                                     speck_align_spread=args.speck_align_spread,
                                     band_centers=args.band_centers, band_freq=args.band_freq,
                                     band_irregularity=args.band_irregularity,
                                     wisp_amount=args.wisp_amount, crack_amount=args.crack_amount,
                                     crack_cells=args.crack_cells, crack_width=args.crack_width,
                                     crack_coverage=args.crack_coverage, wisp_sparsity=args.wisp_sparsity)
        texture_png = build_pattern_texture(args.pattern, rgb, color2, noise=shared_noise, color3=color3)

        metal_mask = None
        if args.metallic_inclusions != "none":
            metal_mask = build_metal_mask(shared_noise, args.metallic_inclusions,
                                          args.metallic_threshold, args.metallic_softness)
            # metallicFactor MULTIPLIES the texture's B channel, so it has to
            # be 1 or the baked mask is scaled away to nothing.
            metallic = 1.0
            if transmission is not None:
                transmission_texture_png = build_transmission_texture(metal_mask)

        if args.frosted or metal_mask is not None:
            roughness_texture_png = build_roughness_texture(
                args.roughness_min, args.roughness_max, shared_noise,
                metal_mask=metal_mask, metal_roughness=args.metallic_roughness)
        # roughnessFactor MULTIPLIES the baked G channel, so any factor below
        # 1 silently compresses the roughness range that was just baked --
        # the auto-guessed value would leave a "frosted" bead near-mirror.
        # An explicit --roughness is still honoured (with a warning above
        # when it conflicts with --metallic-roughness).
        if roughness_texture_png and args.roughness is None:
            roughness = 1.0

        if args.frosted:
            normal_texture_png = build_normal_texture(
                size=args.texture_size, seed=args.seed + 97, scale=args.normal_scale,
                strength=args.normal_strength, octaves=args.octaves,
                noise=shared_noise if args.normal_follows_pattern else None)

    # Tangent along the u (longitude) direction: for both the sphere band and
    # the bore, dP/dtheta normalises to (sin t, 0, cos t) with t = 2*pi*u, which
    # is exactly orthogonal to the surface normal in both cases.
    tangents = None
    if args.anisotropy > 0:
        tangents = []
        for i in range(len(uvs) // 2):
            t = uvs[i * 2] * math.pi * 2
            tangents.extend([math.sin(t), 0.0, math.cos(t), 1.0])

    glb_bytes = build_glb(
        positions, normals, uvs, indices, base_color_linear, roughness, metallic,
        args.name, transmission=transmission, ior=ior, thickness=thickness,
        texture_png=texture_png, roughness_texture_png=roughness_texture_png,
        normal_texture_png=normal_texture_png,
        attenuation_color_linear=attenuation_color_linear, attenuation_distance=attenuation_distance,
        tangents=tangents, anisotropy=args.anisotropy or None,
        anisotropy_rotation=args.anisotropy_rotation,
        transmission_texture_png=transmission_texture_png,
    )

    with open(args.out, "wb") as f:
        f.write(glb_bytes)

    print(json.dumps({
        "out": args.out,
        "name": args.name,
        "diameter_mm": args.diameter_mm,
        "sampled_color_srgb": "#%02x%02x%02x" % rgb,
        "roughness": roughness,
        "translucent": bool(transmission),
        "transmission_factor": transmission,
        "pattern": args.pattern,
        "frosted": args.frosted,
        "segments": f"{seg_w}x{max(4, seg_w // 2)}",
        "hole_diameter_mm": args.hole_diameter_mm,
        "anisotropy": args.anisotropy,
        "vertex_count": len(positions) // 3,
        "triangle_count": len(indices) // 3,
        "file_bytes": len(glb_bytes),
    }, indent=2))


if __name__ == "__main__":
    main()
