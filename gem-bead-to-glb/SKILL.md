---
name: gem-bead-to-glb
description: Turn a photo of a gemstone/crystal bracelet bead into a correctly-sized, colored glTF binary (.glb) sphere mesh — optionally with a real stringing hole — for use in a three.js bracelet/jewelry configurator. Use this skill whenever the user shares or references a photo of a bead, gemstone, or crystal and wants a 3D model, a .glb file, or an asset for a three.js/web bead scene — even if they just say "give me a glb for this stone" or "make the 3D asset for 草莓晶" without spelling out the whole pipeline. Also use it when the user is building out a set of bracelet materials (e.g. a list like "1-06 草莓晶 Strawberry Quartz") and needs a batch of matching .glb bead assets, or when they ask how to string those beads so each one looks like a different real stone.
---

# Gem Bead → GLB

Turns a photo of a gemstone bead into a `.glb`: a correctly-sized sphere
(optionally drilled for stringing) with a PBR material whose colour,
finish and internal pattern match the stone. The output drops straight
into a three.js scene via `GLTFLoader`.

## How it works, and why

**The texture is procedural, not the photo.** A flat product photo cannot
be wrapped onto a sphere without seams and distortion. So the job is:
*look at the photo, decide the colours, finish and pattern type, and bake
those into a synthetic texture* — multi-octave (fractal) noise with domain
warping, which reads as real mineral structure without pretending to
reproduce the exact real pattern.

**No npm / three.js dependency.** `scripts/generate_bead_glb.py` writes the
`.glb` container by hand (glTF 2.0 is a stable, documented format). It
needs only Python's stdlib plus NumPy and Pillow, so it runs even where
package installs are blocked.

**If a bead looks dull in the user's own scene, suspect the scene first.**
`--translucent` materials (KHR_materials_transmission) and glossy PBR need
*something to reflect and transmit* — an environment map and/or a
background. A bare scene with flat grey and no environment map (which is
what threejs.org/editor gives you by default) makes even a correct
transmissive material look like dull plastic. Check that the consuming
scene sets `scene.environment` before concluding the file is wrong;
`scripts/make_viewer.py` builds a page with a correct setup to prove it.

## Workflow

### 1. Gather the essentials

You need an image of the bead, plus ideally its diameter and a name/code.

- If the user already gave a name/code (e.g. from a materials list), use
  it — don't ask again.
- **Don't block on diameter.** Bracelet beads are almost always 6mm or
  8mm; default to 8mm and say so.
- **Ask which grade** if the stone has grades and the photo is ambiguous —
  see `references/materials.md`, "Grades are specifications". This one
  question can save many iterations.

### 2. Read the photo yourself

You are multimodal — look at the image rather than relying on the script's
own colour sampling. Decide:

- **Three colours**: `--color` (body), `--pattern-color2` (light tone),
  `--pattern-color3` (dark accent). The dark tone matters more than people
  expect; a two-stop ramp always looks washed out.
- **Pattern type** — match the stone's actual structure, not just "it has
  a pattern". The selection table is in `references/materials.md`.
- **Translucent or opaque**, and how glossy.
- **Are the inclusions metal?** Rutile (金发晶), pyrite, hematite,
  goldstone. If so you need `--metallic-inclusions` — a metallic colour
  painted into baseColor can never read as metal. This is easy to miss at
  step 2 and expensive to discover at step 4.

`--color` (your read) is the primary path; `--image` (the script's
center-crop average) is a fallback or cross-check.

### 3. Generate

```bash
python3 scripts/generate_bead_glb.py \
  --color "#cf8079" --pattern-color2 "#ecd0c8" --pattern-color3 "#a03f30" \
  --pattern speckle --speck-count 95000 --speck-size 3.2 --speck-aspect 5 \
  --frosted --roughness 1.0 --translucent --transmission 0.7 \
  --texture-size 1024 --segments 96 --diameter-mm 8 --hole-diameter-mm 1.2 \
  --out "1-06_StrawberryQuartz.glb" --name "1-06_StrawberryQuartz"
```

The script prints a JSON summary — check it matches what you intended.

**`--frosted` is the single biggest quality lever.** It varies roughness
and adds subtle normal relief, which breaks the one hard pinpoint
highlight that makes a bead read as shiny plastic.

Note that `roughnessFactor` and `metallicFactor` both *multiply* their
baked texture channels, so whenever a roughness map is baked the factor
must be 1.0 or the range you asked for is silently compressed. The script
now sets that automatically unless you pass `--roughness` yourself; the
recipes still pass `--roughness 1.0` explicitly so they read unambiguously.

### 4. Verify before handing off

1. `python3 scripts/validate_glb.py <file>.glb` — container structure,
   buffer lengths, index ranges, embedded PNGs, volume extensions.
2. **Look at the texture itself** when tuning appearance. Extract the
   baked PNG from the GLB and view it directly — this is how you tell a
   genuine texture bug from a preview artefact. Several real bugs in this
   skill's history were only visible this way.
3. `python3 scripts/render_preview.py <file>.glb out.png` for a quick
   independent sanity render. It is flat-shaded and low-fidelity **by
   design** — use it to catch structural faults (inside-out normals, wrong
   colour, missing texture), never to judge final quality.
