#!/usr/bin/env python3
"""Tiny software rasterizer to sanity-render a .glb sphere bead to PNG.

Not part of the skill itself -- this is just a verification aid so a human
(or me) can eyeball that the exported geometry/winding/normals/color are
actually correct, without needing three.js or a GPU.
"""
import json
import struct
import sys
import math
from io import BytesIO
from PIL import Image, ImageDraw


def load_glb(path):
    with open(path, "rb") as f:
        data = f.read()
    offset = 12
    chunks = {}
    while offset < len(data):
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunks[chunk_type] = data[offset:offset + chunk_len]
        offset += chunk_len
    gltf = json.loads(chunks[0x4E4F534A])
    bin_data = chunks[0x004E4942]

    def read_accessor(idx):
        acc = gltf["accessors"][idx]
        bv = gltf["bufferViews"][acc["bufferView"]]
        start = bv["byteOffset"]
        n = acc["count"] * {"VEC3": 3, "VEC2": 2, "SCALAR": 1}[acc["type"]]
        fmt = {5126: "f", 5125: "I"}[acc["componentType"]]
        raw = struct.unpack_from(f"<{n}{fmt}", bin_data, start)
        size = {"VEC3": 3, "VEC2": 2, "SCALAR": 1}[acc["type"]]
        return [raw[i:i + size] for i in range(0, len(raw), size)] if size > 1 else list(raw)

    prim = gltf["meshes"][0]["primitives"][0]
    positions = read_accessor(prim["attributes"]["POSITION"])
    normals = read_accessor(prim["attributes"]["NORMAL"])
    uvs = read_accessor(prim["attributes"]["TEXCOORD_0"]) if "TEXCOORD_0" in prim["attributes"] else None
    indices = read_accessor(prim["indices"])
    mat = gltf["materials"][0]["pbrMetallicRoughness"]
    base_color = mat["baseColorFactor"][:3]

    texture_img = None
    if "baseColorTexture" in mat:
        tex = gltf["textures"][mat["baseColorTexture"]["index"]]
        img_info = gltf["images"][tex["source"]]
        ibv = gltf["bufferViews"][img_info["bufferView"]]
        img_bytes = bin_data[ibv["byteOffset"]:ibv["byteOffset"] + ibv["byteLength"]]
        texture_img = Image.open(BytesIO(img_bytes)).convert("RGB")

    return positions, normals, uvs, indices, base_color, texture_img


def render(path, out_png, size=300):
    positions, normals, uvs, indices, base_color_linear, texture_img = load_glb(path)
    # linear -> sRGB for display
    def lin2srgb(c):
        c = max(0.0, min(1.0, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    base_rgb = tuple(int(255 * lin2srgb(c)) for c in base_color_linear)
    tex_w, tex_h = texture_img.size if texture_img else (0, 0)

    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    r = max(max(map(abs, xs)), max(map(abs, ys))) * 1.15

    def project(p):
        sx = size / 2 + (p[0] / r) * (size / 2)
        sy = size / 2 - (p[1] / r) * (size / 2)
        return sx, sy

    img = Image.new("RGB", (size, size), (24, 24, 28))
    draw = ImageDraw.Draw(img)

    light = (0.4, 0.6, 0.7)
    ll = math.sqrt(sum(c * c for c in light))
    light = tuple(c / ll for c in light)

    tris = []
    for i in range(0, len(indices), 3):
        a, b, c = indices[i], indices[i + 1], indices[i + 2]
        pa, pb, pc = positions[a], positions[b], positions[c]
        avg_z = (pa[2] + pb[2] + pc[2]) / 3
        na, nb, nc = normals[a], normals[b], normals[c]
        n = tuple((na[k] + nb[k] + nc[k]) / 3 for k in range(3))
        nl = math.sqrt(sum(v * v for v in n)) or 1.0
        n = tuple(v / nl for v in n)
        if n[2] <= 0:  # backface (camera looks down -z)
            continue
        intensity = max(0.15, sum(n[k] * light[k] for k in range(3))) * 0.85 + 0.15

        tri_rgb = base_rgb
        if texture_img and uvs:
            ua, ub, uc = uvs[a], uvs[b], uvs[c]
            avg_u = (ua[0] + ub[0] + uc[0]) / 3
            avg_v = (ua[1] + ub[1] + uc[1]) / 3
            tx = min(tex_w - 1, max(0, int(avg_u * tex_w)))
            ty = min(tex_h - 1, max(0, int((1 - avg_v) * tex_h)))
            tri_rgb = texture_img.getpixel((tx, ty))

        color = tuple(min(255, int(ch * intensity)) for ch in tri_rgb)
        tris.append((avg_z, [project(pa), project(pb), project(pc)], color))

    tris.sort(key=lambda t: t[0])  # farthest (smallest z going away from camera) first
    for _, pts, color in tris:
        draw.polygon(pts, fill=color)

    img.save(out_png)
    print(f"rendered {out_png}  ({len(tris)} front-facing triangles)")


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])
