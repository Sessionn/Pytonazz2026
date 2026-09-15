"""Regression tests for birthday removal, using only temporary storage."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs import birthdays
from core import birthday_store


class BirthdayRemovalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        store_patch = patch.object(birthday_store, "_DATA_PATH", Path(self.temp.name) / "birthdays.json")
        store_patch.start()
        self.addCleanup(store_patch.stop)
        self.cog = object.__new__(birthdays.Birthdays)
        self.guild = SimpleNamespace(id=123, get_member=lambda uid: None)
        self.inter = SimpleNamespace(
            guild_id=123, guild=self.guild,
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        self.uid = 123456789012345678

    async def remove(self, **kwargs):
        await birthdays.Birthdays.bday_adminremove.callback(self.cog, self.inter, **kwargs)

    async def test_missing_member_removed_by_id_only_in_current_guild(self):
        birthday_store.set_birthday(123, self.uid, 2, 3, None)
        birthday_store.set_birthday(456, self.uid, 2, 3, None)
        with patch.object(birthdays, "_refresh_list_in_channel", new_callable=AsyncMock) as refresh:
            await self.remove(utente_id=str(self.uid))
            await asyncio.sleep(0)
            refresh.assert_awaited_once_with(self.guild)
        self.assertIsNone(birthday_store.get_birthday(123, self.uid))
        self.assertIsNotNone(birthday_store.get_birthday(456, self.uid))
        self.assertTrue(self.inter.response.send_message.call_args.kwargs["ephemeral"])

    async def test_existing_member_still_supported(self):
        birthday_store.set_birthday(123, self.uid, 2, 3, None)
        with patch.object(birthdays, "_refresh_list_in_channel", new_callable=AsyncMock):
            await self.remove(utente=SimpleNamespace(id=self.uid, display_name="Test"))
            await asyncio.sleep(0)
        self.assertIsNone(birthday_store.get_birthday(123, self.uid))

    async def test_invalid_or_ambiguous_input_does_not_remove(self):
        inputs = [{}, {"utente_id": "abc"}, {"utente_id": "0"},
                  {"utente_id": str(2**64)}, {"utente_id": "１２３"},
                  {"utente_id": str(self.uid), "utente": SimpleNamespace(id=self.uid)}]
        with patch.object(birthdays, "remove_birthday") as remove:
            for kwargs in inputs:
                await self.remove(**kwargs)
            remove.assert_not_called()

    async def test_unknown_id_reports_missing_without_refresh(self):
        with patch.object(birthdays, "_refresh_list_in_channel", new_callable=AsyncMock) as refresh:
            await self.remove(utente_id=str(self.uid))
            await asyncio.sleep(0)
            refresh.assert_not_called()
        embed = self.inter.response.send_message.call_args.kwargs["embed"]
        self.assertIn("Nessun compleanno", embed.description)

    def test_list_shows_copyable_id_for_missing_member(self):
        embeds = birthdays._build_list_embeds(
            self.guild, {str(self.uid): {"day": 2, "month": 3, "year": None}}
        )
        self.assertIn(f"ID: `{self.uid}`", embeds[0].description)

    async def test_last_removal_clears_published_list(self):
        birthday_store.set_channel(123, 999)
        birthday_store.set_list_message_id(123, 888)
        message = SimpleNamespace(delete=AsyncMock())
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message), send=AsyncMock())
        self.guild.get_channel = lambda cid: channel
        await birthdays._refresh_list_in_channel(self.guild)
        channel.fetch_message.assert_awaited_once_with(888)
        message.delete.assert_awaited_once()
        channel.send.assert_not_called()
        self.assertIsNone(birthday_store.get_list_message_id(123))


if __name__ == "__main__":
    unittest.main()