4. If the user reports it looking wrong *in their scene*, build them a
   correct comparison with `scripts/make_viewer.py` rather than assuming
   the file is at fault.

**Offer variants rather than one answer.** Appearance is the user's call
and you cannot run WebGL — build 3-4 candidates along the axis they
complained about and let them pick. This has consistently been faster than
iterating one bead at a time.

### 5. Batches

For a materials list, loop steps 2-4 per row using the material code as
`--name` and filename. Summarise in one table at the end rather than
narrating every file.

## Flag reference

| flag | meaning |
|---|---|
| `--color '#rrggbb'` | body colour (preferred over `--image`) |
| `--image PATH` | let the script sample the colour itself |
| `--out PATH` / `--name NAME` | output path; name baked into node/mesh/material |
| `--diameter-mm N` | real bead diameter (default 8) |
| `--hole-diameter-mm N` | drill a real stringing channel (0 = solid). ~1.0-1.5mm on an 8mm bead |
| `--segments N` | tessellation, longitude (latitude = N/2). Default 64 |
| `--translucent` | adds transmission + ior + volume extensions |
| `--transmission N` | 0..1. Default 0.55 reads dull; 0.8+ for glassy crystal |
| `--ior N` | index of refraction (1.54 quartz, 1.58 beryl, 1.60 rhodochrosite, 1.72 kyanite) |
| `--attenuation-color` / `--attenuation-distance-mm` | colour light picks up inside the stone, and over what distance. **Raise the distance if a bead looks too dark** |
| `--thickness-mm N` | volume thickness — lower = brighter/airier |
| `--roughness N` | 0=mirror, 1=matte. Set to **1.0** whenever `--frosted` is on |
| `--frosted` | roughness + normal variation; the main anti-plastic lever |
| `--roughness-min` / `--roughness-max` | with `--frosted`: glossy vs cloudy patch roughness |
| `--normal-strength` / `--normal-scale` / `--normal-follows-pattern` | surface relief strength, grain, and whether it aligns with the veins |
| `--pattern {none,marble,band,fiber,speckle,ice}` | pattern family — see `references/materials.md` |
| `--pattern-color2` / `--pattern-color3` | light tone / dark accent tone |
| `--pattern-scale N` | base lattice of the first fBm octave (4-8); lower = larger masses |
| `--octaves N` | fBm octaves (6-8 = real-stone detail) |
| `--warp N` | domain warp — turns blobs into swirled filaments |
| `--pattern-contrast N` / `--pattern-bias N` | vein/matrix separation; gamma (>1 = less light tone) |
| `--pattern-aniso N` | stretch noise along one axis. **>1** = fibres run pole-to-pole; **<1** (e.g. 0.12) = fibres ring the bead perpendicular to the hole |
| `--metallic-inclusions {none,dark,light}` | make the inclusions real metal (rutile 金发晶, pyrite, goldstone). Bakes metallic=1 + transmission=0 over them. **This is the only way to get gold** — see `references/materials.md` |
| `--metallic-threshold` / `--metallic-softness` / `--metallic-roughness` | which part of the pattern counts as metal, how soft the edge, how polished the metal |
| `--anisotropy N` / `--anisotropy-rotation N` | optional chatoyancy via `KHR_materials_anisotropy` (off by default; emits TANGENT). Leave off unless asked — see `references/materials.md` |
| `--ridged` | sharp filaments instead of soft blobs (implied by `fiber`) |
| `--texture-size N` | texture resolution. 1024 for hero beads, 512 for catalogues |
| `--seed N` | change the pattern layout without changing anything else |

Pattern-specific flags (`--speck-*`, `--band-*`, `--wisp-*`, `--crack-*`)
are documented in `references/materials.md` alongside the pattern they
belong to.

## References

- **`references/materials.md`** — read this whenever tuning appearance:
  pattern selection by stone type, the fBm/warp/three-tone principles,
  grade-driven specs, worked examples, and a catalogue of failure modes
  with the fix that actually works for each. Most appearance complaints
  are covered there by name.
- **`references/strand-and-budget.md`** — read this when the beads are
  going onto a bracelet: drilled-bead orientation, making a strand of one
  `.glb` look like many different stones, mesh/texture size budgeting.

## Scripts

| script | use |
|---|---|
| `scripts/generate_bead_glb.py` | build the bead |
| `scripts/validate_glb.py` | structural + material-range check; run on every file |
| `scripts/render_preview.py` | flat-shaded sanity render; structural faults only |
| `scripts/make_viewer.py` | correct-environment comparison page for N beads |
| `scripts/make_strand_demo.py` | 20 beads on a cord, with the per-bead randomisation toggles |

## Known limitations (mention when relevant)

- Patterns are synthetic — good for "this is convincingly that mineral",
  not for matching a specific photo's exact veining.
- Colour and finish come from your visual read, not material scanning.
- Inclusions are painted into the texture, not modelled as geometry.
  Modelling them as real geometry inside a transmissive shell was
  prototyped and abandoned: it depends on renderer-specific screen-space
  transmission behaviour and did not pay for its complexity.
