"""Validate the exported mesh and texture headers without Blender or Pillow."""
from pathlib import Path
import array
import json
import math
import struct
import sys

root=Path(__file__).resolve().parents[1]
assets=root/'data/database/dashboard/static/models/python'
data=(assets/'python.mesh').read_bytes()
magic,vertices,count=struct.unpack_from('<4sII',data)
assert magic==b'PYT1' and 0<vertices<65536 and count%3==0
assert len(data)==12+vertices*40+count*2
floats=array.array('f',data[12:12+vertices*40])
indices=array.array('H',data[12+vertices*40:])
if sys.byteorder!='little':floats.byteswap();indices.byteswap()
assert max(indices)<vertices
assert all(math.isfinite(value) for value in floats)
for offset in range(0,len(floats),10):
    assert 0<=floats[offset+6]<=1
    assert all(0<=floats[offset+i]<=1 for i in (7,8))
    assert floats[offset+9] in range(5)
manifest=json.loads((assets/'manifest.json').read_text())
assert manifest['vertices']==vertices and manifest['triangles']==count//3
for name in ('skin.webp','normal.webp'):
    image=(assets/name).read_bytes()
    assert image[:4]==b'RIFF' and image[8:12]==b'WEBP'
assert sum(p.stat().st_size for p in assets.iterdir() if p.is_file())<4_000_000
print('OK: Blender mesh integrity, finite rig/UV attributes, texture format and transfer budget')
