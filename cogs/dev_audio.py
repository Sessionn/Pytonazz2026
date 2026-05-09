import asyncio
import logging
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from core.log_colors import tag, b, user
from core.paths import TMP_DIR
from core.permissions import owner_check

log = logging.getLogger("pitonazz.dev_audio")

_OWN = "🔧"
_AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac", ".m4a")
_TMP_PREFIX = "tmp_devplay_"

_LOCAL_FFMPEG_OPTS = {
    "options": "-vn",
}


class DevAudio(commands.Cog):
    """Comandi audio riservati all'owner: riproduce file caricati nel VC."""

    COG_ICON  = "🔧"
    COG_LABEL = "Sviluppo Audio"
    COG_TYPE  = "dev"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(
        self, inter: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            if not inter.response.is_done():
                await inter.response.send_message(
                    "❌ Solo il proprietario del bot può usare questo comando.",
                    ephemeral=True,
                )
        else:
            log.error(tag("DEV_AUDIO", f"command error → {error}"))

    @app_commands.command(
        name="playmp3",
        description=f"{_OWN} Riproduci un file audio caricato nel tuo canale vocale",
    )
    @app_commands.describe(
        file="File audio da riprodurre (MP3, WAV, OGG, FLAC, M4A)",
        volume="Volume 0–100 (default 80)",
    )
    @owner_check
    async def playmp3(
        self,
        inter: discord.Interaction,
        file: discord.Attachment,
        volume: app_commands.Range[int, 0, 100] = 80,
    ):
        await inter.response.defer(ephemeral=True)

        if not inter.user.voice or not inter.user.voice.channel:
            return await inter.followup.send(
                "❌ Devi essere in un canale vocale per usare questo comando.",
                ephemeral=True,
            )

        fname_lower = file.filename.lower()
        if not any(fname_lower.endswith(ext) for ext in _AUDIO_EXTS):
            return await inter.followup.send(
                f"❌ Formato non supportato. Estensioni accettate: `{', '.join(_AUDIO_EXTS)}`",
                ephemeral=True,
            )

        voice_channel = inter.user.voice.channel
        tmp_path = TMP_DIR / f"{_TMP_PREFIX}{inter.id}{os.path.splitext(file.filename)[1]}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(file.url) as resp:
                    if resp.status != 200:
                        return await inter.followup.send(
                            f"❌ Download fallito (HTTP {resp.status}).", ephemeral=True
                        )
                    with open(tmp_path, "wb") as fp:
                        fp.write(await resp.read())

            vc: discord.VoiceClient | None = inter.guild.voice_client
            if vc:
                if vc.channel != voice_channel:
                    await vc.move_to(voice_channel)
                if vc.is_playing():
                    vc.stop()
                    await asyncio.sleep(0.3)
            else:
                vc = await voice_channel.connect()

            source = discord.FFmpegPCMAudio(str(tmp_path), **_LOCAL_FFMPEG_OPTS)
            source = discord.PCMVolumeTransformer(source, volume=volume / 100)

            def _after(error):
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                if error:
                    log.error(tag("DEV_AUDIO", f"errore riproduzione → {error}"))
                    return
                asyncio.run_coroutine_threadsafe(vc.disconnect(), self.bot.loop)

            vc.play(source, after=_after)

            log.info(tag(
                "DEV_AUDIO",
                f"play  {b(file.filename)}  vol={volume}%  "
                f"vc={b(voice_channel.name)}  by={user(str(inter.user))}",
            ))
            await inter.followup.send(
                f"▶️ **In riproduzione:** `{file.filename}`\n"
                f"🔊 Volume: `{volume}%` · 📢 {voice_channel.mention}",
                ephemeral=True,
            )

        except Exception as exc:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            log.error(tag("DEV_AUDIO", f"eccezione → {exc}"))
            await inter.followup.send(f"❌ Errore: `{exc}`", ephemeral=True)

    @app_commands.command(
        name="stopmp3",
        description=f"{_OWN} Ferma la riproduzione e disconnette il bot dal VC",
    )
    @owner_check
    async def stopmp3(self, inter: discord.Interaction):
        vc: discord.VoiceClient | None = inter.guild.voice_client
        if vc and vc.is_connected():
            if vc.is_playing():
                vc.stop()
            await vc.disconnect()
            log.info(tag("DEV_AUDIO", f"stop+disconnect  by={user(str(inter.user))}"))
            await inter.response.send_message(
                "⏹️ Riproduzione fermata · bot disconnesso.", ephemeral=True
            )
        else:
            await inter.response.send_message(
                "❌ Il bot non è connesso a nessun canale vocale.", ephemeral=True
            )

    @app_commands.command(
        name="skipmp3",
        description=f"{_OWN} Interrompe il file corrente (senza disconnettere)",
    )
    @owner_check
    async def skipmp3(self, inter: discord.Interaction):
        vc: discord.VoiceClient | None = inter.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            log.info(tag("DEV_AUDIO", f"skip  by={user(str(inter.user))}"))
            await inter.response.send_message(
                "⏭️ Riproduzione interrotta.", ephemeral=True
            )
        else:
            await inter.response.send_message(
                "❌ Nessuna riproduzione in corso.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(DevAudio(bot))
