#!/usr/bin/env python3
"""Run every bash recipe in references/materials.md and validate the output.

The documented recipes ARE the test suite: if a flag changes meaning or a
default shifts, a recipe either stops generating or starts producing an invalid
file, and this catches it. Several real regressions in this skill's history
were caught exactly this way.
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(ROOT, "gem-bead-to-glb")
md = open(os.path.join(SKILL, "references", "materials.md"), encoding="utf-8").read()
cmds = re.findall(r"```bash\n(python3 scripts/generate_bead_glb\.py.*?)\n```", md, re.S)

if not cmds:
    sys.exit("no recipes found in references/materials.md")

failures = 0
with tempfile.TemporaryDirectory() as tmp:
    for cmd in cmds:
        cmd = cmd.replace("\\\n", " ")
        name = re.search(r'--name "?([\w_]+)', cmd).group(1)
        cmd = re.sub(r"--out \S+", f"--out {tmp}/{name}.glb", cmd)
        # keep CI fast; appearance is not what this test checks
        cmd = re.sub(r"--texture-size \d+", "--texture-size 256", cmd)
        cmd = re.sub(r"--segments \d+", "--segments 32", cmd)
        cmd = cmd.replace("python3 scripts/", f"python3 {SKILL}/scripts/")
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if r.returncode:
            print(f"FAIL generate {name}\n{r.stderr[-400:]}")
            failures += 1
            continue
        v = subprocess.run(f"python3 {SKILL}/scripts/validate_glb.py {tmp}/{name}.glb",
                           shell=True, capture_output=True, text=True)
        if v.returncode:
            print(f"FAIL validate {name}\n{v.stderr[-400:]}")
            failures += 1
        else:
            print(f"ok  {name}")

print(f"\n{len(cmds) - failures}/{len(cmds)} recipes passed")
sys.exit(1 if failures else 0)
