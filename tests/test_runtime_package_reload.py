"""Package changes reload their owning extension, with retry on failure."""
import asyncio
import logging
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core import runtime


async def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        package = root / 'music'
        package.mkdir()
        entry = package / '__init__.py'
        entry.write_text('')
        shard = package / 'queue.py'
        shard.write_text('one')
        legacy = root / 'legacy.py'
        legacy.write_text('')
        paths = {'cogs.music': entry, 'cogs.legacy': legacy}
        bot = AsyncMock()
        logger = logging.getLogger('test')
        with patch.object(runtime, 'cog_path', side_effect=paths.__getitem__):
            previous = runtime.snapshot_extension_mtimes(list(paths))
            shard.unlink()
            (package / 'batch.py').write_text('new')
            bot.reload_extension.side_effect = RuntimeError('retry')
            failed = await runtime.reload_modified_extensions(bot, list(paths), previous, logger)
            assert failed == previous
            bot.reload_extension.assert_awaited_once_with('cogs.music')
            bot.reload_extension.reset_mock()
            bot.reload_extension.side_effect = None
            current = await runtime.reload_modified_extensions(bot, list(paths), failed, logger)
            bot.reload_extension.assert_awaited_once_with('cogs.music')
            bot.reload_extension.reset_mock()
            await runtime.reload_modified_extensions(bot, list(paths), current, logger)
            bot.reload_extension.assert_not_awaited()
            # Even if the whole package disappears, changes retain their owner.
            paths['cogs.music'] = package.with_suffix('.py')
            assert runtime._extension_owns('cogs.music', str(entry))
    print('OK: package changes, deletions, ownership and retries')


asyncio.run(main())
