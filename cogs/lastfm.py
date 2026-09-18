import asyncio
import io
import logging
import os
import discord
from discord.ext import commands
from discord import app_commands

from utils.lastfm import LastFMClient, get_spotify_search_url

log = logging.getLogger("Dabot.LastFM")

PERIOD_MAP = {
    "semana": "7day",
    "7day": "7day",
    "7d": "7day",
    "mes": "1month",
    "1month": "1month",
    "1m": "1month",
    "3meses": "3month",
    "3month": "3month",
    "3m": "3month",
    "6meses": "6month",
    "6month": "6month",
    "6m": "6month",
    "año": "12month",
    "12month": "12month",
    "1y": "12month",
    "total": "overall",
    "overall": "overall",
    "all": "overall"
}

PERIOD_LABELS = {
    "7day": "últimos 7 días",
    "1month": "último mes",
    "3month": "últimos 3 meses",
    "6month": "últimos 6 meses",
    "12month": "último año",
    "overall": "histórico total"
}


class MusicLinksView(discord.ui.View):
    def __init__(self, spotify_url: str, lastfm_url: str):
        super().__init__(timeout=120)
        if spotify_url:
            self.add_item(discord.ui.Button(
                label="Spotify",
                url=spotify_url,
                emoji="🎧",
                style=discord.ButtonStyle.link
            ))
        if lastfm_url:
            self.add_item(discord.ui.Button(
                label="Last.fm",
                url=lastfm_url,
                emoji="🎵",
                style=discord.ButtonStyle.link
            ))


