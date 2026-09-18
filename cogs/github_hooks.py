import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import datetime
import asyncio


class GitHubHooks(commands.Cog):
    """Polls GitHub repos for new events and posts them to a channel."""
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.GitHub')
        self.check_repos.start()

    def cog_unload(self):
        self.check_repos.cancel()

    github_group = app_commands.Group(name="github", description="GitHub repo tracking.",
                                      default_permissions=discord.Permissions(manage_guild=True))

    @github_group.command(name="add", description="Track a GitHub repo for new events.")
    @app_commands.describe(repo="Repository (owner/repo format)", channel="Channel for notifications")
    async def github_add(self, interaction: discord.Interaction, repo: str, channel: discord.TextChannel):
        if '/' not in repo:
            await interaction.response.send_message("❌ Format: `owner/repo` (e.g. `discord/discord-api-docs`)", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        # Validate repo exists
        url = f"https://api.github.com/repos/{repo}"
        try:
            async with self.bot.session.get(url) as resp:
                if resp.status != 200:
                    await interaction.followup.send(f"❌ Repository `{repo}` not found.", ephemeral=True)
                    return
                data = await resp.json()
        except Exception as e:
            await interaction.followup.send(f"❌ Error checking repo: {e}", ephemeral=True)
            return

        # Get latest event ID
        last_event_id = await self._get_latest_event_id(repo)

        try:
            await self.bot.db.execute(
                "INSERT INTO github_config (guild_id, channel_id, repo, last_event_id) VALUES (?, ?, ?, ?)",
                interaction.guild.id, channel.id, repo, last_event_id)
        except Exception:
            await interaction.followup.send(f"❌ `{repo}` is already tracked.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🐙 GitHub Repo Added",
            description=f"**Repo:** [{repo}](https://github.com/{repo})\n**Channel:** {channel.mention}",
            color=0x24292e)
        if data.get('description'):
            embed.add_field(name="Description", value=data['description'][:200], inline=False)
        embed.set_thumbnail(url=data.get('owner', {}).get('avatar_url', ''))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @github_group.command(name="remove", description="Stop tracking a GitHub repo.")
    @app_commands.describe(repo="Repository to remove (owner/repo)")
    async def github_remove(self, interaction: discord.Interaction, repo: str):
        await self.bot.db.execute("DELETE FROM github_config WHERE guild_id = ? AND repo = ?",
                                  interaction.guild.id, repo)
        await interaction.response.send_message(f"✅ Stopped tracking `{repo}`.", ephemeral=True)

    @github_group.command(name="list", description="List tracked repos.")
    async def github_list(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetch_all(
            "SELECT repo, channel_id FROM github_config WHERE guild_id = ?", interaction.guild.id)
        if not rows:
            await interaction.response.send_message("🐙 No repos tracked.", ephemeral=True)
            return
        lines = [f"• [{r}](https://github.com/{r}) → <#{c}>" for r, c in rows]
        embed = discord.Embed(title="🐙 Tracked Repos", description="\n".join(lines), color=0x24292e)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _get_latest_event_id(self, repo: str) -> str:
        url = f"https://api.github.com/repos/{repo}/events?per_page=1"
        try:
            async with self.bot.session.get(url) as resp:
                if resp.status == 200:
                    events = await resp.json()
                    if events:
                        return events[0].get('id', '')
        except Exception:
            pass
        return ''

    @tasks.loop(minutes=3)
    async def check_repos(self):
        configs = await self.bot.db.fetch_all(
            "SELECT id, guild_id, channel_id, repo, last_event_id FROM github_config")

        for cfg_id, guild_id, channel_id, repo, last_event_id in configs:
            guild = self.bot.get_guild(guild_id)
            channel = guild.get_channel(channel_id) if guild else None
            if not channel:
                continue

            try:
                url = f"https://api.github.com/repos/{repo}/events?per_page=10"
                async with self.bot.session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    events = await resp.json()

                if not events:
                    continue

                # Find new events
                new_events = []
                for event in events:
                    if event.get('id') == last_event_id:
                        break
                    new_events.append(event)

                # Post new events (oldest first, max 5)
                for event in reversed(new_events[:5]):
                    embed = self._event_to_embed(repo, event)
                    if embed:
                        try:
                            await channel.send(embed=embed)
                        except discord.Forbidden:
                            break
                        await asyncio.sleep(1)

                # Update last event ID
                if new_events:
                    await self.bot.db.execute(
                        "UPDATE github_config SET last_event_id = ? WHERE id = ?",
                        new_events[0]['id'], cfg_id)

            except Exception as e:
                self.logger.error(f"GitHub poll error for {repo}: {e}")

            await asyncio.sleep(2)

    @check_repos.before_loop
    async def before_check_repos(self):
        await self.bot.wait_until_ready()

    def _event_to_embed(self, repo: str, event: dict) -> discord.Embed | None:
        etype = event.get('type', '')
        actor = event.get('actor', {}).get('display_login', 'Unknown')
        avatar = event.get('actor', {}).get('avatar_url', '')
        payload = event.get('payload', {})
        created = event.get('created_at', '')

        embed = discord.Embed(color=0x24292e, timestamp=datetime.datetime.now())
        embed.set_author(name=actor, icon_url=avatar, url=f"https://github.com/{actor}")
        embed.set_footer(text=repo)

        if etype == 'PushEvent':
            commits = payload.get('commits', [])
            count = len(commits)
            branch = payload.get('ref', '').replace('refs/heads/', '')
            desc = "\n".join([f"[`{c['sha'][:7]}`](https://github.com/{repo}/commit/{c['sha']}) {c['message'][:60]}"
                             for c in commits[:5]])
            embed.title = f"⬆️ {count} commit{'s' if count != 1 else ''} pushed to `{branch}`"
            embed.description = desc or "No commit messages"

        elif etype == 'PullRequestEvent':
            pr = payload.get('pull_request', {})
            action = payload.get('action', 'opened')
            embed.title = f"🔀 PR #{pr.get('number', '?')} {action}: {pr.get('title', '')[:80]}"
            embed.url = pr.get('html_url', '')
            embed.description = (pr.get('body', '') or '')[:200]

        elif etype == 'IssuesEvent':
            issue = payload.get('issue', {})
            action = payload.get('action', 'opened')
            embed.title = f"🐛 Issue #{issue.get('number', '?')} {action}: {issue.get('title', '')[:80]}"
            embed.url = issue.get('html_url', '')

        elif etype == 'ReleaseEvent':
            release = payload.get('release', {})
            embed.title = f"🏷️ Release: {release.get('tag_name', '?')} — {release.get('name', '')[:80]}"
            embed.url = release.get('html_url', '')
            embed.description = (release.get('body', '') or '')[:300]

        elif etype == 'ForkEvent':
            embed.title = f"🍴 {actor} forked {repo}"
        elif etype == 'WatchEvent':
            embed.title = f"⭐ {actor} starred {repo}"
        elif etype == 'CreateEvent':
            ref_type = payload.get('ref_type', 'branch')
            ref = payload.get('ref', '')
            embed.title = f"🌿 {ref_type} `{ref}` created"
        else:
            return None  # Skip unknown event types

        return embed


async def setup(bot):
    await bot.add_cog(GitHubHooks(bot))
