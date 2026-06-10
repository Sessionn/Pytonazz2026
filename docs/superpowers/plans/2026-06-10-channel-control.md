# Channel Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add dev-level maintenance/restart access, persistent channel controls, and regression checks for playlist URL support.

**Architecture:** Keep runtime configuration in `core.bot_config.BotConfig`, add a focused `cogs.channel_control` command group, and enforce restrictions centrally from `main.py` for slash commands and normal messages. Playlist support stays in the existing music input/resolver path with tests guarding URL classification.

**Tech Stack:** Python, discord.py app commands, existing script-style tests.

---

### Task 1: Regression Tests

**Files:**
- Create: `tests/test_dev_permissions_static.py`
- Create: `tests/test_channel_control_config.py`
- Create: `tests/test_music_playlist_links.py`

- [ ] Write static tests proving `/restart` and `/maintenance` use `@dev_check`.
- [ ] Write BotConfig tests for setting, listing, and removing channel controls.
- [ ] Write input tests proving YouTube, Spotify, and SoundCloud playlist-style links are multi URLs.
- [ ] Run each new test and confirm it fails for the missing behavior.

### Task 2: Runtime Config

**Files:**
- Modify: `core/bot_config.py`

- [ ] Add `channel_controls` to defaults.
- [ ] Add `channel_controls_for_guild`, `get_channel_control`, `set_channel_control`, and `remove_channel_control`.
- [ ] Keep persistence through the existing `_persist()` method.

### Task 3: Dev Commands

**Files:**
- Modify: `cogs/dev.py`
- Create: `cogs/channel_control.py`
- Modify: `core/runtime.py`

- [ ] Replace `owner_check` with `dev_check` for `/restart` and `/maintenance`.
- [ ] Add `/channel_control set`, `/channel_control remove`, and `/channel_control list`.
- [ ] Register `cogs.channel_control` in `DEFAULT_COGS`.

### Task 4: Enforcement

**Files:**
- Modify: `main.py`

- [ ] Add an app command check that rejects bot commands in channels configured as `no_bot_commands`.
- [ ] Add an `on_message` handler that deletes normal user messages in channels configured as `bot_commands_only`.
- [ ] Preserve existing cog `on_message` listeners by not replacing listener behavior.

### Task 5: Verification

**Files:**
- Run tests only.

- [ ] Run the new tests.
- [ ] Run existing maintenance and SoundCloud routing tests.
- [ ] Run `python -m compileall main.py cogs core tests`.
