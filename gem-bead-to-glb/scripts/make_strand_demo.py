#!/usr/bin/env python3
"""
Strand demo: string N drilled beads on a cord and randomise each one, while
shipping only ONE .glb per stone type.

The point: the baked textures are seamlessly tileable, so a per-bead UV offset
reveals a completely different region of the inclusion pattern at zero asset
cost. Combined with spin, size jitter and a colour multiplier, a strand of
identical meshes stops reading as a clone army.

Note on drilled beads: once the bead has a real hole, its orientation is no
longer free -- the hole must stay on the cord axis, so the only rotation left
is a spin about that axis. That makes the UV offset MORE important, not less,
because rotation alone can no longer disguise repetition.

Usage:
    python3 make_strand_demo.py a.glb "标签A" b.glb "标签B" ... --out strand.html
"""
import argparse
import base64
import json

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8" />
<title>珠串随机化演示</title>
<style>
  html, body { margin:0; height:100%; background:#eceef0; color:#222;
    font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; overflow:hidden; }
  #ui { position:fixed; top:12px; left:12px; z-index:10; background:rgba(255,255,255,.94);
    padding:14px 18px; border-radius:10px; max-width:400px; line-height:1.55; font-size:13px;
    box-shadow:0 2px 12px rgba(0,0,0,.15); }
  #ui h1 { font-size:15px; margin:0 0 10px; }
  #ui label { display:flex; align-items:center; gap:8px; margin:7px 0; cursor:pointer; }
  #ui p { margin:10px 0 0; color:#666; }
  #ui select, #ui button { padding:5px 10px; font-size:13px; border:1px solid #bbb;
    border-radius:6px; background:#fff; cursor:pointer; }
  #ui button { margin-top:10px; }
  #ui button:hover { background:#f2f2f2; }
  .k { flex:0 0 100px; color:#555; }
  #status { position:fixed; bottom:14px; left:50%; transform:translateX(-50%); z-index:10;
    background:rgba(255,255,255,.9); padding:8px 16px; border-radius:8px; font-size:13px; color:#444; }
  canvas { display:block; }
</style>
</head>
<body>
<div id="ui">
  <h1>珠串随机化演示</h1>
  <label><span class="k">石头</span><select id="stone"></select></label>
  <label><input type="checkbox" id="uv" checked /> 随机 UV 偏移（换纹理区域）</label>
  <label><input type="checkbox" id="spin" checked /> 随机自转（绕穿绳轴）</label>
  <label><input type="checkbox" id="scl" checked /> 随机大小 ±3%</label>
  <label><input type="checkbox" id="tint" checked /> 随机色调深浅</label>
  <label><input type="checkbox" id="cord" checked /> 显示绳子</label>
  <label><span class="k">曝光</span><input type="range" id="exposure" min="0.4" max="3" step="0.05" value="1.6" /></label>
  <button id="reroll">重新随机</button>
  <p>四个随机项全部取消勾选＝现在的做法（每颗完全相同）。珠子有真实穿孔，所以朝向被绳子锁住，只能绕绳轴自转——这也是为什么 UV 偏移比旋转更关键。<b>全部共用同一个 .glb</b>。</p>
</div>
<div id="status">载入中…</div>

<script type="importmap">
{"imports":{
  "three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
  "three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}
</script>
<script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const BEADS = __BEADS_JSON__;
const COUNT = 20;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, innerWidth/innerHeight, 0.1, 500);
const renderer = new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.6;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 1.8;
scene.background = new THREE.Color(0xe6e8ea);

const key = new THREE.DirectionalLight(0xffffff, 2.4); key.position.set(5,10,7); scene.add(key);
const fill = new THREE.DirectionalLight(0xffffff, 1.0); fill.position.set(-6,4,-5); scene.add(fill);
scene.add(new THREE.AmbientLight(0xffffff, .5));

const group = new THREE.Group();
scene.add(group);

const statusEl = document.getElementById("status");
const stoneSel = document.getElementById("stone");
BEADS.forEach((b,i) => {
  const o = document.createElement("option");
  o.value = i; o.textContent = b.label;
  stoneSel.appendChild(o);
});

function bytesFrom(b64){
  const bin = atob(b64), a = new Uint8Array(bin.length);
  for (let i=0;i<bin.length;i++) a[i]=bin.charCodeAt(i);
  return a.buffer;
}

const loader = new GLTFLoader();
const cache = new Map();
let beads = [];
let cordMesh = null;
let ringR = 40;

function loadStone(idx){
  if (cache.has(idx)) { build(cache.get(idx), idx); return; }
  statusEl.textContent = "载入中…";
  loader.parse(bytesFrom(BEADS[idx].b64), "", (gltf) => {
    let src = null;
    gltf.scene.traverse(o => { if (o.isMesh && !src) src = o; });
    cache.set(idx, src);
    build(src, idx);
  });
}

function build(srcMesh, idx){
  group.clear();
  beads = [];

  const box = new THREE.Box3().setFromObject(srcMesh);
  const dia = box.getSize(new THREE.Vector3()).x || 8;
  ringR = (dia * COUNT) / (2 * Math.PI) * 1.02;

  const up = new THREE.Vector3(0,1,0);
  for (let i=0;i<COUNT;i++){
    const mesh = new THREE.Mesh(srcMesh.geometry, srcMesh.material.clone());

    // transmissionMap belongs in this list too: a metallic-inclusion bead
    // carries one, and leaving it at offset (0,0) while the others move gives
    // transparent needles floating over opaque quartz.
    // Clone each map so this bead carries its OWN uv offset. Texture.clone()
    // shares the underlying Source, so the image uploads to the GPU once --
    // 20 beads cost 20 small Texture objects, not 20 copies of a 1024px image.
    for (const slot of ["map","roughnessMap","metalnessMap","normalMap","transmissionMap"]){
      if (mesh.material[slot]) {
        mesh.material[slot] = mesh.material[slot].clone();
        mesh.material[slot].wrapS = mesh.material[slot].wrapT = THREE.RepeatWrapping;
      }
    }

    const a = (i/COUNT) * Math.PI * 2;
    mesh.position.set(Math.cos(a)*ringR, 0, Math.sin(a)*ringR);
    // The drill channel runs along the mesh's local +Y, so align local +Y with
    // the ring tangent and the cord threads straight through every bead.
    const tangent = new THREE.Vector3(-Math.sin(a), 0, Math.cos(a));
    mesh.quaternion.setFromUnitVectors(up, tangent);
    mesh.userData.baseQuat = mesh.quaternion.clone();
    group.add(mesh);
    beads.push(mesh);
  }

  if (cordMesh) { cordMesh.geometry.dispose(); cordMesh.material.dispose(); }
  cordMesh = new THREE.Mesh(
    new THREE.TorusGeometry(ringR, 0.42, 12, 220),
    new THREE.MeshStandardMaterial({color:0x9a8b7a, roughness:0.85})
  );
  cordMesh.rotation.x = Math.PI/2;
  group.add(cordMesh);

  camera.position.set(0, ringR*1.1, ringR*2.0);
  controls.target.set(0,0,0);
  controls.update();

  statusEl.textContent = `${BEADS[idx].label} · ${COUNT} 颗 · 共用 1 个 .glb`;
  reroll();
}

function reroll(){
  const useUV   = document.getElementById("uv").checked;
  const useSpin = document.getElementById("spin").checked;
  const useScl  = document.getElementById("scl").checked;
  const useTint = document.getElementById("tint").checked;
  if (cordMesh) cordMesh.visible = document.getElementById("cord").checked;

  const spinAxis = new THREE.Vector3(0,1,0);
  beads.forEach((m) => {
    // Every map must share the SAME offset, or colour, roughness and normal
    // detail drift apart and one bead looks like three stones overlaid.
    const ou = useUV ? Math.random() : 0;
    const ov = useUV ? Math.random() : 0;
    for (const slot of ["map","roughnessMap","metalnessMap","normalMap","transmissionMap"]){
      if (m.material[slot]) m.material[slot].offset.set(ou, ov);
    }

    // Spin about the cord axis only -- a threaded bead has exactly one
    // rotational degree of freedom left.
    m.quaternion.copy(m.userData.baseQuat);
    if (useSpin) {
      m.quaternion.multiply(
        new THREE.Quaternion().setFromAxisAngle(spinAxis, Math.random()*Math.PI*2));
    }

    m.scale.setScalar(useScl ? 1 + (Math.random()-0.5)*0.06 : 1);

    // A mild multiplier stands in for the density differences that make some
    // beads in a real strand read darker or milkier than their neighbours.
    if (useTint){
      const t = 0.88 + Math.random()*0.24;
      m.material.color.setRGB(t, t*(0.985+Math.random()*0.03), t*(0.985+Math.random()*0.03));
    } else {
      m.material.color.setRGB(1,1,1);
    }
  });
}

for (const id of ["uv","spin","scl","tint","cord"])
  document.getElementById(id).addEventListener("change", reroll);
document.getElementById("reroll").addEventListener("click", reroll);
document.getElementById("stone").addEventListener("change", e => loadStone(+e.target.value));
document.getElementById("exposure").addEventListener("input", e => {
  renderer.toneMappingExposure = parseFloat(e.target.value);
});

addEventListener("resize", () => {
  camera.aspect = innerWidth/innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

loadStone(0);

(function animate(){
  requestAnimationFrame(animate);
  group.rotation.y += 0.0022;
  controls.update();
  renderer.render(scene, camera);
})();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pairs", nargs="+", help="alternating GLB_PATH LABEL ...")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if len(args.pairs) % 2:
        ap.error("pass GLB_PATH/LABEL pairs")

    beads = []
    for i in range(0, len(args.pairs), 2):
        with open(args.pairs[i], "rb") as f:
            beads.append({"label": args.pairs[i + 1],
                          "b64": base64.b64encode(f.read()).decode("ascii")})

    html = TEMPLATE.replace("__BEADS_JSON__", json.dumps(beads))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(json.dumps({"out": args.out, "stones": len(beads), "html_bytes": len(html)}, indent=2))


if __name__ == "__main__":
    main()
