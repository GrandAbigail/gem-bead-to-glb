# Stringing beads, and paying for them

Read this when the beads are going onto a bracelet rather than being
viewed one at a time.

## Drilled beads

`--hole-diameter-mm` produces a bead with a real channel through it. No
CSG is involved: a sphere with a cylindrical bore is a surface of
revolution with a piece removed, so it is built directly — keep the
spherical band whose polar angle clears the hole, then close the two
openings with an inward-facing cylinder wall. Both parts are generated at
the same radius and height at the seam, so the join is exact.

Typical bracelet spec: **1.0-1.5mm hole on an 8mm bead**.

Drilled and solid variants share the same UV mapping, so one set of baked
textures serves both — you never need to re-bake to add a hole.

Two things to pass on to whoever strings them:

- **The channel runs along the mesh's local +Y.** Align local +Y with the
  cord's tangent at each bead position and the cord threads straight
  through. In three.js:
  `mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), tangent)`.
- **A threaded bead has one rotational degree of freedom left** — spin
  about the cord axis. This matters more than it sounds: with a solid bead
  you can hide repetition by rotating each one arbitrarily, but on a string
  that trick mostly disappears, which makes the UV-offset technique below
  the primary source of variety rather than a nice extra.

## Making a strand look like real stones, not a clone army

One `.glb` per stone type means every bead on the bracelet is identical,
which reads as fake immediately. The textures this skill bakes are
**seamlessly tileable** (the noise lattice wraps in both axes), and that is
what makes the cheap fix possible: give each bead instance a different UV
offset and it shows a completely different region of the pattern — at zero
asset cost.

Per bead, clone the material and each map, and set the **same** offset on
all of them:

```js
for (const slot of ["map","roughnessMap","metalnessMap",
                    "normalMap","transmissionMap"]) {
  if (mesh.material[slot]) {
    mesh.material[slot] = mesh.material[slot].clone();
    mesh.material[slot].wrapS = mesh.material[slot].wrapT = THREE.RepeatWrapping;
    mesh.material[slot].offset.set(u, v);   // SAME u,v for every slot
  }
}
```

`scripts/make_strand_demo.py a.glb "label" [b.glb "label" ...] --out
strand.html` builds a working demo of exactly this — 20 beads on a cord
from one `.glb`, with each randomisation as a checkbox so you can show
what each one buys. Untick all four and you get the naive version where
every bead is identical, which is the fastest way to make the case.

All maps must share one offset, or colour, roughness and normal detail
drift apart and a single bead looks like three stones overlaid. **Do not
omit `transmissionMap`** — a bead made with `--metallic-inclusions` has
one, and leaving it behind gives transparent needles floating over opaque
stone.

`Texture.clone()` shares the underlying `Source`, so the image uploads to
the GPU once regardless of how many beads use it.

Stack these on top, cheapest first:

1. **Spin about the cord axis** — free, and the only rotation a threaded
   bead has.
2. **±3% size jitter** — real beads are not identical.
3. **A mild per-bead colour multiplier** (0.88-1.12) — stands in for the
   density differences that make some beads in a real strand read darker
   or milkier than their neighbours.

**What UV offset cannot do** is vary a bead's *overall* inclusion
density — a whole bead that is visibly cleaner or milkier than its
neighbours. Real strands do show this. If it matters, bake 3-4 texture
variants per stone (light / typical / dense) and pick between them by
weight; drop `--texture-size` to 512 to pay for the extra bytes.

**At scale**, cloning materials means one draw call per bead. Fine for one
bracelet; for many on screen at once, move to `InstancedMesh` with the UV
offset as an instanced attribute.

## Size budget

Mesh cost from `--segments`:

| `--segments` | triangles | mesh bytes | when |
|---|---|---|---|
| 32 | 960 | ~30 KB | many beads, mobile-first, beads stay small |
| 64 (default) | 3,968 | ~115 KB | normal configurator use |
| 96 | 9,024 | ~250 KB | beads shown large or rotated close-up |
| 128 | 16,128 | ~450 KB | close-up / hero shots |

Faceting shows on the **silhouette** first — normals are per-vertex so
shading itself stays smooth — and transmissive beads reveal it more than
opaque ones because refraction bends the edge.

**Textures usually dominate, not geometry.** With `--frosted` the three
baked maps at `--texture-size 1024` are 2-3 MB and swamp even a 128-segment
mesh. Dense `speckle` patterns compress especially badly. So when a
catalogue gets too big, drop `--texture-size` to 512 (roughly a quarter of
the bytes, barely distinguishable at bracelet scale) before you consider
capping `--segments`.

Dense `speckle` is also the slowest to *generate* — stamping is O(n·r²),
so the 金发晶 recipe takes ~6s at 1024px and ~65s at 2048px. Batch
accordingly; 1024 is the practical ceiling for a catalogue run.

Rough per-bead totals: 512px textures ≈ 0.5-1 MB, 1024px ≈ 2-4 MB. For a
48-stone catalogue that is the difference between ~40 MB and ~150 MB.
