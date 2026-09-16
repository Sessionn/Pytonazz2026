"""Keep music state while discord.py still owns a recovering voice client."""
import asyncio


async def voice_session_ended(guild, previous_client, *, attempts=90):
    # A gateway leave event also occurs during disconnect(cleanup=False).
    # Allow the voice protocol to process that event before inspecting ownership.
    for _ in range(attempts):
        await asyncio.sleep(1)
        current = guild.voice_client
        if current is None:
            return True
        if current is not previous_client or current.is_connected():
            return False
    # A slow recovery is not permission to destroy the user's queue.
    return False
