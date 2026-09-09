# Making a bead look like real stone

Read this when tuning appearance. The failure-mode catalogue at the end is
the fastest route: most complaints ("too red", "looks like candy", "the
flecks look wrong") appear there by name with the fix that actually works.

## Contents

- [The four principles](#the-four-principles)
- [Pattern selection by stone type](#pattern-selection-by-stone-type)
- [Pattern-specific flags](#pattern-specific-flags)
- [Fibre direction (and optional chatoyancy)](#fibre-direction-and-optional-chatoyancy)
- [Grades are specifications](#grades-are-specifications)
- [Failure modes and their real fixes](#failure-modes-and-their-real-fixes)
- [Worked examples](#worked-examples)

## The four principles

**1. Detail at every scale (`--octaves` 6-8).** Real mineral texture has
big cloudy masses, veins inside them, and fine mottling inside those, all
at once. A single octave of noise has exactly one feature size and always
reads as fake, whether it looks like blobs (low frequency) or grain (high).

**2. Domain warping (`--warp` 0.3-0.6).** Displacing the noise by *another*
noise field turns round blobs into the stretched, swirled filaments real
stone has. Without it, even good fBm reads as clouds rather than rock.
Exception: `band` wants much less (0.15-0.3) — past ~0.35 the layers stop
reading as layers and break into blotches.

**3. Three tones, not two.** `--color` body, `--pattern-color2` light,
`--pattern-color3` dark. Real stone has a dark matrix/vein tone as well as
a light one; omitting the dark tone is the most common cause of a
washed-out texture.

**4. Correlated relief (`--frosted`, `--normal-follows-pattern`).** When
roughness and normal detail follow the *same* field as the colour, a
cloudy patch is simultaneously differently-coloured, rougher and slightly
displaced — one physical feature. Uncorrelated, it reads as three
unrelated effects stacked on each other.

## Pattern selection by stone type

Match the stone's actual internal structure, not just "it has a pattern".

| stone look | flags |
|---|---|
| cloudy / mottled (quartz family, aquamarine) | `--pattern marble --warp 0.4-0.45` |
| concentric / botryoidal banding (rhodochrosite, malachite, agate eyes) | `--pattern band --band-centers 6-9 --band-freq 20-34 --band-irregularity 0.15 --warp 0.15` |
| parallel layering (onyx, slab-cut agate) | `--pattern band --band-centers 0 --warp 0.15-0.3` |
| swirled fibrous veins (charoite, jade, serpentine) | `--pattern fiber --warp 0.5 --pattern-aniso 4-5 --pattern-contrast 1.5` |
| straight parallel fibres (tiger's eye, satin spar, fibrous jade) | `--pattern fiber --warp 0.15 --pattern-aniso 0.12 --pattern-contrast 1.9` |
| bladed streaks in a translucent body (kyanite) | `--pattern fiber --warp 0.10 --pattern-aniso 0.10 --pattern-contrast 1.7 --pattern-bias 1.9 --translucent --ior 1.72` |
| suspended flecks in a clear body (strawberry quartz, sunstone) | `--pattern speckle --speck-count 12000+ --speck-size 3 --speck-cluster 0.75` |
| needles in sheaves (金发晶 gold rutilated quartz, tourmalinated quartz, actinolite) | `--pattern speckle --speck-size 55 --speck-aspect 100 --speck-count 6500 --speck-cluster 0.12 --speck-angles 36 --speck-align 0.9` |
| metallic inclusions (金发晶 rutile, pyrite, goldstone, hematite) | add `--metallic-inclusions dark --metallic-roughness 0.3` to whichever pattern places them |
| high-grade "ice" stone: clean body, a few wisps, a few fractures (6A rhodochrosite, icy jade) | `--pattern ice --wisp-amount 0.3 --crack-amount 0.34 --crack-cells 20 --crack-coverage 0.3` |
| genuinely plain stone | `--pattern none` |

## Pattern-specific flags

**`speckle`** — discrete inclusions stamped as objects (points with varied
radii and elongation), not derived from noise.

| flag | meaning |
|---|---|
| `--speck-count N` | how many flecks at 1024px (auto-scaled for other sizes) |
| `--speck-size N` | fleck diameter in texture pixels — higher = bigger |
| `--speck-aspect N` | max elongation. ~3 = mixed flakes/dots; 4-6 = fibrous slivers; 40-65 = long needles |
| `--speck-cluster N` | fraction bunching into veils (0.6-0.85). An even sprinkle always reads as confetti |
| `--speck-cluster-size N` | spread of each cloud in px. Too large gives one big blob like a vignette |
| `--speck-angles N` | how many distinct orientations exist. 6 is fine for dots, but long needles need 30-40 |
| `--speck-align N` | 0..1, fraction of flecks following a local sweep direction instead of pointing randomly. **This is what makes needles read as hair rather than as scratches.** 0.75-0.9 |
| `--speck-align-spread N` | fan within one sheaf, radians. 0.1 = tight silky bundle, 0.35 = loose spray |

`--speck-size` sets the **long** axis; the short axis is that divided by
`--speck-aspect`. So size scales the whole fleck *uniformly* — raising it
to lengthen a needle makes it proportionally fatter at the same time, and
the shape only changes when you move aspect. To make needles **thinner**,
lower size and raise aspect together. (The short axis has a 0.6px floor,
so past very high aspect ratios extra aspect stops thinning anything and
only shortens the fleck relative to its neighbours.)

**`band`** — layering. `--band-centers 0` gives parallel layers; 1-10 gives
concentric layers nested around that many growth centres.

| flag | meaning |
|---|---|
| `--band-centers N` | 0 = parallel, 6-9 = botryoidal (what most banded gems actually are) |
| `--band-freq N` | number of layers across the texture |
| `--band-irregularity N` | alternates thick zones with tight clusters of thin lines (0.1-0.3). Evenly spaced bands are the giveaway of a fake |

**`ice`** — a clean translucent body whose character comes from a *small*
number of discrete defects.

| flag | meaning |
|---|---|
| `--wisp-amount N` | strength of the white filaments (白紋). 0.15-0.35 for a high grade |
| `--wisp-sparsity N` | higher = fewer, more isolated wisps |
| `--crack-amount N` | strength of the fracture network (冰裂) |
| `--crack-cells N` | Voronoi cell count. Keep low (15-25) — a dense net reads as crackle glaze |
| `--crack-width N` | line thickness (0.004-0.012) |
| `--crack-coverage N` | fraction of the surface with any cracking at all (0.2-0.35) |

Cracks are generated as Voronoi *cell boundaries*, not noise: the gap
between nearest and second-nearest seed distance goes to zero exactly on a
boundary, which is what produces thin continuous branching lines. Noise
can only ever blur toward something crack-ish.

## Fibre direction (and optional chatoyancy)

`--pattern-aniso` stretches the noise along one axis, and **which axis
matters on a drilled bead**:

- **`> 1`** (3-6) elongates along v, so fibres run pole-to-pole. On a
  drilled bead they converge and pinch at the hole.
- **`< 1`** (e.g. 0.12-0.2) elongates along u, so fibres ring the bead
  perpendicular to the drill hole. This is what banded fibrous stones
  want — and it is how real tiger's eye beads are cut, with the chatoyant
  band running across the face rather than into the hole.

Swirled vs straight is a separate axis from that, controlled by `--warp`:
charoite swirls (`--warp 0.5`), tiger's eye is nearly parallel with only
gentle undulation (`--warp 0.15`). Copying the charoite recipe onto
tiger's eye is the easy mistake — the fibre *shape* is right but the
*flow* is wrong.

**Chatoyancy** (the moving cat-eye sheen) is available via `--anisotropy`,
which stretches the specular highlight along the fibre direction instead of
leaving a round dot. It is **off by default and should stay off unless
someone asks for it and has checked how it renders.** In practice the
fibre texture plus `--frosted` already carries the silky read, and the
anisotropic highlight is easy to get subtly wrong:

- Which way the highlight elongates relative to the tangent depends on the
  viewer's BRDF implementation, so `--anisotropy-rotation` may need
  flipping by `1.5708` (pi/2) — and you cannot tell which without looking
  at it in the actual target renderer.
- It only works where the consuming viewer supports
  `KHR_materials_anisotropy` at all.

Setting it emits TANGENT vectors automatically (the extension requires
them; they are computed analytically along the u direction and are exactly
perpendicular to the normals for both the sphere band and the bore wall).
Leaving `--anisotropy` off keeps the mesh free of the TANGENT attribute
and the material free of the extension entirely.

## Grades are specifications

Many gems are sold by grade, and the grade description *is* the build
spec. Chinese gem grading is especially precise. 6A rhodochrosite is
「冰種、晶體乾淨、油潤光澤，只有少量白紋和冰裂」— ice grade, clean crystal,
oily lustre, only a *small amount* of white veining and ice cracks. That
translates directly:

- 冰種 + 晶體乾淨 → `--pattern ice`, clean body, high `--transmission`
- 少量白紋 → low `--wisp-amount`, high `--wisp-sparsity`
- 少量冰裂 → `--crack-*` present but `--crack-coverage` ~0.3
- 油潤光澤 → roughness **0.06-0.15**, not near-zero. Oily lustre is not
  mirror polish; a glass-smooth bead misses the grade

Lower grades differ by having *more* cloudiness and veining, so the same
knobs scaled up cover the whole ladder.

**Ask which grade before iterating.** Many stones have a plain translucent
"ice" grade (冰种) alongside the figured one, and it is a completely
different and much simpler material. Chasing complex figuring the user
never wanted is the single most expensive mistake available here.

## Failure modes and their real fixes

**"Looks like hard candy / a plastic ball."** One uniform glossy colour
with one hard pinpoint highlight. Turn on `--frosted`, use a paler and
less saturated base for crystalline stones, push `--transmission` to 0.8+,
and set `--attenuation-color`/`--attenuation-distance-mm` for depth.

**"Too dark / murky."** A transmissive bead refracts whatever is behind
it, so first check the scene's background and environment brightness. In
the file, raise `--attenuation-distance-mm` (this is the main lever) and
lower `--thickness-mm`. Attenuation distance shorter than the bead
diameter absorbs heavily.

**"Too red / not the right hue."** Change `--attenuation-color` along with
`--color`. Adjusting only the base colour leaves the volume tint pulling
the old hue back wherever the stone is thick.

**"There's too much white / the white patches look wrong."** Reach for
`--pattern-bias` (1.3-1.6) before changing colours — it shrinks how much
of the surface reaches the light tone while leaving structure intact. For
fibrous stones also add `--pattern-aniso 4-5`: isotropic noise makes
woolly *patches*; only stretched noise makes thin brush-stroke fibres.

**"The flecks look blocky / like grain."** Don't make inclusions out of
noise at all. `--pattern speckle` stamps them as discrete objects.
Thresholded value noise always shows its lattice as visible squares no
matter how it is tuned.

**"The inclusions look like confetti / too evenly sprinkled."** Raise
`--speck-cluster` (0.75+) rather than changing the count. Real inclusions
settled onto growth planes, so they bunch into veils with genuinely clear
stone between them; an even sprinkle at any density reads as printed dots.

**"The inclusions are too sparse / it should look denser."** Densely
included stone (草莓晶 up close) is a near-continuous felted mass, not
dots on a clear field. Push `--speck-count` up an order of magnitude
(50k-100k), and raise `--speck-aspect` to 4-6 — *packed slivers* read as
mineral wool, packed dots read as printed spots.

**"The needles look like a wire cage / scratches, not like hair."** Two
separate causes, and you usually have both:

1. **Too few orientations.** `--speck-angles` defaults to 6, which is
   invisible on round flecks but ruinous on long ones — every needle in the
   stone lands on one of six global directions, so they form a regular
   lattice. Raise it to 30-40.
2. **Independent random angles.** Even with 40 bins, needles that point
   randomly read as a scribble. Rutile, tourmaline and actinolite grow in
   **sheaves** — locally near-parallel bundles that fan and change
   direction across the stone. That is why the mineral is called 发 (hair).
   `--speck-align 0.9 --speck-align-spread 0.28` drives each needle's angle
   from a smooth low-frequency field, so neighbours are near-parallel,
   while the unaligned 10% stay as the stray crossing needles every real
   specimen has.

The giveaway that you need this: the pattern looks *busy* but every
intersection is a clean X. Real sheaves give you long stretches of
near-parallel travel with occasional crossings.

**"There's no gold in it" / "the metallic bits look like printed ink."**
In a PBR renderer gold is not a colour — it is `metallic=1` plus a
*coloured specular reflection*. A gold-coloured diffuse patch can never
read as metal no matter what hex you pick, and inside a transmissive bead
it gets worse: at `--transmission 0.9` you are looking straight *through*
the needles, which washes them out to pale yellow ink on glass.

`--metallic-inclusions dark` (or `light`, depending on which end of the
field the inclusions sit on — `speckle` puts them at the dark end) bakes
three correlated things off the same pattern mask:

- **metallic = 1** on the inclusions (B channel of the metallicRoughness
  texture), 0 on the stone body;
- **their own roughness** (`--metallic-roughness`, 0.2-0.35 for bright
  rutile), since the body's `--roughness-min/max` range is tuned for a
  dielectric;
- **transmission = 0** on them, via a `transmissionTexture` — metal does
  not transmit light, and this is what turns them from ink printed on the
  glass into solid crystals suspended inside it.

Then `--pattern-color3` stops being a pigment and becomes the metal's
*reflectance*: use a brighter, more saturated gold than looks right in the
flat texture (`#e8b34a`, not `#c2860c`), because what you see in the render
is that colour multiplied by the environment.

Note `metallicFactor` and `roughnessFactor` both **multiply** their
texture channels, so both must be 1.0 — the script forces this, but a
hand-edited material that drops either one silently erases the effect.

**"The needles came out as thick blobs / clumps."** `--speck-size` scales
the fleck uniformly, so raising it to lengthen a needle fattens it by the
same factor. Raise `--speck-aspect` in step with it (55/100 gives a hair;
150/18 gives a lozenge). Also keep `--speck-cluster` low
(~0.1) — needles grew as separate crystals crossing at random angles, so
clustering them into veils is the wrong physics and reads as fuzz.

**"The banding looks like printed stripes."** Most banded gems are
botryoidal: layers grew outward from nodule centres, so they read as
nested closed rings and lens shapes, not lines running across the stone.
Set `--band-centers` 6-9. Parallel banding is correct only for slab-cut
onyx and some agates.

**"It's banded but still not crystal-like."** Banding and translucency are
independent. Keep the pattern and push the volume: `--transmission` 0.6+,
`--attenuation-distance-mm` ~30, `--thickness-mm` 3-4. A stone can be
strongly figured *and* glassy.

**"The ice-grade stone looks like crackle glaze."** Cracks spread evenly
over the whole surface. Keep `--crack-coverage` ~0.3 and `--crack-cells`
low. For a high grade, restraint IS the material.

**"The wisps look like brushed fabric."** Wisps built from fine
many-octave noise turn into an all-over streaky weave. Keep them coarse
(few octaves, lattice no finer than the body) and raise `--wisp-sparsity`.

## Worked examples

**Charoite — fibrous, opaque-ish, silky**

```bash
python3 scripts/generate_bead_glb.py \
  --color "#6b4f8f" --pattern-color2 "#d8cbe8" --pattern-color3 "#2b1d40" \
  --pattern fiber --pattern-scale 6 --octaves 7 --warp 0.5 --pattern-aniso 4.5 \
  --pattern-contrast 1.5 --pattern-bias 1.5 \
  --frosted --roughness 1.0 --roughness-min 0.06 --roughness-max 0.26 \
  --normal-strength 0.32 --normal-follows-pattern \
  --translucent --transmission 0.20 --ior 1.55 \
  --attenuation-color "#9d84bd" --attenuation-distance-mm 11 --thickness-mm 8 \
  --texture-size 1024 --segments 128 --diameter-mm 8 \
  --out charoite.glb --name "Charoite"
```

**6A ice rhodochrosite — clean body, few wisps, few fractures**

```bash
python3 scripts/generate_bead_glb.py \
  --color "#eb8396" --pattern-color2 "#fdf0f3" --pattern-color3 "#d96b81" \
  --pattern ice --pattern-scale 3 --warp 0.4 --pattern-aniso 2.0 \
  --wisp-amount 0.40 --wisp-sparsity 4.9 \
  --crack-amount 0.41 --crack-cells 20 --crack-width 0.0073 --crack-coverage 0.34 \
  --frosted --roughness 1.0 --roughness-min 0.06 --roughness-max 0.15 \
  --normal-strength 0.16 --normal-follows-pattern \
  --translucent --transmission 0.82 --ior 1.60 \
  --attenuation-color "#f7b5c2" --attenuation-distance-mm 28 --thickness-mm 4.2 \
  --texture-size 1024 --segments 128 --diameter-mm 8 \
  --out rhodochrosite.glb --name "Rhodochrosite_6A"
```

**Strawberry quartz — dense felted inclusions**

```bash
python3 scripts/generate_bead_glb.py \
  --color "#cf8079" --pattern-color2 "#ecd0c8" --pattern-color3 "#a03f30" \
  --pattern speckle --pattern-scale 5 \
  --speck-count 95000 --speck-size 3.2 --speck-aspect 5.0 \
  --speck-cluster 0.5 --speck-cluster-size 55 \
  --pattern-contrast 1.05 --pattern-bias 1.9 \
  --frosted --roughness 1.0 --roughness-min 0.04 --roughness-max 0.17 \
  --normal-strength 0.22 \
  --translucent --transmission 0.7 --ior 1.55 \
  --attenuation-color "#e0a89e" --attenuation-distance-mm 20 --thickness-mm 5 \
  --texture-size 1024 --segments 128 --diameter-mm 8 \
  --out strawberry_quartz.glb --name "StrawberryQuartz"
```

**Tiger's eye — parallel fibres with cat-eye sheen**

```bash
python3 scripts/generate_bead_glb.py \
  --color "#a8681c" --pattern-color2 "#edc063" --pattern-color3 "#241407" \
  --pattern fiber --pattern-scale 5 --octaves 6 \
  --warp 0.15 --pattern-aniso 0.12 --pattern-contrast 1.9 \
  --frosted --roughness 1.0 --roughness-min 0.05 --roughness-max 0.18 \
  --normal-strength 0.3 --normal-follows-pattern \
  --texture-size 1024 --segments 96 --diameter-mm 8 --hole-diameter-mm 1.2 \
  --out tigereye.glb --name "TigerEye"
```

Note: opaque, so no `--translucent`. Tiger's eye gets its depth from the
fibre banding and the varied roughness, not from transmission.

**Kyanite — bladed silvery streaks in translucent royal blue**

```bash
python3 scripts/generate_bead_glb.py \
  --color "#2a5fb5" --pattern-color2 "#dfeafa" --pattern-color3 "#0e2559" \
  --pattern fiber --pattern-scale 3 --octaves 5 \
  --warp 0.10 --pattern-aniso 0.10 --pattern-contrast 1.7 --pattern-bias 1.9 \
  --frosted --roughness 1.0 --roughness-min 0.03 --roughness-max 0.14 \
  --normal-strength 0.26 --normal-follows-pattern \
  --translucent --transmission 0.55 --ior 1.72 \
  --attenuation-color "#6b9ad8" --attenuation-distance-mm 18 --thickness-mm 4.5 \
  --texture-size 1024 --segments 96 --diameter-mm 8 --hole-diameter-mm 1.2 \
  --out kyanite.glb --name "Kyanite"
```

Note `--pattern-bias 1.9`: without it the streaks cover about half the
surface and the bead reads as white-and-blue rather than blue. Bias is the
right knob here — it thins the light tone while leaving the blade
structure intact.

**金发晶 Gold rutilated quartz — golden sheaves of needles in amber quartz**

```bash
python3 scripts/generate_bead_glb.py \
  --color "#eecf8a" --pattern-color2 "#faeecb" --pattern-color3 "#eeb03c" \
  --pattern speckle --pattern-scale 4 \
  --speck-count 6500 --speck-size 55 --speck-aspect 100 \
  --speck-cluster 0.12 --speck-cluster-size 130 \
  --speck-angles 36 --speck-align 0.9 --speck-align-spread 0.28 \
  --pattern-contrast 1.3 --seed 61 \
  --metallic-inclusions dark --metallic-threshold 0.40 --metallic-roughness 0.28 \
  --frosted --roughness 1.0 --roughness-min 0.02 --roughness-max 0.10 \
  --normal-strength 0.12 \
  --translucent --transmission 0.80 --ior 1.54 \
  --attenuation-color "#eec070" --attenuation-distance-mm 18 --thickness-mm 4.5 \
  --texture-size 1024 --segments 96 --diameter-mm 8 --hole-diameter-mm 1.2 \
  --out rutilated.glb --name "GoldRutilatedQuartz"
```

Three non-obvious things, each of which this stone got wrong first time:

- **`speckle`, not `fiber`.** `fiber` makes continuous woolly filaments
  following one grain direction; rutile needles are separate straight
  crystals. `speckle` stamps each one as its own object.
- **`--speck-align` is what makes it 发.** Without sheaf alignment the
  needles form a wire cage. See the failure modes above.
- **`--metallic-inclusions dark` is what makes it 金.** Without it the
  needles are diffuse yellow seen through 0.9 transmission — yellow ink on
  glass.

Note `--speck-size 55 --speck-aspect 100`: size is the short axis and
aspect the multiplier, so a *thin* needle wants low size and high aspect.
Raising size alone to lengthen a needle just fattens it.

Keep `--normal-strength` low (0.12): the needles are *inside* the quartz,
so surface relief tracking them would put them on the outside of the bead.

For a more golden overall read, the body colour does less work than the
volume does — shorten `--attenuation-distance-mm` (32 → 18) so light picks
up more gold on its way through, and drop `--transmission` slightly (0.9 →
0.8) so the bead is milky-gold rather than water-clear. Real 金发晶 balls
are not colourless quartz with yellow lines in them.

**Aquamarine — soft internal cloud, icy and clear**

```bash
python3 scripts/generate_bead_glb.py \
  --color "#bcdde5" --pattern-color2 "#f4fbfc" --pattern-color3 "#74a9b8" \
  --pattern marble --pattern-scale 5 --octaves 7 --warp 0.45 --pattern-contrast 1.25 \
  --frosted --roughness 1.0 --roughness-min 0.03 --roughness-max 0.18 \
  --normal-strength 0.28 --normal-follows-pattern \
  --translucent --transmission 0.82 --ior 1.58 \
  --attenuation-color "#a9d6e0" --attenuation-distance-mm 13 --thickness-mm 8 \
  --texture-size 1024 --segments 128 --diameter-mm 8 \
  --out aquamarine.glb --name "Aquamarine"
```
