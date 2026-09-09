#!/usr/bin/env python3
"""Structural validator for the hand-rolled .glb output (no external gltf libs available)."""
import json
import struct
import sys



def _metal_coverage(png_bytes, metal_factor):
    """Fraction of the surface whose effective metalness exceeds 0.5.

    The metallic mask is the BLUE channel of the metallicRoughness texture,
    multiplied by metallicFactor. Returns None if Pillow/NumPy are missing,
    so the validator still works as a pure-stdlib structural check.
    """
    try:
        import io
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    b = np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGB"))[:, :, 2] / 255.0
    return float((b * metal_factor > 0.5).mean())

def validate(path):
    with open(path, "rb") as f:
        data = f.read()

    magic, version, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, f"bad magic: {magic:#x}"
    assert version == 2, f"bad version: {version}"
    assert length == len(data), f"length field {length} != actual file size {len(data)}"

    offset = 12
    chunks = {}
    while offset < len(data):
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk_data = data[offset:offset + chunk_len]
        assert len(chunk_data) == chunk_len
        chunks[chunk_type] = chunk_data
        offset += chunk_len
    assert offset == len(data), "trailing bytes after last chunk"

    JSON_TYPE, BIN_TYPE = 0x4E4F534A, 0x004E4942
    assert JSON_TYPE in chunks, "missing JSON chunk"
    gltf = json.loads(chunks[JSON_TYPE])
    assert gltf["asset"]["version"] == "2.0"

    bin_data = chunks.get(BIN_TYPE, b"")
    total_buffer_len = sum(b["byteLength"] for b in gltf["buffers"])
    assert total_buffer_len == len(bin_data), (
        f"declared buffer length {total_buffer_len} != BIN chunk length {len(bin_data)}"
    )

    # cross-check every accessor's bufferView slice is in range, and indices
    # reference valid vertices
    n_vertices = None
    for i, acc in enumerate(gltf["accessors"]):
        bv = gltf["bufferViews"][acc["bufferView"]]
        end = bv["byteOffset"] + bv["byteLength"]
        assert end <= len(bin_data), f"accessor {i} bufferView out of range"
        if acc["type"] == "VEC3" and acc.get("componentType") == 5126 and "min" in acc:
            n_vertices = acc["count"]

    mesh = gltf["meshes"][0]["primitives"][0]
    idx_acc = gltf["accessors"][mesh["indices"]]
    idx_bv = gltf["bufferViews"][idx_acc["bufferView"]]
    idx_bytes = bin_data[idx_bv["byteOffset"]:idx_bv["byteOffset"] + idx_bv["byteLength"]]
    indices = struct.unpack(f"<{idx_acc['count']}I", idx_bytes[:idx_acc["count"] * 4])
    assert max(indices) < n_vertices, "index references out-of-range vertex"
    assert len(indices) % 3 == 0, "index count not a multiple of 3 (triangles)"

    mat = gltf["materials"][0]
    # Every one of these is OPTIONAL in glTF 2.0, with a spec default. This
    # validator is also pointed at third-party files, so it must not KeyError
    # on a legal one that simply omits them.
    pbr = mat.get("pbrMetallicRoughness", {})
    rgba = pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0])
    assert len(rgba) == 4 and all(0 <= c <= 1 for c in rgba)
    rough_factor = pbr.get("roughnessFactor", 1.0)
    metal_factor = pbr.get("metallicFactor", 1.0)

    def read_texture(ref, label):
        """Decode an embedded texture, checking its bufferView is in bounds.

        The accessor loop bounds-checks its views; images were not, so an
        over-long byteLength silently truncated and the PNG magic still
        matched at the front.
        """
        tex = gltf["textures"][ref["index"]]
        img = gltf["images"][tex["source"]]
        img_bv = gltf["bufferViews"][img["bufferView"]]
        start = img_bv.get("byteOffset", 0)
        end = start + img_bv["byteLength"]
        assert end <= len(bin_data), (
            f"{label} image bufferView runs past the end of the binary chunk "
            f"({end} > {len(bin_data)})")
        img_bytes = bin_data[start:end]
        assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n", f"{label} embedded image is not a valid PNG"
        if "sampler" in tex:
            assert gltf["samplers"][tex["sampler"]] is not None
        return img_bytes

    def check_texture_ref(ref, label):
        read_texture(ref, label)
        return True

    has_texture = "baseColorTexture" in pbr and check_texture_ref(pbr["baseColorTexture"], "baseColorTexture")
    has_rough_tex = "metallicRoughnessTexture" in pbr and check_texture_ref(pbr["metallicRoughnessTexture"], "metallicRoughnessTexture")
    has_normal_tex = "normalTexture" in mat and check_texture_ref(mat["normalTexture"], "normalTexture")

    # Scalar ranges the glTF spec constrains. The generator clamps these, but
    # checking here catches hand-edited or third-party files too -- an
    # out-of-range factor is invalid glTF that still loads in some viewers.
    assert 0.0 <= rough_factor <= 1.0, f"roughnessFactor out of range: {rough_factor}"
    assert 0.0 <= metal_factor <= 1.0, f"metallicFactor out of range: {metal_factor}"
    ext = mat.get("extensions", {})
    has_trans_tex = False
    if "KHR_materials_transmission" in ext:
        tr = ext["KHR_materials_transmission"]
        t = tr["transmissionFactor"]
        assert 0.0 <= t <= 1.0, f"transmissionFactor out of range: {t}"
        if "transmissionTexture" in tr:
            has_trans_tex = check_texture_ref(tr["transmissionTexture"], "transmissionTexture")
    # Stone is a dielectric; only its inclusions are ever metal. So a bead
    # whose surface comes out MOSTLY metallic is a mistake every time -- most
    # often --metallic-inclusions pointed at the wrong end of the pattern
    # field. Checking the factor alone missed this: the factor is legitimately
    # 1.0 and the mask lives in the texture's blue channel, so the mask is
    # what has to be measured.
    metal_coverage = None
    if metal_factor > 0:
        if not has_rough_tex:
            raise AssertionError(
                f"metallicFactor={metal_factor} with no metallicRoughnessTexture: "
                "the entire bead would render as solid metal")
        metal_coverage = _metal_coverage(read_texture(pbr["metallicRoughnessTexture"],
                                                      "metallicRoughnessTexture"), metal_factor)
        if metal_coverage is not None and metal_coverage > 0.60:
            raise AssertionError(
                f"{metal_coverage*100:.0f}% of the surface is metallic. Stone beads are "
                "dielectric with metallic inclusions, not the reverse -- most likely "
                "--metallic-inclusions is set to the wrong end of the pattern field "
                "(speckle puts inclusions at the 'dark' end), or --metallic-threshold "
                "is too permissive.")
    if "KHR_materials_anisotropy" in ext:
        a = ext["KHR_materials_anisotropy"]["anisotropyStrength"]
        assert 0.0 <= a <= 1.0, f"anisotropyStrength out of range: {a}"
    if "KHR_materials_ior" in ext:
        assert ext["KHR_materials_ior"]["ior"] >= 1.0, "ior must be >= 1"

    volume = ext.get("KHR_materials_volume")
    if volume:
        if "attenuationColor" in volume:
            assert len(volume["attenuationColor"]) == 3 and all(0 <= c <= 1 for c in volume["attenuationColor"])
        # Spec: thicknessFactor minimum 0, attenuationDistance exclusiveMinimum 0.
        # A zero distance is a divide-by-zero in the renderer's volume math.
        assert volume.get("thicknessFactor", 0.0) >= 0.0, \
            f"thicknessFactor must be >= 0: {volume.get('thicknessFactor')}"
        if "attenuationDistance" in volume:
            assert volume["attenuationDistance"] > 0.0, \
                f"attenuationDistance must be > 0: {volume['attenuationDistance']}"

    print(f"OK  {path}")
    print(f"    vertices={n_vertices}  triangles={len(indices)//3}  "
          f"material='{mat['name']}'  baseColor(linear)={[round(c,3) for c in rgba]}  "
          f"roughness={pbr['roughnessFactor']}  baseColorTex={'yes' if has_texture else 'no'}  "
          f"roughnessTex={'yes' if has_rough_tex else 'no'}  normalTex={'yes' if has_normal_tex else 'no'}  "
          f"metallic={metal_factor}"
          f"{f' (masked, {metal_coverage*100:.1f}% coverage)' if metal_coverage is not None else ''}  "
          f"transmissionTex={'yes' if has_trans_tex else 'no'}  "
          f"extensions={gltf.get('extensionsUsed', [])}")
    if volume:
        print(f"    volume: attenuationDistance={volume.get('attenuationDistance')}  "
              f"attenuationColor={volume.get('attenuationColor')}")
    pos_acc = gltf["accessors"][0]
    size = [pos_acc["max"][i] - pos_acc["min"][i] for i in range(3)]
    print(f"    bounding box size (mm) = {[round(s,3) for s in size]}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        validate(p)