class LastFM(commands.GroupCog, group_name="fm", group_description="🎵 Integración con Last.fm y Spotify (estilo .fmbot)"):
    """Cog for Last.fm and Spotify scrobble integration."""

    def __init__(self, bot):
        self.bot = bot
        self.client = LastFMClient(session=getattr(bot, "session", None))

    async def cog_unload(self):
        await self.client.close()

    async def _get_username_for(self, user: discord.User | discord.Member) -> str | None:
        return await self.bot.db.get_user_lastfm(user.id)

    @app_commands.command(name="set", description="🔗 Vincula tu cuenta de Last.fm a tu perfil de Discord.")
    @app_commands.describe(usuario="Tu nombre de usuario en Last.fm (ej: davito_03)")
    async def set_user(self, interaction: discord.Interaction, usuario: str):
        usuario = usuario.strip()
        await interaction.response.defer(ephemeral=True)

        uinfo = await self.client.get_user_info(usuario)
        if not uinfo:
            await interaction.followup.send(
                f"❌ No se ha encontrado el usuario **{usuario}** en Last.fm. Asegúrate de escribirlo correctamente.",
                ephemeral=True
            )
            return

        await self.bot.db.set_user_lastfm(interaction.user.id, uinfo["name"])

        embed = discord.Embed(
            title="✅ Cuenta de Last.fm Vinculada",
            description=(
                f"Has vinculado con éxito tu perfil **[{uinfo['name']}]({uinfo['url']})**.\n\n"
                f"📊 **Scrobbles totales:** `{uinfo['playcount']:,}`\n"
                f"💡 Ya puedes usar `/fm` o `/np` para mostrar lo que estás escuchando en Spotify."
            ),
            color=discord.Color.from_rgb(30, 215, 96)
        )
        if uinfo.get("avatar"):
            embed.set_thumbnail(url=uinfo["avatar"])
        embed.set_footer(text="Dabot Music · Conexión oficial Last.fm & Spotify")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="unset", description="❌ Desvincula tu cuenta de Last.fm de tu perfil de Discord.")
    async def unset_user(self, interaction: discord.Interaction):
        existing = await self._get_username_for(interaction.user)
        if not existing:
            await interaction.response.send_message("ℹ️ No tenías ninguna cuenta de Last.fm vinculada.", ephemeral=True)
            return

        await self.bot.db.delete_user_lastfm(interaction.user.id)
        await interaction.response.send_message("✅ Se ha desvinculado tu cuenta de Last.fm.", ephemeral=True)

    async def _show_now_playing(self, interaction: discord.Interaction, target_user: discord.User | discord.Member = None):
        target = target_user or interaction.user
        username = await self._get_username_for(target)

        if not username:
            if target.id == interaction.user.id:
                msg = (
                    "❌ No tienes ninguna cuenta de Last.fm vinculada.\n"
                    "Usa `/fm set <tu_usuario>` para vincularla en 10 segundos.\n\n"
                    "💡 *¿Usas Spotify? Puedes conectar tu cuenta de Spotify a Last.fm gratis en "
                    "[last.fm/settings/applications](https://www.last.fm/settings/applications) "
                    "para que guarde todas tus canciones automáticamente.*"
                )
            else:
                msg = f"❌ **{target.display_name}** no tiene una cuenta de Last.fm vinculada."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await interaction.response.defer()

        rec = await self.client.get_recent_tracks(username, limit=2)
        if not rec or not rec.get("current"):
            await interaction.followup.send(f"⚠️ No se pudieron obtener canciones recientes para **{username}**.")
            return

        track = rec["current"]
        is_now = rec.get("now_playing", False)
        total_scrobbles = rec.get("total_scrobbles", 0)

        # Fetch detailed playcounts for this track & artist
        track_info, artist_info = await asyncio.gather(
            self.client.get_track_info(track["artist"], track["name"], username=username),
            self.client.get_artist_info(track["artist"], username=username)
        )

        user_track_plays = track_info.get("userplaycount", 0)
        user_artist_plays = artist_info.get("userplaycount", 0)
        user_loved = track_info.get("userloved", False)

        color = discord.Color.from_rgb(30, 215, 96) if is_now else discord.Color.from_rgb(185, 0, 0)
        status_header = "Escuchando ahora" if is_now else "Última canción escuchada"
        heart = " ❤️" if user_loved else ""

        album_line = f"\nÁlbum: *{track['album']}*" if track.get("album") else ""
        desc = (
            f"### [{track['name']}]({track['url']}){heart}\n"
            f"de **[{track['artist']}](https://www.last.fm/music/{track['artist'].replace(' ', '+')})**"
            f"{album_line}"
        )

        embed = discord.Embed(
            title=f"🎶 {status_header} — {target.display_name}",
            description=desc,
            color=color,
            timestamp=discord.utils.utcnow()
        )

        if track.get("image"):
            embed.set_thumbnail(url=track["image"])

        embed.add_field(
            name="🎵 Scrobbles del tema",
            value=f"`{user_track_plays}` reproducciones",
            inline=True
        )
        embed.add_field(
            name="🎤 Scrobbles del artista",
            value=f"`{user_artist_plays}` reproducciones",
            inline=True
        )
        embed.add_field(
            name="📊 Scrobbles totales",
            value=f"`{total_scrobbles:,}` en Last.fm",
            inline=True
        )

        tags = track_info.get("tags") or artist_info.get("tags")
        if tags:
            embed.add_field(name="🏷️ Géneros", value=" · ".join(f"`{t}`" for t in tags[:4]), inline=False)

        embed.set_footer(
            text=f"Last.fm: {username} • Dabot Music",
            icon_url=target.display_avatar.url
        )

        view = MusicLinksView(track.get("spotify_url", ""), track.get("url", ""))
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="nowplaying", description="🎧 Muestra la canción que estás escuchando en Spotify o Last.fm.")
    @app_commands.describe(usuario="Miembro a consultar (opcional, por defecto tú)")
    async def nowplaying(self, interaction: discord.Interaction, usuario: discord.Member | None = None):
        await self._show_now_playing(interaction, usuario)

    @app_commands.command(name="chart", description="🖼️ Genera un collage visual con las carátulas de tus discos más escuchados.")
    @app_commands.describe(
        tamaño="Tamaño del collage (3x3, 4x4 o 5x5)",
        periodo="Rango temporal a analizar",
        usuario="Miembro a consultar (opcional, por defecto tú)"
    )
    @app_commands.choices(
        tamaño=[
            app_commands.Choice(name="3x3 (9 álbumes)", value="3"),
            app_commands.Choice(name="4x4 (16 álbumes)", value="4"),
            app_commands.Choice(name="5x5 (25 álbumes)", value="5"),
        ],
        periodo=[
            app_commands.Choice(name="Últimos 7 días", value="7day"),
            app_commands.Choice(name="Último mes", value="1month"),
            app_commands.Choice(name="Últimos 3 meses", value="3month"),
            app_commands.Choice(name="Últimos 6 meses", value="6month"),
            app_commands.Choice(name="Último año", value="12month"),
            app_commands.Choice(name="Histórico total", value="overall"),
        ]
    )
    async def chart(
        self,
        interaction: discord.Interaction,
        tamaño: app_commands.Choice[str] = None,
        periodo: app_commands.Choice[str] = None,
        usuario: discord.Member | None = None
    ):
        target = usuario or interaction.user
        username = await self._get_username_for(target)

        if not username:
            msg = "❌ No tienes una cuenta de Last.fm vinculada. Usa `/fm set <tu_usuario>`." if target.id == interaction.user.id else f"❌ **{target.display_name}** no tiene cuenta de Last.fm vinculada."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        size_val = int(tamaño.value) if tamaño else 3
        period_val = periodo.value if periodo else "7day"
        period_label = PERIOD_LABELS.get(period_val, period_val)

        await interaction.response.defer()

        chart_io = await self.client.generate_chart_image(username, size=size_val, period=period_val)
        if not chart_io:
            await interaction.followup.send(f"⚠️ No se encontraron suficientes álbumes con carátula en los registros de **{username}** para ese periodo.")
            return

        file = discord.File(fp=chart_io, filename=f"chart_{username}_{size_val}x{size_val}.png")

        embed = discord.Embed(
            title=f"🖼️ Collage de Álbumes ({size_val}x{size_val}) — {target.display_name}",
            description=f"Tus álbumes más escuchados durante **{period_label}** en Last.fm ({username}):",
            color=discord.Color.from_rgb(185, 0, 0),
            timestamp=discord.utils.utcnow()
        )
        embed.set_image(url=f"attachment://chart_{username}_{size_val}x{size_val}.png")
        embed.set_footer(text=f"Dabot Music · Last.fm: {username}", icon_url=target.display_avatar.url)

        await interaction.followup.send(embed=embed, file=file)

    @app_commands.command(name="top", description="📊 Muestra tus artistas, álbumes o canciones más escuchados.")
    @app_commands.describe(
        tipo="Qué tipo de ranking consultar",
        periodo="Rango temporal a analizar",
        usuario="Miembro a consultar (opcional, por defecto tú)"
    )
    @app_commands.choices(
        tipo=[
            app_commands.Choice(name="Artistas", value="artists"),
            app_commands.Choice(name="Álbumes", value="albums"),
            app_commands.Choice(name="Canciones", value="tracks"),
        ],
        periodo=[
            app_commands.Choice(name="Últimos 7 días", value="7day"),
            app_commands.Choice(name="Último mes", value="1month"),
            app_commands.Choice(name="Últimos 3 meses", value="3month"),
            app_commands.Choice(name="Últimos 6 meses", value="6month"),
            app_commands.Choice(name="Último año", value="12month"),
            app_commands.Choice(name="Histórico total", value="overall"),
        ]
    )
    async def top(
        self,
        interaction: discord.Interaction,
        tipo: app_commands.Choice[str],
        periodo: app_commands.Choice[str] = None,
        usuario: discord.Member | None = None
    ):
        target = usuario or interaction.user
        username = await self._get_username_for(target)

        if not username:
            msg = "❌ No tienes una cuenta de Last.fm vinculada. Usa `/fm set <tu_usuario>`." if target.id == interaction.user.id else f"❌ **{target.display_name}** no tiene cuenta de Last.fm vinculada."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        period_val = periodo.value if periodo else "7day"
        period_label = PERIOD_LABELS.get(period_val, period_val)
        kind = tipo.value

        await interaction.response.defer()

        if kind == "artists":
            items = await self.client.get_top_artists(username, period=period_val, limit=10)
            title = f"🎤 Top 10 Artistas — {target.display_name}"
            lines = [f"`{idx+1:2d}.` **[{a['name']}]({a['url']})** — `{a['playcount']:,}` scrobbles" for idx, a in enumerate(items)]
        elif kind == "albums":
            items = await self.client.get_top_albums(username, period=period_val, limit=10)
            title = f"💿 Top 10 Álbumes — {target.display_name}"
            lines = [f"`{idx+1:2d}.` **[{a['name']}]({a['url']})** de *{a['artist']}* — `{a['playcount']:,}` scrobbles" for idx, a in enumerate(items)]
        else:
            items = await self.client.get_top_tracks(username, period=period_val, limit=10)
            title = f"🎵 Top 10 Canciones — {target.display_name}"
            lines = [f"`{idx+1:2d}.` **[{t['name']}]({t['url']})** de *{t['artist']}* — `{t['playcount']:,}` scrobbles" for idx, t in enumerate(items)]

        if not items:
            await interaction.followup.send(f"⚠️ No hay datos suficientes registrados para **{username}** en ese periodo.")
            return

        embed = discord.Embed(
            title=title,
            description=f"Estadísticas de **{period_label}**:\n\n" + "\n".join(lines),
            color=discord.Color.from_rgb(30, 215, 96),
            timestamp=discord.utils.utcnow()
        )
        if items and items[0].get("image"):
            embed.set_thumbnail(url=items[0]["image"])

        embed.set_footer(text=f"Last.fm: {username} • Dabot Music", icon_url=target.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="compare", description="💞 Compara tu gusto musical con otro miembro del servidor.")
    @app_commands.describe(miembro="Usuario de Discord con quien comparar tu gusto musical")
    async def compare(self, interaction: discord.Interaction, miembro: discord.Member):
        if miembro.id == interaction.user.id:
            await interaction.response.send_message("❌ No puedes compararte contigo mismo.", ephemeral=True)
            return

        u1 = await self._get_username_for(interaction.user)
        u2 = await self._get_username_for(miembro)

        if not u1:
            await interaction.response.send_message("❌ No tienes vinculada tu cuenta de Last.fm. Usa `/fm set <tu_usuario>`.", ephemeral=True)
            return
        if not u2:
            await interaction.response.send_message(f"❌ **{miembro.display_name}** aún no ha vinculado su cuenta de Last.fm.", ephemeral=True)
            return

        await interaction.response.defer()

        res = await self.client.compare_users(u1, u2, period="1month")
        score = res["score"]
        rating = res["rating"]
        common = res["common_artists"]

        color = discord.Color.magenta() if score >= 60 else (discord.Color.blue() if score >= 30 else discord.Color.dark_grey())

        embed = discord.Embed(
            title=f"💞 Compatibilidad Musical",
            description=(
                f"Comparando a **{interaction.user.display_name}** (`{u1}`) y **{miembro.display_name}** (`{u2}`):\n\n"
                f"### Puntuación: `{score}%` — {rating}\n"
                f"Artistas en común: **{res['common_count']}**"
            ),
            color=color,
            timestamp=discord.utils.utcnow()
        )

        if common:
            top_shared = "\n".join(
                f"• **{a['name']}** (`{a['plays1']}` vs `{a['plays2']}` scrobbles)"
                for a in common[:6]
            )
            embed.add_field(name="🤝 Artistas compartidos más escuchados", value=top_shared, inline=False)

        embed.set_footer(text="Dabot Music · Basado en el último mes")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="profile", description="👤 Muestra la ficha musical y resumen de Last.fm de un usuario.")
    @app_commands.describe(usuario="Miembro a consultar (opcional, por defecto tú)")
    async def profile(self, interaction: discord.Interaction, usuario: discord.Member | None = None):
        target = usuario or interaction.user
        username = await self._get_username_for(target)

        if not username:
            msg = "❌ No tienes vinculada tu cuenta de Last.fm. Usa `/fm set <tu_usuario>`." if target.id == interaction.user.id else f"❌ **{target.display_name}** no tiene cuenta de Last.fm vinculada."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await interaction.response.defer()

        uinfo, top_artist = await asyncio.gather(
            self.client.get_user_info(username),
            self.client.get_top_artists(username, period="7day", limit=1)
        )

        if not uinfo:
            await interaction.followup.send(f"⚠️ No se pudo obtener el perfil de Last.fm de **{username}**.")
            return

        country_line = f"\n🌍 **País:** {uinfo['country']}" if uinfo.get('country') else ""
        desc = (
            f"📊 **Scrobbles totales:** `{uinfo['playcount']:,}`\n"
            f"📅 **En Last.fm desde:** {uinfo.get('registered') or 'Desconocido'}"
            f"{country_line}"
        )

        embed = discord.Embed(
            title=f"👤 Perfil Musical — {uinfo['name']}",
            url=uinfo["url"],
            description=desc,
            color=discord.Color.from_rgb(185, 0, 0),
            timestamp=discord.utils.utcnow()
        )

        if top_artist and len(top_artist) > 0:
            a = top_artist[0]
            embed.add_field(
                name="🔥 Artista #1 de la semana",
                value=f"**[{a['name']}]({a['url']})** (`{a['playcount']:,}` scrobbles)",
                inline=False
            )

        if uinfo.get("avatar"):
            embed.set_thumbnail(url=uinfo["avatar"])
        embed.set_footer(text="Dabot Music · Last.fm & Spotify", icon_url=target.display_avatar.url)

        await interaction.followup.send(embed=embed)


