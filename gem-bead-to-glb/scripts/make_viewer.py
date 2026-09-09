#!/usr/bin/env python3
"""
make_viewer.py -- build a self-contained HTML page that loads one or more
.glb beads with a *correct* three.js setup (environment map + background),
with a checkbox to toggle the environment on/off live.

Why this exists: KHR_materials_transmission (the "--translucent" look) and
glossy PBR materials in general need an environment to reflect/refract.
Drop the exact same .glb into a bare scene (a couple of lights, flat gray
background, no environment map -- e.g. threejs.org/editor's default scene)
and it will look dull/opaque even though the file itself is correct. This
viewer makes that difference visible and toggleable, so it's obvious
whether a "why does my bead look flat" problem is the file or the scene.

Usage:
    python3 make_viewer.py bead1.glb "Label 1" bead2.glb "Label 2" ... \\
        --out viewer.html

The output is a single HTML file with the beads embedded as base64 --
no server, no build step, just open it in a browser. It loads three.js
itself from a CDN (jsdelivr) at view time, so the machine *opening* the
file needs internet access (this script does not need any).
"""
import argparse
import base64
import json
import sys

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8" />
<title>gem-bead-to-glb viewer</title>
<style>
  html, body { margin: 0; height: 100%; background: #eceef0; color: #222; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; overflow: hidden; }
  #ui { position: fixed; top: 12px; left: 12px; z-index: 10; background: rgba(255,255,255,0.92); padding: 14px 18px; border-radius: 10px; max-width: 400px; line-height: 1.5; font-size: 13px; box-shadow: 0 2px 12px rgba(0,0,0,0.15); }
  #ui h1 { font-size: 15px; margin: 0 0 8px; }
  #ui label { display: flex; align-items: center; gap: 8px; margin: 7px 0; cursor: pointer; }
  #ui label span.k { flex: 0 0 88px; color: #555; }
  #ui input[type=range] { flex: 1; }
  #ui p { margin: 10px 0 0; color: #666; }
  #labels { position: fixed; bottom: 14px; left: 50%; transform: translateX(-50%); display: grid; gap: 4px 28px; z-index: 10; pointer-events: none; font-size: 13px; color: #333; text-align: center; background: rgba(255,255,255,0.85); padding: 10px 18px; border-radius: 8px; }
  canvas { display: block; }
</style>
</head>
<body>
<div id="ui">
  <h1>gem-bead-to-glb 诊断预览</h1>
  <label><input type="checkbox" id="envToggle" checked /> 环境贴图（透光材质必须有这个才对）</label>
  <label><input type="checkbox" id="rotateToggle" checked /> 自动旋转</label>
  <label><span class="k">亮度 exposure</span><input type="range" id="exposure" min="0.4" max="3" step="0.05" value="1.6" /></label>
  <label><span class="k">环境光强度</span><input type="range" id="envIntensity" min="0.2" max="4" step="0.05" value="1.8" /></label>
  <label><span class="k">背景明暗</span><input type="range" id="bgLight" min="0" max="1" step="0.01" value="0.88" /></label>
  <p>透光的珠子会"透出背后的东西"——背景暗，珠子就暗。拉上面几个滑块看真实亮度范围；你自己的场景有多亮，珠子就有多亮。</p>
</div>
<div id="labels"></div>

<script type="importmap">
{
  "imports": {
    "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
    "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
  }
}
</script>
<script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const BEADS = __BEADS_JSON__;

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.set(0, 3, 26);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.6;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 3, 0);
controls.enableDamping = true;

const pmrem = new THREE.PMREMGenerator(renderer);
const envTex = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

// A transmissive bead refracts whatever is BEHIND it, so a dark backdrop
// makes even a correctly-authored crystal read as murky/dark. Default to a
// bright studio-ish backdrop -- that's what jewelry renders actually use.
const bgColor = new THREE.Color();
function setBgLight(v) {
  bgColor.setRGB(v, v, v * 1.02);
  scene.background = bgColor;
}

const keyLight = new THREE.DirectionalLight(0xffffff, 2.6);
keyLight.position.set(5, 10, 7);
scene.add(keyLight);
const fillLight = new THREE.DirectionalLight(0xffffff, 1.1);
fillLight.position.set(-6, 4, -5);
scene.add(fillLight);
scene.add(new THREE.AmbientLight(0xffffff, 0.5));

let envOn = true;
function applyEnv(on) {
  envOn = on;
  scene.environment = on ? envTex : null;
  setBgLight(parseFloat(document.getElementById("bgLight").value));
}
scene.environmentIntensity = 1.8;
applyEnv(true);

