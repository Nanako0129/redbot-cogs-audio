import asyncio
import contextlib
import logging
import os
import tarfile
from pathlib import Path

from typing import Union

import discord
import lavalink

from redbot.core import bank, commands
from redbot.core.data_manager import cog_data_path
from redbot.core.i18n import Translator
from redbot.core.utils.chat_formatting import box, humanize_number
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu, start_adding_reactions
from redbot.core.utils.predicates import MessagePredicate, ReactionPredicate

from ...audio_dataclasses import LocalPath
from ...converters import ScopeParser
from ...errors import MissingGuild, TooManyMatches
from ...utils import CacheLevel, PlaylistScope, has_internal_server
from ..abc import MixinMeta
from ..cog_utils import CompositeMetaClass, PlaylistConverter, __version__

log = logging.getLogger("red.cogs.Audio.cog.Commands.audioset")

_ = Translator("Audio", Path(__file__))


class AudioSetCommands(MixinMeta, metaclass=CompositeMetaClass):
    @commands.group(name="audioset")
    @commands.bot_has_permissions(embed_links=True)
    async def command_audioset(self, ctx: commands.Context):
        """音樂設定選項。"""

    @command_audioset.group(name="restrictions")
    @commands.mod_or_permissions(manage_guild=True)
    async def command_audioset_perms(self, ctx: commands.Context):
        """管理黑名單和白名單的關鍵字。"""

    @commands.is_owner()
    @command_audioset_perms.group(name="global")
    async def command_audioset_perms_global(self, ctx: commands.Context):
        """管理全域白名單/黑名單關鍵字。"""

    @command_audioset_perms_global.group(name="whitelist")
    async def command_audioset_perms_global_whitelist(self, ctx: commands.Context):
        """管理全域白名單關鍵字。"""

    @command_audioset_perms_global_whitelist.command(name="add")
    async def command_audioset_perms_global_whitelist_add(
        self, ctx: commands.Context, *, keyword: str
    ):
        """新增關鍵字到全域白名單。

        如果新增任何內容到全域白名單中，則會將其他所有內容都列入全域黑名單。
        """
        keyword = keyword.lower().strip()
        if not keyword:
            return await ctx.send_help()
        exists = False
        async with self.config.url_keyword_whitelist() as whitelist:
            if keyword in whitelist:
                exists = True
            else:
                whitelist.append(keyword)
        if exists:
            return await self.send_embed_msg(ctx, title=_("Keyword already in the whitelist."))
        else:
            return await self.send_embed_msg(
                ctx,
                title=_("Whitelist Modified"),
                description=_("Added `{whitelisted}` to the whitelist.").format(
                    whitelisted=keyword
                ),
            )

    @command_audioset_perms_global_whitelist.command(name="list")
    @commands.bot_has_permissions(add_reactions=True)
    async def command_audioset_perms_global_whitelist_list(self, ctx: commands.Context):
        """列出所有已新增到白名單中的關鍵字。"""
        whitelist = await self.config.url_keyword_whitelist()
        if not whitelist:
            return await self.send_embed_msg(ctx, title=_("Nothing in the whitelist."))
        whitelist.sort()
        text = ""
        total = len(whitelist)
        pages = []
        for i, entry in enumerate(whitelist, 1):
            text += f"{i}. [{entry}]"
            if i != total:
                text += "\n"
                if i % 10 == 0:
                    pages.append(box(text, lang="ini"))
                    text = ""
            else:
                pages.append(box(text, lang="ini"))
        embed_colour = await ctx.embed_colour()
        pages = list(
            discord.Embed(title=_("Global Whitelist"), description=page, colour=embed_colour)
            for page in pages
        )
        await menu(ctx, pages, DEFAULT_CONTROLS)

    @command_audioset_perms_global_whitelist.command(name="clear")
    async def command_audioset_perms_global_whitelist_clear(self, ctx: commands.Context):
        """清除所有白名單中的關鍵字。"""
        whitelist = await self.config.url_keyword_whitelist()
        if not whitelist:
            return await self.send_embed_msg(ctx, title=_("Nothing in the whitelist."))
        await self.config.url_keyword_whitelist.clear()
        return await self.send_embed_msg(
            ctx,
            title=_("Whitelist Modified"),
            description=_("All entries have been removed from the whitelist."),
        )

    @command_audioset_perms_global_whitelist.command(name="delete", aliases=["del", "remove"])
    async def command_audioset_perms_global_whitelist_delete(
        self, ctx: commands.Context, *, keyword: str
    ):
        """從白名單中移除關鍵字。"""
        keyword = keyword.lower().strip()
        if not keyword:
            return await ctx.send_help()
        exists = True
        async with self.config.url_keyword_whitelist() as whitelist:
            if keyword not in whitelist:
                exists = False
            else:
                whitelist.remove(keyword)
        if not exists:
            return await self.send_embed_msg(ctx, title=_("Keyword already in the whitelist."))
        else:
            return await self.send_embed_msg(
                ctx,
                title=_("Whitelist Modified"),
                description=_("Removed `{whitelisted}` from the whitelist.").format(
                    whitelisted=keyword
                ),
            )

    @command_audioset_perms_global.group(name="blacklist")
    async def command_audioset_perms_global_blacklist(self, ctx: commands.Context):
        """管理全域黑名單關鍵字。"""

    @command_audioset_perms_global_blacklist.command(name="add")
    async def command_audioset_perms_global_blacklist_add(
        self, ctx: commands.Context, *, keyword: str
    ):
        """在黑名單中新增關鍵字。"""
        keyword = keyword.lower().strip()
        if not keyword:
            return await ctx.send_help()
        exists = False
        async with self.config.url_keyword_blacklist() as blacklist:
            if keyword in blacklist:
                exists = True
            else:
                blacklist.append(keyword)
        if exists:
            return await self.send_embed_msg(ctx, title=_("Keyword already in the blacklist."))
        else:
            return await self.send_embed_msg(
                ctx,
                title=_("Blacklist Modified"),
                description=_("Added `{blacklisted}` to the blacklist.").format(
                    blacklisted=keyword
                ),
            )

    @command_audioset_perms_global_blacklist.command(name="list")
    @commands.bot_has_permissions(add_reactions=True)
    async def command_audioset_perms_global_blacklist_list(self, ctx: commands.Context):
        """列出所有已新增到黑名單中的關鍵字。"""
        blacklist = await self.config.url_keyword_blacklist()
        if not blacklist:
            return await self.send_embed_msg(ctx, title=_("Nothing in the blacklist."))
        blacklist.sort()
        text = ""
        total = len(blacklist)
        pages = []
        for i, entry in enumerate(blacklist, 1):
            text += f"{i}. [{entry}]"
            if i != total:
                text += "\n"
                if i % 10 == 0:
                    pages.append(box(text, lang="ini"))
                    text = ""
            else:
                pages.append(box(text, lang="ini"))
        embed_colour = await ctx.embed_colour()
        pages = list(
            discord.Embed(title=_("Global Blacklist"), description=page, colour=embed_colour)
            for page in pages
        )
        await menu(ctx, pages, DEFAULT_CONTROLS)

    @command_audioset_perms_global_blacklist.command(name="clear")
    async def command_audioset_perms_global_blacklist_clear(self, ctx: commands.Context):
        """清除所有黑名單中的關鍵字。"""
        blacklist = await self.config.url_keyword_blacklist()
        if not blacklist:
            return await self.send_embed_msg(ctx, title=_("Nothing in the blacklist."))
        await self.config.url_keyword_blacklist.clear()
        return await self.send_embed_msg(
            ctx,
            title=_("Blacklist Modified"),
            description=_("All entries have been removed from the blacklist."),
        )

    @command_audioset_perms_global_blacklist.command(name="delete", aliases=["del", "remove"])
    async def command_audioset_perms_global_blacklist_delete(
        self, ctx: commands.Context, *, keyword: str
    ):
        """從黑名單中移除關鍵字。"""
        keyword = keyword.lower().strip()
        if not keyword:
            return await ctx.send_help()
        exists = True
        async with self.config.url_keyword_blacklist() as blacklist:
            if keyword not in blacklist:
                exists = False
            else:
                blacklist.remove(keyword)
        if not exists:
            return await self.send_embed_msg(ctx, title=_("Keyword is not in the blacklist."))
        else:
            return await self.send_embed_msg(
                ctx,
                title=_("Blacklist Modified"),
                description=_("Removed `{blacklisted}` from the blacklist.").format(
                    blacklisted=keyword
                ),
            )

    @command_audioset_perms.group(name="whitelist")
    @commands.guild_only()
    async def command_audioset_perms_whitelist(self, ctx: commands.Context):
        """管理白名單關鍵字。"""

    @command_audioset_perms_whitelist.command(name="add")
    async def command_audioset_perms_whitelist_add(self, ctx: commands.Context, *, keyword: str):
        """新增關鍵字到白名單。

        如果新增任何內容到白名單中，則會將其他所有內容都列入黑名單。
        """
        keyword = keyword.lower().strip()
        if not keyword:
            return await ctx.send_help()
        exists = False
        async with self.config.guild(ctx.guild).url_keyword_whitelist() as whitelist:
            if keyword in whitelist:
                exists = True
            else:
                whitelist.append(keyword)
        if exists:
            return await self.send_embed_msg(ctx, title=_("Keyword already in the whitelist."))
        else:
            return await self.send_embed_msg(
                ctx,
                title=_("Whitelist Modified"),
                description=_("Added `{whitelisted}` to the whitelist.").format(
                    whitelisted=keyword
                ),
            )

    @command_audioset_perms_whitelist.command(name="list")
    @commands.bot_has_permissions(add_reactions=True)
    async def command_audioset_perms_whitelist_list(self, ctx: commands.Context):
        """列出所有已新增到白名單中的關鍵字。"""
        whitelist = await self.config.guild(ctx.guild).url_keyword_whitelist()
        if not whitelist:
            return await self.send_embed_msg(ctx, title=_("Nothing in the whitelist."))
        whitelist.sort()
        text = ""
        total = len(whitelist)
        pages = []
        for i, entry in enumerate(whitelist, 1):
            text += f"{i}. [{entry}]"
            if i != total:
                text += "\n"
                if i % 10 == 0:
                    pages.append(box(text, lang="ini"))
                    text = ""
            else:
                pages.append(box(text, lang="ini"))
        embed_colour = await ctx.embed_colour()
        pages = list(
            discord.Embed(title=_("Whitelist"), description=page, colour=embed_colour)
            for page in pages
        )
        await menu(ctx, pages, DEFAULT_CONTROLS)

    @command_audioset_perms_whitelist.command(name="clear")
    async def command_audioset_perms_whitelist_clear(self, ctx: commands.Context):
        """清除所有白名單中的關鍵字。"""
        whitelist = await self.config.guild(ctx.guild).url_keyword_whitelist()
        if not whitelist:
            return await self.send_embed_msg(ctx, title=_("Nothing in the whitelist."))
        await self.config.guild(ctx.guild).url_keyword_whitelist.clear()
        return await self.send_embed_msg(
            ctx,
            title=_("Whitelist Modified"),
            description=_("All entries have been removed from the whitelist."),
        )

    @command_audioset_perms_whitelist.command(name="delete", aliases=["del", "remove"])
    async def command_audioset_perms_whitelist_delete(
        self, ctx: commands.Context, *, keyword: str
    ):
        """從白名單中移除關鍵字。"""
        keyword = keyword.lower().strip()
        if not keyword:
            return await ctx.send_help()
        exists = True
        async with self.config.guild(ctx.guild).url_keyword_whitelist() as whitelist:
            if keyword not in whitelist:
                exists = False
            else:
                whitelist.remove(keyword)
        if not exists:
            return await self.send_embed_msg(ctx, title=_("Keyword already in the whitelist."))
        else:
            return await self.send_embed_msg(
                ctx,
                title=_("Whitelist Modified"),
                description=_("Removed `{whitelisted}` from the whitelist.").format(
                    whitelisted=keyword
                ),
            )

    @command_audioset_perms.group(name="blacklist")
    @commands.guild_only()
    async def command_audioset_perms_blacklist(self, ctx: commands.Context):
        """管理全域黑名單關鍵字。"""

    @command_audioset_perms_blacklist.command(name="add")
    async def command_audioset_perms_blacklist_add(self, ctx: commands.Context, *, keyword: str):
        """在黑名單中新增關鍵字。"""
        keyword = keyword.lower().strip()
        if not keyword:
            return await ctx.send_help()
        exists = False
        async with self.config.guild(ctx.guild).url_keyword_blacklist() as blacklist:
            if keyword in blacklist:
                exists = True
            else:
                blacklist.append(keyword)
        if exists:
            return await self.send_embed_msg(ctx, title=_("Keyword already in the blacklist."))
        else:
            return await self.send_embed_msg(
                ctx,
                title=_("Blacklist Modified"),
                description=_("Added `{blacklisted}` to the blacklist.").format(
                    blacklisted=keyword
                ),
            )

    @command_audioset_perms_blacklist.command(name="list")
    @commands.bot_has_permissions(add_reactions=True)
    async def command_audioset_perms_blacklist_list(self, ctx: commands.Context):
        """列出所有已新增到黑名單中的關鍵字。"""
        blacklist = await self.config.guild(ctx.guild).url_keyword_blacklist()
        if not blacklist:
            return await self.send_embed_msg(ctx, title=_("Nothing in the blacklist."))
        blacklist.sort()
        text = ""
        total = len(blacklist)
        pages = []
        for i, entry in enumerate(blacklist, 1):
            text += f"{i}. [{entry}]"
            if i != total:
                text += "\n"
                if i % 10 == 0:
                    pages.append(box(text, lang="ini"))
                    text = ""
            else:
                pages.append(box(text, lang="ini"))
        embed_colour = await ctx.embed_colour()
        pages = list(
            discord.Embed(title=_("Blacklist"), description=page, colour=embed_colour)
            for page in pages
        )
        await menu(ctx, pages, DEFAULT_CONTROLS)

    @command_audioset_perms_blacklist.command(name="clear")
    async def command_audioset_perms_blacklist_clear(self, ctx: commands.Context):
        """清除所有黑名單中的關鍵字。"""
        blacklist = await self.config.guild(ctx.guild).url_keyword_blacklist()
        if not blacklist:
            return await self.send_embed_msg(ctx, title=_("Nothing in the blacklist."))
        await self.config.guild(ctx.guild).url_keyword_blacklist.clear()
        return await self.send_embed_msg(
            ctx,
            title=_("Blacklist Modified"),
            description=_("All entries have been removed from the blacklist."),
        )

    @command_audioset_perms_blacklist.command(name="delete", aliases=["del", "remove"])
    async def command_audioset_perms_blacklist_delete(
        self, ctx: commands.Context, *, keyword: str
    ):
        """從黑名單中移除關鍵字。"""
        keyword = keyword.lower().strip()
        if not keyword:
            return await ctx.send_help()
        exists = True
        async with self.config.guild(ctx.guild).url_keyword_blacklist() as blacklist:
            if keyword not in blacklist:
                exists = False
            else:
                blacklist.remove(keyword)
        if not exists:
            return await self.send_embed_msg(ctx, title=_("Keyword is not in the blacklist."))
        else:
            return await self.send_embed_msg(
                ctx,
                title=_("Blacklist Modified"),
                description=_("Removed `{blacklisted}` from the blacklist.").format(
                    blacklisted=keyword
                ),
            )

    @command_audioset.group(name="autoplay")
    @commands.guild_only()
    @commands.mod_or_permissions(manage_guild=True)
    async def command_audioset_autoplay(self, ctx: commands.Context):
        """更改自動播放設定。"""

    @command_audioset_autoplay.command(name="toggle")
    async def command_audioset_autoplay_toggle(self, ctx: commands.Context):
        """當佇列內沒有歌曲時，則切換自動播放模式。"""
        autoplay = await self.config.guild(ctx.guild).auto_play()
        repeat = await self.config.guild(ctx.guild).repeat()
        disconnect = await self.config.guild(ctx.guild).disconnect()
        msg = _("Auto-play when queue ends: {true_or_false}.").format(
            true_or_false=_("Enabled") if not autoplay else _("Disabled")
        )
        await self.config.guild(ctx.guild).auto_play.set(not autoplay)
        if autoplay is not True and repeat is True:
            msg += _("\nRepeat has been disabled.")
            await self.config.guild(ctx.guild).repeat.set(False)
        if autoplay is not True and disconnect is True:
            msg += _("\nAuto-disconnecting at queue end has been disabled.")
            await self.config.guild(ctx.guild).disconnect.set(False)

        await self.send_embed_msg(ctx, title=_("Setting Changed"), description=msg)
        if self._player_check(ctx):
            await self.set_player_settings(ctx)

    @command_audioset_autoplay.command(name="playlist", usage="<playlist_name_OR_id> [args]")
    @commands.bot_has_permissions(add_reactions=True)
    async def command_audioset_autoplay_playlist(
        self,
        ctx: commands.Context,
        playlist_matches: PlaylistConverter,
        *,
        scope_data: ScopeParser = None,
    ):
        """設定播放清單以便自動播放歌曲。

        **用法**:
        ​ ​ ​ ​ `[p]audioset autoplay 播放清單名稱或ID [參數]`

        **參數**:
        ​ ​ ​ ​ 以下是可選參數:
        ​ ​ ​ ​ ​ ​ ​ ​ --scope <範圍>
        ​ ​ ​ ​ ​ ​ ​ ​ --author [作者]
        ​ ​ ​ ​ ​ ​ ​ ​ --guild [伺服器] **此命令只有機器人擁有者可使用**

        **範圍** 可選擇:
            ​Global
        ​ ​ ​ ​ Guild
        ​ ​ ​ ​ User

        **作者** 可選擇:
        ​ ​ ​ ​ 使用者ID
        ​ ​ ​ ​ 提及使用者
        ​ ​ ​ ​ 使用者名稱#0000

        **伺服器** 可選擇:
        ​ ​ ​ ​ 伺服器ID
        ​ ​ ​ ​ 伺服器全名

        範例:
        ​ ​ ​ ​ `[p]audioset autoplay MyGuildPlaylist`
        ​ ​ ​ ​ `[p]audioset autoplay MyGlobalPlaylist --scope Global`
        ​ ​ ​ ​ `[p]audioset autoplay PersonalPlaylist --scope User --author Draper`
        """
        if self.playlist_api is None:
            return await self.send_embed_msg(
                ctx,
                title=_("Playlists Are Not Available"),
                description=_("The playlist section of Audio is currently unavailable"),
                footer=discord.Embed.Empty
                if not await self.bot.is_owner(ctx.author)
                else _("Check your logs."),
            )
        if scope_data is None:
            scope_data = [None, ctx.author, ctx.guild, False]

        scope, author, guild, specified_user = scope_data
        try:
            playlist, playlist_arg, scope = await self.get_playlist_match(
                ctx, playlist_matches, scope, author, guild, specified_user
            )
        except TooManyMatches as e:
            return await self.send_embed_msg(ctx, title=str(e))
        if playlist is None:
            return await self.send_embed_msg(
                ctx,
                title=_("No Playlist Found"),
                description=_("Could not match '{arg}' to a playlist").format(arg=playlist_arg),
            )
        try:
            tracks = playlist.tracks
            if not tracks:
                return await self.send_embed_msg(
                    ctx,
                    title=_("No Tracks Found"),
                    description=_("Playlist {name} has no tracks.").format(name=playlist.name),
                )
            playlist_data = dict(enabled=True, id=playlist.id, name=playlist.name, scope=scope)
            await self.config.guild(ctx.guild).autoplaylist.set(playlist_data)
        except RuntimeError:
            return await self.send_embed_msg(
                ctx,
                title=_("No Playlist Found"),
                description=_("Playlist {id} does not exist in {scope} scope.").format(
                    id=playlist_arg, scope=self.humanize_scope(scope, the=True)
                ),
            )
        except MissingGuild:
            return await self.send_embed_msg(
                ctx,
                title=_("Missing Arguments"),
                description=_("You need to specify the Guild ID for the guild to lookup."),
            )
        else:
            return await self.send_embed_msg(
                ctx,
                title=_("Setting Changed"),
                description=_(
                    "Playlist {name} (`{id}`) [**{scope}**] will be used for autoplay."
                ).format(
                    name=playlist.name,
                    id=playlist.id,
                    scope=self.humanize_scope(
                        scope, ctx=guild if scope == PlaylistScope.GUILD.value else author
                    ),
                ),
            )

    @command_audioset_autoplay.command(name="reset")
    async def command_audioset_autoplay_reset(self, ctx: commands.Context):
        """將自動播放重置回預設的播放清單。"""
        playlist_data = dict(
            enabled=True,
            id=42069,
            name="Aikaterna's curated tracks",
            scope=PlaylistScope.GLOBAL.value,
        )

        await self.config.guild(ctx.guild).autoplaylist.set(playlist_data)
        return await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("Set auto-play playlist to play recently played tracks."),
        )

    @command_audioset.command(name="globaldailyqueue")
    @commands.is_owner()
    async def command_audioset_global_historical_queue(self, ctx: commands.Context):
        """切換全域每日佇列。

        全域每日佇列會將當天播放的所有歌曲建立為播放清單。
        """
        daily_playlists = self._daily_global_playlist_cache.setdefault(
            self.bot.user.id, await self.config.daily_playlists()
        )
        await self.config.daily_playlists.set(not daily_playlists)
        self._daily_global_playlist_cache[self.bot.user.id] = not daily_playlists
        await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("Global daily queues: {true_or_false}.").format(
                true_or_false=_("Enabled") if not daily_playlists else _("Disabled")
            ),
        )

    @command_audioset.command(name="dailyqueue")
    @commands.guild_only()
    @commands.admin()
    async def command_audioset_historical_queue(self, ctx: commands.Context):
        """切換每日佇列。

        每日佇列會將當天播放的所有歌曲建立為播放清單。
        """
        daily_playlists = self._daily_playlist_cache.setdefault(
            ctx.guild.id, await self.config.guild(ctx.guild).daily_playlists()
        )
        await self.config.guild(ctx.guild).daily_playlists.set(not daily_playlists)
        self._daily_playlist_cache[ctx.guild.id] = not daily_playlists
        await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("Daily queues: {true_or_false}.").format(
                true_or_false=_("Enabled") if not daily_playlists else _("Disabled")
            ),
        )

    @command_audioset.command(name="dc")
    @commands.guild_only()
    @commands.mod_or_permissions(manage_guild=True)
    async def command_audioset_dc(self, ctx: commands.Context):
        """切換播放完畢後，機器人自動退出語音的設定。

        此設定將覆蓋`[p]audioset emptydisconnect`
        """

        disconnect = await self.config.guild(ctx.guild).disconnect()
        autoplay = await self.config.guild(ctx.guild).auto_play()
        msg = ""
        msg += _("Auto-disconnection at queue end: {true_or_false}.").format(
            true_or_false=_("Enabled") if not disconnect else _("Disabled")
        )
        if disconnect is not True and autoplay is True:
            msg += _("\nAuto-play has been disabled.")
            await self.config.guild(ctx.guild).auto_play.set(False)

        await self.config.guild(ctx.guild).disconnect.set(not disconnect)

        await self.send_embed_msg(ctx, title=_("Setting Changed"), description=msg)

    @command_audioset.command(name="dj")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    async def command_audioset_dj(self, ctx: commands.Context):
        """切換為DJ模式

        DJ模式將會允許擁有DJ角色的使用者使用音樂類的指令。
        """
        dj_role = self._dj_role_cache.setdefault(
            ctx.guild.id, await self.config.guild(ctx.guild).dj_role()
        )
        dj_role = ctx.guild.get_role(dj_role)
        if dj_role is None:
            await self.send_embed_msg(
                ctx,
                title=_("Missing DJ Role"),
                description=_(
                    "Please set a role to use with DJ mode. Enter the role name or ID now."
                ),
            )

            try:
                pred = MessagePredicate.valid_role(ctx)
                await self.bot.wait_for("message", timeout=15.0, check=pred)
                await ctx.invoke(self.command_audioset_role, role_name=pred.result)
            except asyncio.TimeoutError:
                return await self.send_embed_msg(
                    ctx, title=_("Response timed out, try again later.")
                )
        dj_enabled = self._dj_status_cache.setdefault(
            ctx.guild.id, await self.config.guild(ctx.guild).dj_enabled()
        )
        await self.config.guild(ctx.guild).dj_enabled.set(not dj_enabled)
        self._dj_status_cache[ctx.guild.id] = not dj_enabled
        await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("DJ role: {true_or_false}.").format(
                true_or_false=_("Enabled") if not dj_enabled else _("Disabled")
            ),
        )

    @command_audioset.command(name="emptydisconnect")
    @commands.guild_only()
    @commands.mod_or_permissions(administrator=True)
    async def command_audioset_emptydisconnect(self, ctx: commands.Context, seconds: int):
        """當機器人單獨在頻道超過 x 秒，會自動從頻道斷開。設定 0 秒以取消該功能。

        `[p]audioset dc` 將覆蓋此設定。
        """
        if seconds < 0:
            return await self.send_embed_msg(
                ctx, title=_("Invalid Time"), description=_("Seconds can't be less than zero.")
            )
        if 10 > seconds > 0:
            seconds = 10
        if seconds == 0:
            enabled = False
            await self.send_embed_msg(
                ctx, title=_("Setting Changed"), description=_("Empty disconnect disabled.")
            )
        else:
            enabled = True
            await self.send_embed_msg(
                ctx,
                title=_("Setting Changed"),
                description=_("Empty disconnect timer set to {num_seconds}.").format(
                    num_seconds=self.get_time_string(seconds)
                ),
            )

        await self.config.guild(ctx.guild).emptydc_timer.set(seconds)
        await self.config.guild(ctx.guild).emptydc_enabled.set(enabled)

    @command_audioset.command(name="emptypause")
    @commands.guild_only()
    @commands.mod_or_permissions(administrator=True)
    async def command_audioset_emptypause(self, ctx: commands.Context, seconds: int):
        """當頻道無人之後超過 x 秒，會自動暫停。設定 0 秒以取消該功能。"""
        if seconds < 0:
            return await self.send_embed_msg(
                ctx, title=_("Invalid Time"), description=_("Seconds can't be less than zero.")
            )
        if 10 > seconds > 0:
            seconds = 10
        if seconds == 0:
            enabled = False
            await self.send_embed_msg(
                ctx, title=_("Setting Changed"), description=_("Empty pause disabled.")
            )
        else:
            enabled = True
            await self.send_embed_msg(
                ctx,
                title=_("Setting Changed"),
                description=_("Empty pause timer set to {num_seconds}.").format(
                    num_seconds=self.get_time_string(seconds)
                ),
            )
        await self.config.guild(ctx.guild).emptypause_timer.set(seconds)
        await self.config.guild(ctx.guild).emptypause_enabled.set(enabled)

    @command_audioset.command(name="lyrics")
    @commands.guild_only()
    @commands.mod_or_permissions(administrator=True)
    async def command_audioset_lyrics(self, ctx: commands.Context):
        """優先處理有歌詞的曲目。"""
        prefer_lyrics = await self.config.guild(ctx.guild).prefer_lyrics()
        await self.config.guild(ctx.guild).prefer_lyrics.set(not prefer_lyrics)
        await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("Prefer tracks with lyrics: {true_or_false}.").format(
                true_or_false=_("Enabled") if not prefer_lyrics else _("Disabled")
            ),
        )

    @command_audioset.command(name="jukebox")
    @commands.guild_only()
    @commands.mod_or_permissions(administrator=True)
    async def command_audioset_jukebox(self, ctx: commands.Context, price: int):
        """給非管理成員設定點歌的價格，設定 0 以關閉該功能。"""
        if price < 0:
            return await self.send_embed_msg(
                ctx, title=_("Invalid Price"), description=_("Price can't be less than zero.")
            )
        if price == 0:
            jukebox = False
            await self.send_embed_msg(
                ctx, title=_("Setting Changed"), description=_("Jukebox mode disabled.")
            )
        else:
            jukebox = True
            await self.send_embed_msg(
                ctx,
                title=_("Setting Changed"),
                description=_("Track queueing command price set to {price} {currency}.").format(
                    price=humanize_number(price), currency=await bank.get_currency_name(ctx.guild)
                ),
            )

        await self.config.guild(ctx.guild).jukebox_price.set(price)
        await self.config.guild(ctx.guild).jukebox.set(jukebox)

    @command_audioset.command(name="localpath")
    @commands.is_owner()
    @commands.bot_has_permissions(add_reactions=True)
    async def command_audioset_localpath(self, ctx: commands.Context, *, local_path=None):
        """如果 Lavalink.jar 不是在 Audio 資料夾，請設定 localtracks 路徑。

        留空以重設路徑為 Audio 資料目錄。
        """

        if not local_path:
            await self.config.localpath.set(str(cog_data_path(raw_name="Audio")))
            self.local_folder_current_path = cog_data_path(raw_name="Audio")
            return await self.send_embed_msg(
                ctx,
                title=_("Setting Changed"),
                description=_(
                    "The localtracks path location has been reset to {localpath}"
                ).format(localpath=str(cog_data_path(raw_name="Audio").absolute())),
            )

        info_msg = _(
            "This setting is only for bot owners to set a localtracks folder location "
            "In the example below, the full path for 'ParentDirectory' "
            "must be passed to this command.\n"
            "```\n"
            "ParentDirectory\n"
            "  |__ localtracks  (folder)\n"
            "  |     |__ Awesome Album Name  (folder)\n"
            "  |           |__01 Cool Song.mp3\n"
            "  |           |__02 Groovy Song.mp3\n"
            "```\n"
            "於該命令的資料夾路徑必須含有 localtracks 資料夾。\n"
            "**此資料夾和檔案對於運行 "
            "`Lavalink.jar` 的使用者必須是可見的。**\n"
            "於此指令，留空的路徑將還原預設，"
            "為機器人 `Audio` 的資料夾中。\n"
            "您是否要繼續為 localtracks 設定路徑？"
        )
        info = await ctx.maybe_send_embed(info_msg)

        start_adding_reactions(info, ReactionPredicate.YES_OR_NO_EMOJIS)
        pred = ReactionPredicate.yes_or_no(info, ctx.author)
        await self.bot.wait_for("reaction_add", check=pred)

        if not pred.result:
            with contextlib.suppress(discord.HTTPException):
                await info.delete()
            return
        temp = LocalPath(local_path, self.local_folder_current_path, forced=True)
        if not temp.exists() or not temp.is_dir():
            return await self.send_embed_msg(
                ctx,
                title=_("Invalid Path"),
                description=_("{local_path} does not seem like a valid path.").format(
                    local_path=local_path
                ),
            )

        if not temp.localtrack_folder.exists():
            warn_msg = _(
                "`{localtracks}` does not exist. "
                "The path will still be saved, but please check the path and "
                "create a localtracks folder in `{localfolder}` before attempting "
                "to play local tracks."
            ).format(localfolder=temp.absolute(), localtracks=temp.localtrack_folder.absolute())
            await self.send_embed_msg(ctx, title=_("Invalid Environment"), description=warn_msg)
        local_path = str(temp.localtrack_folder.absolute())
        await self.config.localpath.set(local_path)
        self.local_folder_current_path = temp.localtrack_folder.absolute()
        return await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("The localtracks path location has been set to {localpath}").format(
                localpath=local_path
            ),
        )

    @command_audioset.command(name="maxlength")
    @commands.guild_only()
    @commands.mod_or_permissions(administrator=True)
    async def command_audioset_maxlength(self, ctx: commands.Context, seconds: Union[int, str]):
        """佇列的最大歌曲長度（以秒為單位），設定 0 秒以取消該功能。

        接受 x 秒 或以 00:00:00 (`hh:mm:ss`) 或 00:00 (`mm:ss`) 格式的值。 無效的
        輸入將關閉最大長度的設定。
        """
        if not isinstance(seconds, int):
            seconds = self.time_convert(seconds)
        if seconds < 0:
            return await self.send_embed_msg(
                ctx, title=_("Invalid length"), description=_("Length can't be less than zero.")
            )
        if seconds == 0:
            await self.send_embed_msg(
                ctx, title=_("Setting Changed"), description=_("Track max length disabled.")
            )
        else:
            await self.send_embed_msg(
                ctx,
                title=_("Setting Changed"),
                description=_("Track max length set to {seconds}.").format(
                    seconds=self.get_time_string(seconds)
                ),
            )
        await self.config.guild(ctx.guild).maxlength.set(seconds)

    @command_audioset.command(name="notify")
    @commands.guild_only()
    @commands.mod_or_permissions(manage_guild=True)
    async def command_audioset_notify(self, ctx: commands.Context):
        """切換 顯示曲目 和 其他機器人訊息。"""
        notify = await self.config.guild(ctx.guild).notify()
        await self.config.guild(ctx.guild).notify.set(not notify)
        await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("Notify mode: {true_or_false}.").format(
                true_or_false=_("Enabled") if not notify else _("Disabled")
            ),
        )

    @command_audioset.command(name="autodeafen")
    @commands.guild_only()
    @commands.mod_or_permissions(manage_guild=True)
    async def command_audioset_auto_deafen(self, ctx: commands.Context):
        """切換是否在加入語音頻道後自動使機器人拒聽。"""
        auto_deafen = await self.config.guild(ctx.guild).auto_deafen()
        await self.config.guild(ctx.guild).auto_deafen.set(not auto_deafen)
        await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("Auto Deafen: {true_or_false}.").format(
                true_or_false=_("Enabled") if not auto_deafen else _("Disabled")
            ),
        )

    @command_audioset.command(name="restrict")
    @commands.is_owner()
    @commands.guild_only()
    async def command_audioset_restrict(self, ctx: commands.Context):
        """切換 Audio 的網域限制。

        當設為為關閉時，使用者可以從非營利的網站或連結播放歌曲。
        當設定為開啟時，使用者將限制於播放來自
        YouTube、SoundCloud、Vimeo、Twitch 和 Bandcamp 的連結。
        """
        restrict = await self.config.restrict()
        await self.config.restrict.set(not restrict)
        await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("Commercial links only: {true_or_false}.").format(
                true_or_false=_("Enabled") if not restrict else _("Disabled")
            ),
        )

    @command_audioset.command(name="role")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    async def command_audioset_role(self, ctx: commands.Context, *, role_name: discord.Role):
        """設定DJ身份組來使用DJ模式"""
        await self.config.guild(ctx.guild).dj_role.set(role_name.id)
        self._dj_role_cache[ctx.guild.id] = role_name.id
        dj_role = self._dj_role_cache.setdefault(
            ctx.guild.id, await self.config.guild(ctx.guild).dj_role()
        )
        dj_role_obj = ctx.guild.get_role(dj_role)
        await self.send_embed_msg(
            ctx,
            title=_("Settings Changed"),
            description=_("DJ role set to: {role.name}.").format(role=dj_role_obj),
        )

    @command_audioset.command(name="settings", aliases=["info"])
    @commands.guild_only()
    async def command_audioset_settings(self, ctx: commands.Context):
        """顯示當前設定值。"""
        is_owner = await self.bot.is_owner(ctx.author)
        global_data = await self.config.all()
        data = await self.config.guild(ctx.guild).all()

        auto_deafen = _("Enabled") if data["auto_deafen"] else _("Disabled")
        dj_role_obj = ctx.guild.get_role(data["dj_role"])
        dj_enabled = data["dj_enabled"]
        emptydc_enabled = data["emptydc_enabled"]
        emptydc_timer = data["emptydc_timer"]
        emptypause_enabled = data["emptypause_enabled"]
        emptypause_timer = data["emptypause_timer"]
        jukebox = data["jukebox"]
        jukebox_price = data["jukebox_price"]
        thumbnail = data["thumbnail"]
        dc = data["disconnect"]
        autoplay = data["auto_play"]
        maxlength = data["maxlength"]
        maxvolume = data["max_volume"]
        vote_percent = data["vote_percent"]
        current_level = CacheLevel(global_data["cache_level"])
        song_repeat = _("Enabled") if data["repeat"] else _("Disabled")
        song_shuffle = _("Enabled") if data["shuffle"] else _("Disabled")
        bumpped_shuffle = _("Enabled") if data["shuffle_bumped"] else _("Disabled")
        song_notify = _("Enabled") if data["notify"] else _("Disabled")
        song_status = _("Enabled") if global_data["status"] else _("Disabled")
        persist_queue = _("Enabled") if data["persist_queue"] else _("Disabled")

        countrycode = data["country_code"]

        spotify_cache = CacheLevel.set_spotify()
        youtube_cache = CacheLevel.set_youtube()
        lavalink_cache = CacheLevel.set_lavalink()
        has_spotify_cache = current_level.is_superset(spotify_cache)
        has_youtube_cache = current_level.is_superset(youtube_cache)
        has_lavalink_cache = current_level.is_superset(lavalink_cache)
        cache_enabled = CacheLevel.set_lavalink().is_subset(current_level)
        autoplaylist = data["autoplaylist"]
        vote_enabled = data["vote_enabled"]
        msg = "----" + _("Server Settings") + "----        \n"
        msg += _("Auto-deafen:      [{auto_deafen}]\n").format(
            auto_deafen=auto_deafen,
        )
        msg += _("Auto-disconnect:  [{dc}]\n").format(dc=_("Enabled") if dc else _("Disabled"))
        msg += _("Auto-play:        [{autoplay}]\n").format(
            autoplay=_("Enabled") if autoplay else _("Disabled")
        )
        if emptydc_enabled:
            msg += _("Disconnect timer: [{num_seconds}]\n").format(
                num_seconds=self.get_time_string(emptydc_timer)
            )
        if emptypause_enabled:
            msg += _("Auto Pause timer: [{num_seconds}]\n").format(
                num_seconds=self.get_time_string(emptypause_timer)
            )
        if dj_enabled and dj_role_obj:
            msg += _("DJ Role:          [{role.name}]\n").format(role=dj_role_obj)
        if jukebox:
            msg += _("Jukebox:          [{jukebox_name}]\n").format(jukebox_name=jukebox)
            msg += _("Command price:    [{jukebox_price}]\n").format(
                jukebox_price=humanize_number(jukebox_price)
            )
        if maxlength > 0:
            msg += _("Max track length: [{tracklength}]\n").format(
                tracklength=self.get_time_string(maxlength)
            )
        msg += _(
            "Max volume:       [{max_volume}%]\n"
            "Persist queue:    [{persist_queue}]\n"
            "Repeat:           [{repeat}]\n"
            "Shuffle:          [{shuffle}]\n"
            "Shuffle bumped:   [{bumpped_shuffle}]\n"
            "Song notify msgs: [{notify}]\n"
            "Songs as status:  [{status}]\n"
            "Spotify search:   [{countrycode}]\n"
        ).format(
            max_volume=maxvolume,
            countrycode=countrycode,
            persist_queue=persist_queue,
            repeat=song_repeat,
            shuffle=song_shuffle,
            notify=song_notify,
            status=song_status,
            bumpped_shuffle=bumpped_shuffle,
        )
        if thumbnail:
            msg += _("Thumbnails:       [{0}]\n").format(
                _("Enabled") if thumbnail else _("Disabled")
            )
        if vote_percent > 0:
            msg += _(
                "Vote skip:        [{vote_enabled}]\nSkip percentage:  [{vote_percent}%]\n"
            ).format(
                vote_percent=vote_percent,
                vote_enabled=_("Enabled") if vote_enabled else _("Disabled"),
            )

        if autoplay or autoplaylist["enabled"]:
            if autoplaylist["enabled"]:
                pname = autoplaylist["name"]
                pid = autoplaylist["id"]
                pscope = autoplaylist["scope"]
                if pscope == PlaylistScope.GUILD.value:
                    pscope = _("Server")
                elif pscope == PlaylistScope.USER.value:
                    pscope = _("User")
                else:
                    pscope = _("Global")
            elif cache_enabled:
                pname = _("Cached")
                pid = _("Cached")
                pscope = _("Cached")
            else:
                pname = _("US Top 100")
                pid = _("US Top 100")
                pscope = _("US Top 100")
            msg += (
                "\n---"
                + _("Auto-play Settings")
                + "---        \n"
                + _("Playlist name:    [{pname}]\n")
                + _("Playlist ID:      [{pid}]\n")
                + _("Playlist scope:   [{pscope}]\n")
            ).format(pname=pname, pid=pid, pscope=pscope)

        if is_owner:
            msg += (
                "\n---"
                + _("Cache Settings")
                + "---        \n"
                + _("Max age:                [{max_age}]\n")
                + _("Local Spotify cache:    [{spotify_status}]\n")
                + _("Local Youtube cache:    [{youtube_status}]\n")
                + _("Local Lavalink cache:   [{lavalink_status}]\n")
            ).format(
                max_age=str(await self.config.cache_age()) + " " + _("days"),
                spotify_status=_("Enabled") if has_spotify_cache else _("Disabled"),
                youtube_status=_("Enabled") if has_youtube_cache else _("Disabled"),
                lavalink_status=_("Enabled") if has_lavalink_cache else _("Disabled"),
            )
        msg += (
            "\n---"
            + _("User Settings")
            + "---        \n"
            + _("Spotify search:   [{country_code}]\n")
        ).format(country_code=await self.config.user(ctx.author).country_code())

        msg += (
            "\n---"
            + _("Lavalink Settings")
            + "---        \n"
            + _("Cog version:            [{version}]\n")
            + _("Red-Lavalink:           [{lavalink_version}]\n")
            + _("External server:        [{use_external_lavalink}]\n")
        ).format(
            version=__version__,
            lavalink_version=lavalink.__version__,
            use_external_lavalink=_("Enabled")
            if global_data["use_external_lavalink"]
            else _("Disabled"),
        )
        if is_owner and not global_data["use_external_lavalink"] and self.player_manager.ll_build:
            msg += _(
                "Lavalink build:         [{llbuild}]\n"
                "Lavalink branch:        [{llbranch}]\n"
                "Release date:           [{build_time}]\n"
                "Lavaplayer version:     [{lavaplayer}]\n"
                "Java version:           [{jvm}]\n"
                "Java Executable:        [{jv_exec}]\n"
            ).format(
                build_time=self.player_manager.build_time,
                llbuild=self.player_manager.ll_build,
                llbranch=self.player_manager.ll_branch,
                lavaplayer=self.player_manager.lavaplayer,
                jvm=self.player_manager.jvm,
                jv_exec=self.player_manager.path,
            )
        if is_owner:
            msg += _("Localtracks path:       [{localpath}]\n").format(**global_data)

        await self.send_embed_msg(ctx, description=box(msg, lang="ini"))

    @command_audioset.command(name="logs")
    @commands.is_owner()
    @has_internal_server()
    @commands.guild_only()
    async def command_audioset_logs(self, ctx: commands.Context):
        """傳送 Lavalink server 日誌到你的私訊。"""
        datapath = cog_data_path(raw_name="Audio")
        logs = datapath / "logs" / "spring.log"
        zip_name = None
        try:
            try:
                if not (logs.exists() and logs.is_file()):
                    return await ctx.send(_("No logs found in your data folder."))
            except OSError:
                return await ctx.send(_("No logs found in your data folder."))

            def check(path):
                return os.path.getsize(str(path)) > (8388608 - 1000)

            if check(logs):
                zip_name = logs.with_suffix(".tar.gz")
                zip_name.unlink(missing_ok=True)
                with tarfile.open(zip_name, "w:gz") as tar:
                    tar.add(str(logs), arcname="spring.log", recursive=False)
                if check(zip_name):
                    await ctx.send(
                        _("Logs are too large, you can find them in {path}").format(
                            path=zip_name.absolute()
                        )
                    )
                    zip_name = None
                else:
                    await ctx.author.send(file=discord.File(str(zip_name)))
            else:
                await ctx.author.send(file=discord.File(str(logs)))
        except discord.HTTPException:
            await ctx.send(_("I need to be able to DM you to send you the logs."))
        finally:
            if zip_name is not None:
                zip_name.unlink(missing_ok=True)

    @command_audioset.command(name="status")
    @commands.is_owner()
    @commands.guild_only()
    async def command_audioset_status(self, ctx: commands.Context):
        """啟用/停用歌曲標題作為狀態。"""
        status = await self.config.status()
        await self.config.status.set(not status)
        await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("Song titles as status: {true_or_false}.").format(
                true_or_false=_("Enabled") if not status else _("Disabled")
            ),
        )

    @command_audioset.command(name="thumbnail")
    @commands.guild_only()
    @commands.mod_or_permissions(administrator=True)
    async def command_audioset_thumbnail(self, ctx: commands.Context):
        """切換在音樂資訊上顯示縮圖。"""
        thumbnail = await self.config.guild(ctx.guild).thumbnail()
        await self.config.guild(ctx.guild).thumbnail.set(not thumbnail)
        await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("Thumbnail display: {true_or_false}.").format(
                true_or_false=_("Enabled") if not thumbnail else _("Disabled")
            ),
        )

    @command_audioset.command(name="vote")
    @commands.guild_only()
    @commands.mod_or_permissions(administrator=True)
    async def command_audioset_vote(self, ctx: commands.Context, percent: int):
        """設定投票百分比給非管理的成員略過曲目，設定 0 以取消該功能。"""
        if percent < 0:
            return await self.send_embed_msg(
                ctx, title=_("Invalid Time"), description=_("Seconds can't be less than zero.")
            )
        elif percent > 100:
            percent = 100
        if percent == 0:
            enabled = False
            await self.send_embed_msg(
                ctx,
                title=_("Setting Changed"),
                description=_("Voting disabled. All users can use queue management commands."),
            )
        else:
            enabled = True
            await self.send_embed_msg(
                ctx,
                title=_("Setting Changed"),
                description=_("Vote percentage set to {percent}%.").format(percent=percent),
            )

        await self.config.guild(ctx.guild).vote_percent.set(percent)
        await self.config.guild(ctx.guild).vote_enabled.set(enabled)

    @command_audioset.command(name="youtubeapi")
    @commands.is_owner()
    async def command_audioset_youtubeapi(self, ctx: commands.Context):
        """設定 YouTube API key 的指示說明。"""
        message = _(
            f"1. Go to Google Developers Console and log in with your Google account.\n"
            "(https://console.developers.google.com/)\n"
            "2. You should be prompted to create a new project (name does not matter).\n"
            "3. Click on Enable APIs and Services at the top.\n"
            "4. In the list of APIs choose or search for YouTube Data API v3 and "
            "click on it. Choose Enable.\n"
            "5. Click on Credentials on the left navigation bar.\n"
            "6. Click on Create Credential at the top.\n"
            '7. At the top click the link for "API key".\n'
            "8. No application restrictions are needed. Click Create at the bottom.\n"
            "9. You now have a key to add to `{prefix}set api youtube api_key <your_api_key_here>`"
        ).format(prefix=ctx.prefix)
        await ctx.maybe_send_embed(message)

    @command_audioset.command(name="spotifyapi")
    @commands.is_owner()
    async def command_audioset_spotifyapi(self, ctx: commands.Context):
        """設定Spotify API token的說明。"""
        message = _(
            "1. Go to Spotify developers and log in with your Spotify account.\n"
            "(https://developer.spotify.com/dashboard/applications)\n"
            '2. Click "Create An App".\n'
            "3. Fill out the form provided with your app name, etc.\n"
            '4. When asked if you\'re developing commercial integration select "No".\n'
            "5. Accept the terms and conditions.\n"
            "6. Copy your client ID and your client secret into:\n"
            "`{prefix}set api spotify client_id <your_client_id_here> "
            "client_secret <your_client_secret_here>`"
        ).format(prefix=ctx.prefix)
        await ctx.maybe_send_embed(message)

    @command_audioset.command(name="countrycode")
    @commands.guild_only()
    @commands.mod_or_permissions(administrator=True)
    async def command_audioset_countrycode(self, ctx: commands.Context, country: str):
        """設定Spotify搜索的國家/地區代碼。"""
        if len(country) != 2:
            return await self.send_embed_msg(
                ctx,
                title=_("Invalid Country Code"),
                description=_(
                    "Please use an official [ISO 3166-1 alpha-2]"
                    "(https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2) code."
                ),
            )
        country = country.upper()
        await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("Country Code set to {country}.").format(country=country),
        )

        await self.config.guild(ctx.guild).country_code.set(country)

    @command_audioset.command(name="mycountrycode")
    @commands.guild_only()
    async def command_audioset_countrycode_user(self, ctx: commands.Context, country: str):
        """設定Spotify搜索的國家/地區代碼。"""
        if len(country) != 2:
            return await self.send_embed_msg(
                ctx,
                title=_("Invalid Country Code"),
                description=_(
                    "Please use an official [ISO 3166-1 alpha-2]"
                    "(https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2) code."
                ),
            )
        country = country.upper()
        await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("Country Code set to {country}.").format(country=country),
        )

        await self.config.user(ctx.author).country_code.set(country)

    @command_audioset.command(name="cache")
    @commands.is_owner()
    async def command_audioset_cache(self, ctx: commands.Context, *, level: int = None):
        """設定快取等級。

        可使用以下等級之一：

        0: 停用所有快取
        1: 啟用 Spotify 快取
        2: 啟用 YouTube 快取
        3: 啟用 Lavalink 快取
        5: 啟用所有快取

        -n: 停用指定的快取。如 -3: 停用 Lavalink 快取。
        """
        current_level = CacheLevel(await self.config.cache_level())
        spotify_cache = CacheLevel.set_spotify()
        youtube_cache = CacheLevel.set_youtube()
        lavalink_cache = CacheLevel.set_lavalink()
        has_spotify_cache = current_level.is_superset(spotify_cache)
        has_youtube_cache = current_level.is_superset(youtube_cache)
        has_lavalink_cache = current_level.is_superset(lavalink_cache)

        if level is None:
            msg = (
                _("Max age:          [{max_age}]\n")
                + _("Spotify cache:    [{spotify_status}]\n")
                + _("Youtube cache:    [{youtube_status}]\n")
                + _("Lavalink cache:   [{lavalink_status}]\n")
            ).format(
                max_age=str(await self.config.cache_age()) + " " + _("days"),
                spotify_status=_("Enabled") if has_spotify_cache else _("Disabled"),
                youtube_status=_("Enabled") if has_youtube_cache else _("Disabled"),
                lavalink_status=_("Enabled") if has_lavalink_cache else _("Disabled"),
            )
            await self.send_embed_msg(
                ctx, title=_("Cache Settings"), description=box(msg, lang="ini")
            )
            return await ctx.send_help()
        if level not in [5, 3, 2, 1, 0, -1, -2, -3]:
            return await ctx.send_help()

        removing = level < 0

        if level == 5:
            newcache = CacheLevel.all()
        elif level == 0:
            newcache = CacheLevel.none()
        elif level in [-3, 3]:
            if removing:
                newcache = current_level - lavalink_cache
            else:
                newcache = current_level + lavalink_cache
        elif level in [-2, 2]:
            if removing:
                newcache = current_level - youtube_cache
            else:
                newcache = current_level + youtube_cache
        elif level in [-1, 1]:
            if removing:
                newcache = current_level - spotify_cache
            else:
                newcache = current_level + spotify_cache
        else:
            return await ctx.send_help()

        has_spotify_cache = newcache.is_superset(spotify_cache)
        has_youtube_cache = newcache.is_superset(youtube_cache)
        has_lavalink_cache = newcache.is_superset(lavalink_cache)
        msg = (
            _("Max age:          [{max_age}]\n")
            + _("Spotify cache:    [{spotify_status}]\n")
            + _("Youtube cache:    [{youtube_status}]\n")
            + _("Lavalink cache:   [{lavalink_status}]\n")
        ).format(
            max_age=str(await self.config.cache_age()) + " " + _("days"),
            spotify_status=_("Enabled") if has_spotify_cache else _("Disabled"),
            youtube_status=_("Enabled") if has_youtube_cache else _("Disabled"),
            lavalink_status=_("Enabled") if has_lavalink_cache else _("Disabled"),
        )

        await self.send_embed_msg(ctx, title=_("Cache Settings"), description=box(msg, lang="ini"))

        await self.config.cache_level.set(newcache.value)

    @command_audioset.command(name="cacheage")
    @commands.is_owner()
    async def command_audioset_cacheage(self, ctx: commands.Context, age: int):
        """設定快取最長期限：

        此命令允許您設定在快取中的項目變為無效之前的最大天數。
        
        """
        msg = ""
        if age < 7:
            msg = _(
                "Cache age cannot be less than 7 days. If you wish to disable it run "
                "{prefix}audioset cache.\n"
            ).format(prefix=ctx.prefix)
            age = 7
        msg += _("I've set the cache age to {age} days").format(age=age)
        await self.config.cache_age.set(age)
        await self.send_embed_msg(ctx, title=_("Setting Changed"), description=msg)

    @command_audioset.command(name="persistqueue")
    @commands.admin()
    async def command_audioset_persist_queue(self, ctx: commands.Context):
        """Toggle persistent queues.

        Persistent queues allows the current queue to be restored when the queue closes.
        """
        persist_cache = self._persist_queue_cache.setdefault(
            ctx.guild.id, await self.config.guild(ctx.guild).persist_queue()
        )
        await self.config.guild(ctx.guild).persist_queue.set(not persist_cache)
        self._persist_queue_cache[ctx.guild.id] = not persist_cache
        await self.send_embed_msg(
            ctx,
            title=_("Setting Changed"),
            description=_("Persisting queues: {true_or_false}.").format(
                true_or_false=_("Enabled") if not persist_cache else _("Disabled")
            ),
        )

    @command_audioset.command(name="restart")
    @commands.is_owner()
    async def command_audioset_restart(self, ctx: commands.Context):
        """重啟Lavalink連接。"""
        async with ctx.typing():
            await lavalink.close(self.bot)
            if self.player_manager is not None:
                await self.player_manager.shutdown()

            self.lavalink_restart_connect()

            await self.send_embed_msg(
                ctx,
                title=_("Restarting Lavalink"),
                description=_("It can take a couple of minutes for Lavalink to fully start up."),
            )

    @command_audioset.command(usage="<maximum volume>", name="maxvolume")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    async def command_audioset_maxvolume(self, ctx: commands.Context, max_volume: int):
        """設定此伺服器允許的最大音量。"""
        if max_volume < 1:
            return await self.send_embed_msg(
                ctx,
                title=_("Error"),
                description=_(
                    "Music without sound isn't music at all. Try setting the volume higher then 0%."
                ),
            )
        elif max_volume > 150:
            max_volume = 150
            await self.send_embed_msg(
                ctx,
                title=_("Setting changed"),
                description=_(
                    "The maximum volume has been limited to 150%, be easy on your ears."
                ),
            )
        else:
            await self.send_embed_msg(
                ctx,
                title=_("Setting changed"),
                description=_("The maximum volume has been limited to {max_volume}%.").format(
                    max_volume=max_volume
                ),
            )
        current_volume = await self.config.guild(ctx.guild).volume()
        if current_volume > max_volume:
            await self.config.guild(ctx.guild).volume.set(max_volume)
            if self._player_check(ctx):
                player = lavalink.get_player(ctx.guild.id)
                await player.set_volume(max_volume)
                player.store("notify_channel", ctx.channel.id)

        await self.config.guild(ctx.guild).max_volume.set(max_volume)
