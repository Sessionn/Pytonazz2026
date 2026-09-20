"""Package the Blender atlas for the web. Requires Pillow only for asset builds."""
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[2]
assets = root / 'data/database/dashboard/static/models/python'
source = root / 'assets/python'
for name in ('skin', 'normal'):
    image = Image.open(assets / f'{name}.png').convert('RGB')
    image.save(assets / f'{name}.webp', 'WEBP', lossless=name == 'normal', quality=92, method=6)
    # Masters belong with the editable scene; the server only needs WebP.
    (source / f'{name}.png').write_bytes((assets / f'{name}.png').read_bytes())
    (assets / f'{name}.png').unlink()
(source / 'python.glb').write_bytes((assets / 'python.glb').read_bytes())
(assets / 'python.glb').unlink()