const group = new THREE.Group();
scene.add(group);

const loader = new GLTFLoader();
const spacing = 9;
const COLS = __COLUMNS__ || BEADS.length;
const rows = Math.ceil(BEADS.length / COLS);
const gridW = (COLS - 1) * spacing;
const gridH = (rows - 1) * spacing;
const centerY = 3 + gridH / 2;

// Auto-fit the camera so every bead is in frame regardless of grid size --
// a fixed camera distance only ever works for one particular count.
const margin = spacing * 0.7;
const radius = Math.max(gridW, gridH) / 2 + margin;
const halfFov = (camera.fov * Math.PI) / 180 / 2;
// Fit both axes: a wide-but-short grid is limited by width, a tall one by
// height. Taking only one of them either crops beads or wastes half the frame.
const distV = (gridH / 2 + margin) / Math.tan(halfFov);
const distH = (gridW / 2 + margin) / (Math.tan(halfFov) * camera.aspect);
camera.position.set(0, centerY, Math.max(18, Math.max(distV, distH) * 1.1));
controls.target.set(0, centerY, 0);
controls.update();

const beadObjects = [];
const labelsEl = document.getElementById("labels");
labelsEl.style.gridTemplateColumns = `repeat(${COLS}, 1fr)`;

BEADS.forEach((bead, i) => {
  const bin = atob(bead.b64);
  const bytes = new Uint8Array(bin.length);
  for (let j = 0; j < bin.length; j++) bytes[j] = bin.charCodeAt(j);
  const col = i % COLS;
  const row = Math.floor(i / COLS);
  loader.parse(bytes.buffer, "", (gltf) => {
    const obj = gltf.scene;
    obj.position.set(-gridW / 2 + col * spacing, 3 + gridH - row * spacing, 0);
    group.add(obj);
    beadObjects.push(obj);
  });
  const lbl = document.createElement("div");
  lbl.textContent = bead.label;
  labelsEl.appendChild(lbl);
});

const floor = new THREE.Mesh(
  new THREE.CircleGeometry(Math.max(30, radius * 2.2), 48),
  new THREE.MeshStandardMaterial({ color: 0xdcdee2, roughness: 0.85 })
);
floor.rotation.x = -Math.PI / 2;
floor.position.y = -0.2;
scene.add(floor);

document.getElementById("envToggle").addEventListener("change", (e) => applyEnv(e.target.checked));
let rotating = true;
document.getElementById("rotateToggle").addEventListener("change", (e) => (rotating = e.target.checked));
document.getElementById("exposure").addEventListener("input", (e) => {
  renderer.toneMappingExposure = parseFloat(e.target.value);
});
document.getElementById("envIntensity").addEventListener("input", (e) => {
  scene.environmentIntensity = parseFloat(e.target.value);
});
document.getElementById("bgLight").addEventListener("input", (e) => {
  setBgLight(parseFloat(e.target.value));
});

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

function animate() {
  requestAnimationFrame(animate);
  // Spin each bead about its own axis rather than orbiting the whole group,
  // so grid positions (and therefore the label legend) stay valid.
  if (rotating) for (const obj of beadObjects) obj.rotation.y += 0.004;
  controls.update();
  renderer.render(scene, camera);
}
animate();
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pairs", nargs="+", help="alternating GLB_PATH LABEL GLB_PATH LABEL ...")
    parser.add_argument("--out", required=True, help="output HTML path")
    parser.add_argument("--columns", type=int, default=0,
                        help="lay the beads out in a grid with this many columns "
                             "(default: all in one row). Useful for A/B comparisons: "
                             "put variants in rows and stones in columns. The camera "
                             "auto-fits whatever grid you ask for.")
    args = parser.parse_args()

    if len(args.pairs) % 2 != 0:
        parser.error("pass GLB_PATH/LABEL pairs, e.g. bead1.glb 'Bead 1' bead2.glb 'Bead 2'")

    beads = []
    for i in range(0, len(args.pairs), 2):
        path, label = args.pairs[i], args.pairs[i + 1]
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        beads.append({"label": label, "b64": b64})

    html = (TEMPLATE
            .replace("__BEADS_JSON__", json.dumps(beads))
            .replace("__COLUMNS__", str(args.columns)))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)

    print(json.dumps({"out": args.out, "bead_count": len(beads),
                      "columns": args.columns or len(beads), "html_bytes": len(html)}, indent=2))


if __name__ == "__main__":
    main()
