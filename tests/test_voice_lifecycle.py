"""Regression checks: reconnect must not be treated as a final disconnect."""
import ast
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

_path = Path(__file__).resolve().parents[1] / "core/music/voice_lifecycle.py"
_spec = importlib.util.spec_from_file_location("voice_lifecycle", _path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
voice_session_ended = _module.voice_session_ended


class VoiceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def check_transition(self, outcome, expected):
        client = SimpleNamespace(is_connected=lambda: False)
        guild = SimpleNamespace(voice_client=client)

        async def advance(_):
            outcome(guild, client)

        with patch.object(_module.asyncio, "sleep", side_effect=advance):
            self.assertEqual(await voice_session_ended(guild, client, attempts=2), expected)

    async def test_recovered_client_preserves_queue(self):
        await self.check_transition(lambda g, c: setattr(c, "is_connected", lambda: True), False)

    async def test_removed_client_ends_session(self):
        await self.check_transition(lambda g, c: setattr(g, "voice_client", None), True)

    async def test_replacement_client_preserves_session(self):
        await self.check_transition(lambda g, c: setattr(g, "voice_client", object()), False)

    async def test_slow_reconnect_preserves_queue(self):
        await self.check_transition(lambda g, c: None, False)

    async def test_listener_only_stops_original_player_after_final_leave(self):
        # Execute the actual listener without importing the bot's network services.
        path = Path(__file__).resolve().parents[1] / "cogs/music/__init__.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Music")
        method = next(n for n in cls.body if getattr(n, "name", "") == "on_voice_state_update")
        method.decorator_list = []
        for ended, replace in [(False, False), (True, False), (True, True)]:
            with self.subTest(ended=ended, replace=replace):
                player = Mock()
                cog = SimpleNamespace(
                    bot=SimpleNamespace(user=SimpleNamespace(id=7)),
                    _players={1: player}, _cancel_empty_task=Mock(),
                    _trigger_cancel=Mock(), _notify_dj_state_change=Mock(),
                )
                async def transition(*args):
                    if replace:
                        cog._players[1] = Mock()
                    return ended
                namespace = {"voice_session_ended": transition, "log": Mock(), "tag": lambda *a: a}
                exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
                member = SimpleNamespace(id=7, guild=SimpleNamespace(id=1, voice_client=Mock()))
                await namespace["on_voice_state_update"](
                    cog, member, SimpleNamespace(channel=object()), SimpleNamespace(channel=None)
                )
                self.assertEqual(player.stop.called, ended and not replace)
                self.assertEqual(cog._trigger_cancel.called, ended and not replace)
                self.assertEqual(1 in cog._players, not (ended and not replace))


if __name__ == "__main__":
    unittest.main()
