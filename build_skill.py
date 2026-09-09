#!/usr/bin/env python3
"""Package the skill folder as a .skill file (a zip) for upload to claude.ai."""
import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "gem-bead-to-glb")
OUT = os.path.join(ROOT, "gem-bead-to-glb.skill")

files = []
for dp, dn, fn in os.walk(SRC):
    dn[:] = [d for d in dn if d != "__pycache__"]
    for f in sorted(fn):
        if f.endswith(".pyc"):
            continue
        p = os.path.join(dp, f)
        files.append((p, os.path.join("gem-bead-to-glb", os.path.relpath(p, SRC))))
files.sort(key=lambda x: x[1])

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for path, arc in files:
        z.write(path, arc)

print(f"{OUT}  {os.path.getsize(OUT):,} bytes, {len(files)} files")
for _, arc in files:
    print("  ", arc)
