"""Exercise presence reconstruction without importing main's bootstrap."""
import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import discord

tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'saved_presence')
cfg = SimpleNamespace(last_presence=None)
namespace = {'cfg': cfg, 'discord': discord, 'log': Mock(), 'tag': lambda *args: args}
exec(compile(ast.Module(body=[function], type_ignores=[]), 'main.py', 'exec'), namespace)
restore = namespace['saved_presence']
assert restore() is None
for status in ['online', 'idle', 'dnd', 'invisible']:
    for activity in [discord.Game('Gioco'), discord.CustomActivity(name='Testo'),
                     discord.Activity(type=discord.ActivityType.listening, name='Musica'),
                     discord.Streaming(name='Live', url='https://twitch.tv/example')]:
        cfg.last_presence = {'status': status, 'activity': activity.to_dict()}
        restored = restore()
        assert str(restored['status']) == status
        assert restored['activity'].name == activity.name
        assert restored['activity'].type == activity.type
        if isinstance(activity, discord.Streaming):
            assert restored['activity'].url == activity.url
cfg.last_presence = {'status': 'invalid', 'activity': None}
assert restore() is None
cfg.last_presence = {'status': 'online', 'activity': None}
assert restore() is None
cfg.last_presence = {'status': 'online', 'activity': 'invalid'}
assert restore() is None
print('OK: stored presence types, visibility, streaming URL and malformed fallback')
