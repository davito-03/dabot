import os
import sqlite3
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import logging
import random
from utils.helpers import DASHBOARD_URL
from utils import alt_intel
from utils import verify_log

class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot.Verification')

    @commands.Cog.listener()
    async def on_ready(self):
        # Register the persistent view so the "Verificar" button works across bot restarts
        self.bot.add_view(VerificationPanelView(self.bot))
        self.logger.info('Verification Cog loaded and persistent views registered.')

    async def ensure_table(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS verification_config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                verification_channel_id INTEGER NOT NULL,
                unverified_role_id INTEGER NOT NULL,
                verified_role_id INTEGER NOT NULL,
                verification_type TEXT DEFAULT 'emoji'
            )
        """)
        await alt_intel.ensure_schema_async(self.bot.db)
        try:
            await self.bot.db.execute(verify_log.SCHEMA)
            await self.bot.db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ve_guild ON verification_events(guild_id, id DESC)"
            )
        except Exception:
            pass

    def _db_path(self):
        return os.environ.get("DATABASE_PATH", "dabot.db")

    async def record_discord_sighting(self, member: discord.Member, source: str):
        def _write():
            conn = sqlite3.connect(self._db_path(), timeout=5)
            try:
                conn.execute("PRAGMA busy_timeout=5000")
                flags = int(getattr(member, "public_flags", 0) or 0)
                if hasattr(member, "public_flags") and member.public_flags:
                    try:
                        flags = int(member.public_flags.value)
                    except Exception:
                        flags = 0
                created = ""
                try:
                    created = member.created_at.replace(tzinfo=None).isoformat()
                except Exception:
                    pass
                alt_intel.record_sighting(
                    conn,
                    user_id=member.id,
                    guild_id=member.guild.id,
                    username=str(member.name),
                    global_name=str(member.global_name or member.display_name or ""),
                    account_created=created,
                    avatar_hash=getattr(member.avatar, "key", "") if member.avatar else "",
                    public_flags=flags,
                    source=source,
                )
            finally:
                conn.close()
        try:
            await asyncio.get_running_loop().run_in_executor(None, _write)
        except Exception as e:
            self.logger.warning(f"alt sighting failed: {e}")

    async def record_verification_event(self, guild, **kwargs):
        def _write():
            conn = self._alts_conn()
            try:
                return verify_log.record_full_sync(conn, **kwargs)
            finally:
                conn.close()

        try:
            _eid, ch_id, embed_d = await asyncio.get_running_loop().run_in_executor(None, _write)
        except Exception as e:
            self.logger.warning("verification event write failed: %s", e)
            return
        if not guild or not ch_id:
            return
        channel = guild.get_channel(int(ch_id))
        if not channel:
            return
        try:
            await channel.send(embed=discord.Embed.from_dict(embed_d))
        except Exception as e:
            self.logger.warning("verification discord log failed: %s", e)

    def _member_avatar(self, member) -> str:
        try:
            if getattr(member, "avatar", None):
                return member.avatar.key or ""
        except Exception:
            pass
        return ""

    def _alts_conn(self):
        conn = sqlite3.connect(self._db_path(), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # App Command Group for Verification settings
    verification_group = app_commands.Group(
        name="verification",
        description="Configuración del sistema de verificación antibots.",
        default_permissions=discord.Permissions(administrator=True)
    )

    @verification_group.command(name="setup", description="Configura el sistema de verificación del servidor.")
    @app_commands.describe(
        channel="El canal donde los usuarios completarán la verificación.",
        unverified_role="El rol que se asigna a los nuevos miembros no verificados.",
        verified_role="El rol de miembro verificado que se otorga tras pasar el reto.",
        verification_type="Tipo de reto: emoji (coincidencia de frutas) o math (cuenta aritmética)."
    )
    @app_commands.choices(verification_type=[
        app_commands.Choice(name="Navegador + dispositivo (recomendado)", value="web"),
        app_commands.Choice(name="Emoji Match (Frutas)", value="emoji"),
        app_commands.Choice(name="Operación Matemática", value="math")
    ])
    async def verification_setup(self, interaction: discord.Interaction,
                                   channel: discord.TextChannel,
                                   unverified_role: discord.Role,
                                   verified_role: discord.Role,
                                   verification_type: str = "web"):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        await self.bot.db.execute(
            """INSERT INTO verification_config
               (guild_id, enabled, verification_channel_id, unverified_role_id, verified_role_id, verification_type)
               VALUES (?, 1, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 enabled = 1,
                 verification_channel_id = excluded.verification_channel_id,
                 unverified_role_id = excluded.unverified_role_id,
                 verified_role_id = excluded.verified_role_id,
                 verification_type = excluded.verification_type""",
            interaction.guild.id, channel.id, unverified_role.id, verified_role.id, verification_type
        )

        embed = discord.Embed(
            title="🛡️ Verificación Configurada",
            description=(
                f"**Canal:** {channel.mention}\n"
                f"**Rol No Verificado:** {unverified_role.mention}\n"
                f"**Rol Verificado:** {verified_role.mention}\n"
                f"**Tipo de Reto:** `{verification_type.upper()}`\n\n"
                f"Usa `/verification send_panel` en cualquier canal para enviar el panel de verificación."
            ),
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @verification_group.command(name="send_panel", description="Envía el mensaje de verificación al canal configurado.")
    async def verification_send_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        config = await self.bot.db.fetch(
            "SELECT verification_channel_id FROM verification_config WHERE guild_id = ? AND enabled = 1",
            interaction.guild.id
        )
        if not config:
            await interaction.followup.send("❌ El sistema de verificación no está configurado o está deshabilitado.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(config[0])
        if not channel:
            await interaction.followup.send("❌ No se encontró el canal de verificación configurado.", ephemeral=True)
            return

        vtype = "web"
        try:
            row = await self.bot.db.fetch(
                "SELECT verification_type FROM verification_config WHERE guild_id = ?",
                interaction.guild.id,
            )
            if row:
                vtype = row[0] or "web"
        except Exception:
            pass
        url = f"{DASHBOARD_URL}/verify/{interaction.guild.id}"
        embed = discord.Embed(
            title="🛡️ Verificación",
            description=(
                f"Pulsa el botón y abre **dabot.davito.es/verify** con tu cuenta de Discord.\n"
                f"Un paso en el navegador. El staff de este servidor puede ver coincidencias de dispositivo.\n\n"
                f"[Abrir verificación]({url})"
            ),
            color=discord.Color.from_str("#00FF88"),
        )
        embed.set_footer(text="dabot.davito.es/verify")
        if vtype in ("emoji", "math"):
            view = VerificationPanelView(self.bot, interaction.guild.id)
        else:
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                label="Verificarse · dabot.davito.es",
                style=discord.ButtonStyle.link,
                url=url,
            ))
        await channel.send(embed=embed, view=view)
        await interaction.followup.send(f"✅ Panel de verificación enviado a {channel.mention}.", ephemeral=True)

    @verification_group.command(name="status", description="Muestra el estado actual de la verificación.")
    async def verification_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        config = await self.bot.db.fetch(
            "SELECT enabled, verification_channel_id, unverified_role_id, verified_role_id, verification_type FROM verification_config WHERE guild_id = ?",
            interaction.guild.id
        )
        if not config:
            await interaction.followup.send("❌ La verificación no ha sido configurada en este servidor.", ephemeral=True)
            return

        enabled, channel_id, unverified_role_id, verified_role_id, verification_type = config
        channel = interaction.guild.get_channel(channel_id)
        unverified_role = interaction.guild.get_role(unverified_role_id)
        verified_role = interaction.guild.get_role(verified_role_id)

        embed = discord.Embed(
            title="🛡️ Configuración de Verificación",
            color=discord.Color.blue()
        )
        embed.add_field(name="Habilitado", value="✅ Sí" if enabled else "❌ No", inline=True)
        embed.add_field(name="Canal", value=channel.mention if channel else f"ID: {channel_id} (No encontrado)", inline=True)
        embed.add_field(name="Reto", value=verification_type.upper(), inline=True)
        embed.add_field(name="Rol No Verificado", value=unverified_role.mention if unverified_role else f"ID: {unverified_role_id} (No encontrado)", inline=False)
        embed.add_field(name="Rol Verificado", value=verified_role.mention if verified_role else f"ID: {verified_role_id} (No encontrado)", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @verification_group.command(name="manual", description="Verifica a un miembro solo en este servidor (staff).")
    @app_commands.describe(miembro="Usuario a verificar en este servidor")
    async def verification_manual(self, interaction: discord.Interaction, miembro: discord.Member):
        if not interaction.guild or miembro.guild.id != interaction.guild.id:
            await interaction.response.send_message("❌ Solo vale dentro de este servidor.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()
        config = await self.bot.db.fetch(
            "SELECT enabled, unverified_role_id, verified_role_id FROM verification_config WHERE guild_id = ?",
            interaction.guild.id,
        )
        if not config or not config[0]:
            await interaction.followup.send("❌ Configura `/verification setup` primero.", ephemeral=True)
            return
        unverified_role = interaction.guild.get_role(config[1])
        verified_role = interaction.guild.get_role(config[2])
        if not verified_role:
            await interaction.followup.send("❌ No encuentro el rol verificado.", ephemeral=True)
            return
        try:
            if unverified_role and unverified_role in miembro.roles:
                await miembro.remove_roles(unverified_role, reason=f"Verificación manual por {interaction.user}")
            await miembro.add_roles(verified_role, reason=f"Verificación manual por {interaction.user} (solo {interaction.guild.id})")
        except discord.Forbidden:
            await interaction.followup.send("❌ No puedo asignar esos roles (jerarquía).", ephemeral=True)
            return
        await self.record_discord_sighting(miembro, "manual_verify")
        await self.record_verification_event(
            interaction.guild,
            guild_id=interaction.guild.id,
            user_id=miembro.id,
            username=str(miembro),
            avatar=self._member_avatar(miembro),
            method="manual",
            status="ok",
            actor_id=interaction.user.id,
            extra={"source": "slash_manual"},
        )
        await interaction.followup.send(
            f"✅ {miembro.mention} verificado **solo en {interaction.guild.name}** (`{interaction.guild.id}`). No aplica a otros servidores.",
            ephemeral=True,
        )

    @verification_group.command(name="disable", description="Deshabilita el sistema de verificación.")
    async def verification_disable(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        await self.bot.db.execute(
            "UPDATE verification_config SET enabled = 0 WHERE guild_id = ?",
            interaction.guild.id
        )
        await interaction.followup.send("✅ Sistema de verificación deshabilitado.", ephemeral=True)

    @verification_group.command(name="logs", description="Canal donde se publican las detecciones de multicuenta (con botones).")
    @app_commands.describe(channel="Canal de staff. Si no pones ninguno, se usa el canal actual.")
    async def verification_logs(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()
        dest = channel or interaction.channel
        self.bot.config.set_config(interaction.guild.id, "logs.alts", str(dest.id))

        def _write():
            conn = self._alts_conn()
            try:
                alt_intel.set_alts_channel(conn, interaction.guild.id, dest.id)
            finally:
                conn.close()

        await asyncio.get_running_loop().run_in_executor(None, _write)
        await interaction.followup.send(
            f"✅ Las detecciones de multicuenta se enviarán a {dest.mention} con botones para aprobar, denegar, banear o permitir siempre.",
            ephemeral=True,
        )

    @verification_group.command(name="logchannel", description="Canal de logs de cada verificación (usuario, método, riesgo).")
    @app_commands.describe(channel="Canal de staff. Si no pones ninguno, se usa el canal actual.")
    async def verification_logchannel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        dest = channel or interaction.channel
        self.bot.config.set_config(interaction.guild.id, "logs.verification", str(dest.id))
        await interaction.followup.send(
            f"✅ Cada verificación de este servidor se registrará en {dest.mention} "
            f"(navegador, reto, staff). El listado completo está en {DASHBOARD_URL}/dashboard.",
            ephemeral=True,
        )

    @verification_group.command(name="history", description="Lista reciente de gente verificada en este servidor.")
    @app_commands.describe(limit="Cuántas entradas mostrar (1-25)")
    async def verification_history(self, interaction: discord.Interaction, limit: int = 15):
        await interaction.response.defer(ephemeral=True)
        lim = max(1, min(int(limit or 15), 25))

        def _load():
            conn = self._alts_conn()
            try:
                people = verify_log.list_people_sync(conn, guild_id=interaction.guild.id, limit=lim)
                stats = verify_log.stats_sync(conn, interaction.guild.id)
                return people, stats
            finally:
                conn.close()

        people, stats = await asyncio.get_running_loop().run_in_executor(None, _load)
        if not people:
            await interaction.followup.send(
                "Nadie se ha verificado todavía (o el registro es nuevo). "
                f"El historial también está en {DASHBOARD_URL}/dashboard.",
                ephemeral=True,
            )
            return
        lines = []
        for i, p in enumerate(people, 1):
            uid = p.get("user_id")
            when = (p.get("created_at") or "")[:16].replace("T", " ")
            method = verify_log.METHOD_LABELS.get(p.get("method") or "", p.get("method") or "")
            lines.append(f"`{i}.` <@{uid}> `{uid}` · {method} · {when}")
        embed = discord.Embed(
            title="🛡️ Gente verificada",
            description="\n".join(lines)[:4000],
            color=discord.Color.from_str("#00FF88"),
        )
        embed.set_footer(
            text=f"{stats.get('people') or 0} personas · {stats.get('events') or 0} eventos · dabot.davito.es"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @verification_group.command(name="alts", description="Busca multicuentas ligadas a un usuario (IP, dispositivo, coincidencias).")
    @app_commands.describe(usuario="Cuenta a investigar")
    async def verification_alts(self, interaction: discord.Interaction, usuario: discord.Member):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        def _load():
            conn = self._alts_conn()
            try:
                return alt_intel.user_dossier(
                    conn, usuario.id, current_guild=interaction.guild.id, viewer_id=interaction.user.id
                )
            finally:
                conn.close()

        dossier = await asyncio.get_running_loop().run_in_executor(None, _load)
        kept = []
        for a in dossier.get("alts") or []:
            try:
                oid = int(a.get("user_id"))
            except (TypeError, ValueError):
                continue
            member = interaction.guild.get_member(oid)
            if not member:
                try:
                    member = await interaction.guild.fetch_member(oid)
                except Exception:
                    member = None
            if member:
                kept.append(a)
        dossier["alts"] = kept
        dossier["score"] = kept[0]["score"] if kept else 0
        score = dossier.get("score") or 0
        color = discord.Color.red() if score >= 70 else discord.Color.gold() if score >= 40 else discord.Color.green()
        embed = discord.Embed(
            title=f"Multicuentas · {usuario.display_name}",
            description=alt_intel.summarize_for_embed(dossier),
            color=color,
        )
        embed.add_field(name="Alcance", value="Red compartida" if dossier.get("network") else "Solo este servidor", inline=True)
        embed.add_field(name="Avistamientos", value=str(len(dossier.get("sightings") or [])), inline=True)
        last = (dossier.get("sightings") or [{}])[0]
        if last:
            bits = []
            if last.get("ip"):
                bits.append(f"IP: `{last.get('ip')}`")
            if last.get("ua_summary"):
                bits.append(last["ua_summary"])
            if last.get("country"):
                bits.append(last["country"])
            if bits:
                embed.add_field(name="Última huella", value=" · ".join(bits)[:1024], inline=False)
        embed.set_footer(text="Códigos ip:/net: · misma clave = misma red · dabot.davito.es")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Abrir en el panel",
            style=discord.ButtonStyle.link,
            url=f"{DASHBOARD_URL}/dashboard",
        ))
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @verification_group.command(name="network", description="(Super owner) Aprueba o saca este servidor de la red compartida de alts.")
    @app_commands.describe(accion="enable = compartir inteligencia con otros servidores aprobados")
    @app_commands.choices(accion=[
        app_commands.Choice(name="Aprobar este servidor en la red", value="enable"),
        app_commands.Choice(name="Sacar de la red", value="disable"),
        app_commands.Choice(name="Listar red", value="list"),
    ])
    async def verification_network(self, interaction: discord.Interaction, accion: str):
        if interaction.user.id != getattr(self.bot, "super_owner_id", 0):
            await interaction.response.send_message("Solo el super owner puede gestionar la red de inteligencia.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.ensure_table()

        def _run():
            conn = self._alts_conn()
            try:
                if accion == "enable":
                    alt_intel.set_network(conn, interaction.guild.id, True, interaction.user.id, interaction.guild.name)
                elif accion == "disable":
                    alt_intel.set_network(conn, interaction.guild.id, False, interaction.user.id, "")
                return sorted(alt_intel.network_guilds(conn))
            finally:
                conn.close()

        ids = await asyncio.get_running_loop().run_in_executor(None, _run)
        names = []
        for gid in ids:
            g = self.bot.get_guild(gid)
            names.append(f"• {g.name if g else gid} (`{gid}`)")
        desc = "\n".join(names) if names else "_Ningún servidor en la red._"
        title = "Red de inteligencia de multicuentas"
        if accion == "enable":
            title = "Servidor añadido a la red"
        elif accion == "disable":
            title = "Servidor sacado de la red"
        embed = discord.Embed(title=title, description=desc, color=discord.Color.from_str("#00FF88"))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        await self.ensure_table()
        config = await self.bot.db.fetch(
            "SELECT enabled, unverified_role_id FROM verification_config WHERE guild_id = ?",
            member.guild.id
        )
        if not config or not config[0]:
            return

        unverified_role_id = config[1]
        role = member.guild.get_role(unverified_role_id)
        if role:
            try:
                await member.add_roles(role, reason="Asignación automática de rol no verificado (Protección Antibots)")
                self.logger.info(f"Aplicado rol no verificado a {member} en {member.guild.name}")
            except discord.Forbidden:
                self.logger.warning(f"No se pudo asignar el rol no verificado a {member} en {member.guild.name}: Sin permisos.")
        await self.record_discord_sighting(member, "join")

    async def start_verification(self, interaction: discord.Interaction):
        await self.ensure_table()
        config = await self.bot.db.fetch(
            "SELECT enabled, unverified_role_id, verified_role_id, verification_type FROM verification_config WHERE guild_id = ?",
            interaction.guild.id
        )
        if not config or not config[0]:
            await interaction.response.send_message("❌ El sistema de verificación no está configurado en este servidor.", ephemeral=True)
            return

        unverified_role_id, verified_role_id, verification_type = config[1], config[2], config[3]
        verified_role = interaction.guild.get_role(verified_role_id)

        # Check if already verified
        if verified_role and verified_role in interaction.user.roles:
            await interaction.response.send_message("✅ Ya estás verificado en este servidor.", ephemeral=True)
            return

        if verification_type == "web":
            url = f"{DASHBOARD_URL}/verify/{interaction.guild.id}"
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Verificar con el navegador", style=discord.ButtonStyle.link, url=url))
            await interaction.response.send_message(
                f"🛡️ **{url}**\n"
                "Open **dabot.davito.es/verify** with Discord — one step in the browser.\n"
                "Abre el enlace con Discord: un paso en el navegador.",
                view=view,
                ephemeral=True,
            )
            await self.record_discord_sighting(interaction.user, "verify_start")
            return

        if verification_type == "emoji":
            # List of fruit emojis and their names in Spanish
            emojis = [
                ("🍎", "Manzana"),
                ("🍌", "Plátano"),
                ("🍒", "Cereza"),
                ("🍇", "Uva"),
                ("🍉", "Sandía"),
                ("🍓", "Fresa"),
                ("🍍", "Piña"),
                ("🍋", "Limón"),
                ("🍊", "Naranja"),
                ("🍐", "Pera")
            ]
            target_emoji, target_name = random.choice(emojis)
            decoys = random.sample([e for e in emojis if e[0] != target_emoji], 4)
            choices = decoys + [(target_emoji, target_name)]
            random.shuffle(choices)

            view = EmojiVerificationView(target_emoji, choices, verified_role_id, unverified_role_id, interaction.user.id, self)
            await interaction.response.send_message(
                f"🛡️ **Reto de verificación:**\nPor favor, haz clic en el botón con la **{target_name} {target_emoji}** para verificar que eres humano.",
                view=view,
                ephemeral=True
            )

        elif verification_type == "math":
            # Basic math challenge
            num1 = random.randint(1, 15)
            num2 = random.randint(1, 10)
            operator = random.choice(['+', '-'])
            
            if operator == '+':
                correct_answer = num1 + num2
            else:
                if num1 < num2:
                    num1, num2 = num2, num1
                correct_answer = num1 - num2

            # Generate decoy choices
            decoys = set()
            while len(decoys) < 3:
                decoy = correct_answer + random.randint(-5, 5)
                if decoy != correct_answer and decoy >= 0:
                    decoys.add(decoy)
            
            choices = list(decoys) + [correct_answer]
            random.shuffle(choices)

            view = MathVerificationView(correct_answer, choices, verified_role_id, unverified_role_id, interaction.user.id, self)
            await interaction.response.send_message(
                f"🛡️ **Reto de verificación:**\n¿Cuánto es **{num1} {operator} {num2}**? Selecciona la respuesta correcta de abajo.",
                view=view,
                ephemeral=True
            )

    async def complete_verification(self, interaction: discord.Interaction, verified_role_id: int, unverified_role_id: int, method: str = "emoji"):
        member = interaction.user
        verified_role = interaction.guild.get_role(verified_role_id)
        unverified_role = interaction.guild.get_role(unverified_role_id)

        if not verified_role:
            await interaction.response.send_message("❌ Error: No se pudo encontrar el rol de verificado configurado.", ephemeral=True)
            return

        roles_to_add = [verified_role]
        roles_to_remove = []
        if unverified_role and unverified_role in member.roles:
            roles_to_remove.append(unverified_role)

        try:
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Verificación completada con éxito.")
            await member.add_roles(*roles_to_add, reason="Verificación completada con éxito.")
            
            url = f"{DASHBOARD_URL}/verify/{interaction.guild.id}"
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Registrar dispositivo (recomendado)", style=discord.ButtonStyle.link, url=url))
            await interaction.response.send_message(
                "✅ ¡Verificación completada! Ya tienes acceso.\n"
                "Opcional: registra tu navegador para que el staff pueda detectar multicuentas.",
                view=view,
                ephemeral=True,
            )
            self.logger.info(f"Miembro verificado con éxito: {member} en {interaction.guild.name}")
            await self.record_discord_sighting(member, "verify")
            await self.record_verification_event(
                interaction.guild,
                guild_id=interaction.guild.id,
                user_id=member.id,
                username=str(member),
                avatar=self._member_avatar(member),
                method=method or "emoji",
                status="ok",
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Hubo un error de permisos al intentar asignarte los roles. "
                "Por favor, notifica a un administrador (asegúrate de que el rol jerárquico del bot está por encima de los roles de verificación).",
                ephemeral=True
            )
            self.logger.error(f"Falta de permisos al otorgar roles de verificación en {interaction.guild.name}")
        except Exception as e:
            await interaction.response.send_message(f"❌ Ocurrió un error inesperado al procesar la verificación: {e}", ephemeral=True)
            self.logger.error(f"Error inesperado en verificación en {interaction.guild.name}: {e}")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if not interaction.data or interaction.type != discord.InteractionType.component:
            return
        cid = str(interaction.data.get("custom_id") or "")
        if not cid.startswith("dabot:alt:"):
            return
        parts = cid.split(":")
        if len(parts) < 4:
            return
        action, case_raw = parts[2], parts[3]
        try:
            case_id = int(case_raw)
        except ValueError:
            return
        await self._handle_alt_case(interaction, action, case_id)

    async def _handle_alt_case(self, interaction: discord.Interaction, action: str, case_id: int):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Solo en un servidor.", ephemeral=True)
            return
        allowed = (
            member.guild_permissions.administrator
            or member.guild_permissions.ban_members
            or member.guild_permissions.kick_members
            or member.guild_permissions.manage_guild
            or member.id == getattr(self.bot, "super_owner_id", 0)
        )
        if not allowed:
            await interaction.response.send_message("Necesitas permisos de moderación.", ephemeral=True)
            return
        await interaction.response.defer()

        def _load():
            conn = self._alts_conn()
            try:
                row = alt_intel.get_case(conn, case_id)
                return None if not row else dict(row)
            finally:
                conn.close()

        case = await asyncio.get_running_loop().run_in_executor(None, _load)
        if not case:
            await interaction.followup.send("Caso no encontrado.", ephemeral=True)
            return
        if int(case["guild_id"]) != interaction.guild.id:
            await interaction.followup.send("Este caso no es de este servidor.", ephemeral=True)
            return
        target_id = int(case["user_id"])
        status_map = {"ok": "approved", "no": "denied", "ban": "banned", "always": "allow_always"}
        new_status = status_map.get(action)
        if not new_status:
            return

        note = ""
        color = discord.Color.green()
        try:
            target = interaction.guild.get_member(target_id) or await interaction.guild.fetch_member(target_id)
        except Exception:
            target = None

        if action in ("ok", "always"):
            cfg = await self.bot.db.fetch(
                "SELECT unverified_role_id, verified_role_id FROM verification_config WHERE guild_id = ?",
                interaction.guild.id,
            )
            if cfg and target:
                unverified_role = interaction.guild.get_role(int(cfg[0]))
                verified_role = interaction.guild.get_role(int(cfg[1]))
                try:
                    if unverified_role and unverified_role in target.roles:
                        await target.remove_roles(unverified_role, reason=f"Alt case #{case_id} {action} by {member}")
                    if verified_role:
                        await target.add_roles(verified_role, reason=f"Alt case #{case_id} {action} by {member}")
                except discord.Forbidden:
                    note = " (no pude cambiar roles: jerarquía)"
            if action == "always":
                def _pol():
                    conn = self._alts_conn()
                    try:
                        alt_intel.set_policy(conn, interaction.guild.id, target_id, "allow_always", member.id)
                    finally:
                        conn.close()
                await asyncio.get_running_loop().run_in_executor(None, _pol)
                color = discord.Color.from_str("#00FF88")
                result_txt = f"Permitido siempre meter multicuentas.{note}"
            else:
                result_txt = f"Multicuenta aprobada. Acceso concedido.{note}"
        elif action == "no":
            def _pol():
                conn = self._alts_conn()
                try:
                    alt_intel.set_policy(conn, interaction.guild.id, target_id, "deny", member.id)
                finally:
                    conn.close()
            await asyncio.get_running_loop().run_in_executor(None, _pol)
            color = discord.Color.orange()
            result_txt = "Multicuenta denegada. Se queda sin rol verificado."
        else:
            try:
                await interaction.guild.ban(
                    discord.Object(id=target_id),
                    reason=f"Multicuenta caso #{case_id} por {member}",
                )
                result_txt = "Usuario baneado por multicuenta."
            except Exception as e:
                result_txt = f"No se pudo banear: {e}"
            color = discord.Color.red()

        def _res():
            conn = self._alts_conn()
            try:
                alt_intel.resolve_case(conn, case_id, new_status, member.id)
            finally:
                conn.close()
        await asyncio.get_running_loop().run_in_executor(None, _res)

        v_status = "ok" if action in ("ok", "always") else "denied"
        await self.record_verification_event(
            interaction.guild,
            guild_id=interaction.guild.id,
            user_id=target_id,
            username=str(target) if target else (case.get("username") or str(target_id)),
            avatar=self._member_avatar(target) if target else "",
            method="alt_approve",
            status=v_status,
            actor_id=member.id,
            case_id=case_id,
            extra={"action": action, "new_status": new_status, "source": "discord"},
        )

        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else discord.Embed()
        embed.color = color
        embed.add_field(
            name="Resolución",
            value=f"{result_txt}\nPor {member.mention} · `{new_status}`",
            inline=False,
        )
        try:
            await interaction.message.edit(embed=embed, view=None)
        except Exception:
            pass
        await interaction.followup.send(result_txt, ephemeral=True)


# View for the persistent panel
class VerificationPanelView(discord.ui.View):
    def __init__(self, bot, guild_id: int | None = None):
        super().__init__(timeout=None)
        self.bot = bot
        if guild_id:
            self.add_item(discord.ui.Button(
                label="Navegador / dispositivo",
                style=discord.ButtonStyle.link,
                url=f"{DASHBOARD_URL}/verify/{guild_id}",
            ))

    @discord.ui.button(label="Verificar", style=discord.ButtonStyle.green, emoji="🛡️", custom_id="verify_panel_button_v1")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("Verification")
        if not cog:
            await interaction.response.send_message("❌ El sistema de verificación no está disponible.", ephemeral=True)
            return
        await cog.start_verification(interaction)


# View for Emoji Challenges
class EmojiVerificationView(discord.ui.View):
    def __init__(self, target_emoji, choices, verified_role_id, unverified_role_id, user_id, cog):
        super().__init__(timeout=60)
        self.target_emoji = target_emoji
        self.verified_role_id = verified_role_id
        self.unverified_role_id = unverified_role_id
        self.user_id = user_id
        self.cog = cog

        for emoji_char, emoji_name in choices:
            btn = discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=emoji_char,
                custom_id=f"emoji_verify_btn_{emoji_char}"
            )
            btn.callback = self.make_callback(emoji_char)
            self.add_item(btn)

    def make_callback(self, chosen_emoji):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ Esta sesión de verificación no es para ti.", ephemeral=True)
                return

            if chosen_emoji == self.target_emoji:
                await self.cog.complete_verification(interaction, self.verified_role_id, self.unverified_role_id, method="emoji")
            else:
                await interaction.response.send_message("❌ Selección incorrecta. Por favor, intenta verificar de nuevo desde el botón del panel.", ephemeral=True)
            self.stop()
        return callback

    async def on_timeout(self):
        # View timed out, disable buttons
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


# View for Math Challenges
class MathVerificationView(discord.ui.View):
    def __init__(self, correct_answer, choices, verified_role_id, unverified_role_id, user_id, cog):
        super().__init__(timeout=60)
        self.correct_answer = correct_answer
        self.verified_role_id = verified_role_id
        self.unverified_role_id = unverified_role_id
        self.user_id = user_id
        self.cog = cog

        for option in choices:
            btn = discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                label=str(option),
                custom_id=f"math_verify_btn_{option}"
            )
            btn.callback = self.make_callback(option)
            self.add_item(btn)

    def make_callback(self, chosen_option):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ Esta sesión de verificación no es para ti.", ephemeral=True)
                return

            if chosen_option == self.correct_answer:
                await self.cog.complete_verification(interaction, self.verified_role_id, self.unverified_role_id, method="math")
            else:
                await interaction.response.send_message("❌ Respuesta incorrecta. Por favor, intenta verificar de nuevo desde el botón del panel.", ephemeral=True)
            self.stop()
        return callback

    async def on_timeout(self):
        # View timed out, disable buttons
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


async def setup(bot):
    await bot.add_cog(Verification(bot))