# Shortcut slash command `/np` directly at top-level
class NowPlayingTopCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="np", description="🎧 Muestra la canción que estás escuchando en Spotify o Last.fm.")
    @app_commands.describe(usuario="Miembro a consultar (opcional, por defecto tú)")
    async def np_slash(self, interaction: discord.Interaction, usuario: discord.Member | None = None):
        cog = self.bot.get_cog("LastFM")
        if not cog:
            await interaction.response.send_message("❌ Módulo de música no cargado.", ephemeral=True)
            return
        await cog._show_now_playing(interaction, usuario)

    # Classic prefix commands support: !fm, .fm, !np, .np
    @commands.command(name="fm", aliases=["np"])
    async def fm_prefix(self, ctx: commands.Context, member: discord.Member = None):
        """Classic prefix command for !fm or !np"""
        cog = self.bot.get_cog("LastFM")
        if not cog:
            await ctx.send("❌ Módulo de música no cargado.")
            return

        target = member or ctx.author
        username = await cog._get_username_for(target)
        if not username:
            if target.id == ctx.author.id:
                await ctx.send("❌ No tienes cuenta de Last.fm vinculada. Usa `/fm set <tu_usuario>`.")
            else:
                await ctx.send(f"❌ **{target.display_name}** no tiene cuenta de Last.fm vinculada.")
            return

        rec = await cog.client.get_recent_tracks(username, limit=2)
        if not rec or not rec.get("current"):
            await ctx.send(f"⚠️ No hay canciones recientes para **{username}**.")
            return

        track = rec["current"]
        is_now = rec.get("now_playing", False)
        total = rec.get("total_scrobbles", 0)

        track_info, artist_info = await asyncio.gather(
            cog.client.get_track_info(track["artist"], track["name"], username=username),
            cog.client.get_artist_info(track["artist"], username=username)
        )

        user_track_plays = track_info.get("userplaycount", 0)
        user_artist_plays = artist_info.get("userplaycount", 0)
        user_loved = track_info.get("userloved", False)

        color = discord.Color.from_rgb(30, 215, 96) if is_now else discord.Color.from_rgb(185, 0, 0)
        status_header = "Escuchando ahora" if is_now else "Última canción escuchada"
        heart = " ❤️" if user_loved else ""

        album_line = f"\nÁlbum: *{track['album']}*" if track.get("album") else ""
        desc = (
            f"### [{track['name']}]({track['url']}){heart}\n"
            f"de **[{track['artist']}](https://www.last.fm/music/{track['artist'].replace(' ', '+')})**"
            f"{album_line}"
        )

        embed = discord.Embed(
            title=f"🎶 {status_header} — {target.display_name}",
            description=desc,
            color=color
        )
        if track.get("image"):
            embed.set_thumbnail(url=track["image"])

        embed.add_field(name="🎵 Scrobbles del tema", value=f"`{user_track_plays}`", inline=True)
        embed.add_field(name="🎤 Scrobbles del artista", value=f"`{user_artist_plays}`", inline=True)
        embed.add_field(name="📊 Total usuario", value=f"`{total:,}`", inline=True)
        embed.set_footer(text=f"Last.fm: {username} • Dabot Music", icon_url=target.display_avatar.url)

        view = MusicLinksView(track.get("spotify_url", ""), track.get("url", ""))
        await ctx.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(LastFM(bot))
    await bot.add_cog(NowPlayingTopCommand(bot))
