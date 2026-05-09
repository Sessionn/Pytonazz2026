import io
import logging
from typing import Optional

import discord
import edge_tts
from discord import app_commands
from discord.ext import commands

from core.bot_config import cfg
from core.log_colors import tag, b, user

log = logging.getLogger("pitonazz.tts")

DEFAULT_VOICE = "it-IT-DiegoNeural"

VOICES = {
    "diego (ita, maschile)":     "it-IT-DiegoNeural",
    "elsa (ita, femminile)":     "it-IT-ElsaNeural",
    "isabella (ita, femminile)": "it-IT-IsabellaNeural",
    "ryan (eng, maschile)":      "en-GB-RyanNeural",
    "aria (eng, femminile)":     "en-US-AriaNeural",
}


async def _synth(text: str, voice: str) -> io.BytesIO:
    buf = io.BytesIO()
    communicate = edge_tts.Communicate(text, voice)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    buf.seek(0)
    return buf


class TTS(commands.Cog):
    COG_ICON  = "🔊"
    COG_LABEL = "Text to Speech"
    COG_TYPE  = "public"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="tts", description="Sintetizza un testo come voce nel canale vocale")
    @app_commands.describe(
        testo="Testo da leggere ad alta voce",
        voce="Voce da usare (default: Diego, italiano maschile)",
    )
    @app_commands.choices(voce=[
        app_commands.Choice(name=k, value=v) for k, v in VOICES.items()
    ])
    async def tts(self, inter: discord.Interaction, testo: str, voce: Optional[str] = None):
        if not inter.guild:
            return await inter.response.send_message(
                "Questo comando funziona solo nei server.", ephemeral=True
            )
        if not inter.user.voice or not inter.user.voice.channel:
            return await inter.response.send_message(
                "Devi essere in un canale vocale!", ephemeral=True
            )
        if len(testo) > 500:
            return await inter.response.send_message(
                "Testo troppo lungo (max 500 caratteri).", ephemeral=True
            )

        voice   = voce or DEFAULT_VOICE
        vc_ch   = inter.user.voice.channel
        volume  = cfg.tts_volume

        await inter.response.defer(ephemeral=True)

        try:
            buf = await _synth(testo, voice)
        except Exception as e:
            log.error(tag("TTS", f"synth error  voce={voice}  → {e}"))
            return await inter.followup.send(f"Errore nella sintesi: `{e}`", ephemeral=True)

        vc = inter.guild.voice_client
        try:
            if vc:
                if vc.channel != vc_ch:
                    await vc.move_to(vc_ch)
            else:
                vc = await vc_ch.connect()
        except Exception as e:
            log.error(tag("TTS", f"connect error  → {e}"))
            return await inter.followup.send(f"Errore connessione vocale: `{e}`", ephemeral=True)

        if vc.is_playing():
            vc.stop()

        raw    = discord.FFmpegPCMAudio(buf, pipe=True)
        source = discord.PCMVolumeTransformer(raw, volume=volume)
        vc.play(source)

        log.info(tag("TTS", f"{b(inter.guild.name)}  voce={voice}  vol={volume}x  utente={user(str(inter.user))}  testo={repr(testo[:60])}"))
        await inter.followup.send("✅ In riproduzione.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TTS(bot))
