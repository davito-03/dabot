import json
import os
import re
import logging
import copy
import discord
from discord import app_commands

SUPPORTED_LOCALES = ("es", "en", "fr", "de", "pt", "it", "ja", "ko", "zh")
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def uniquify_placeholders(text: str) -> str:
    """Turn repeated {mention} tokens into {mention}, {mention_2}, ..."""
    counts = {}

    def repl(match):
        name = match.group(1)
        counts[name] = counts.get(name, 0) + 1
        if counts[name] == 1:
            return match.group(0)
        return "{" + name + "_" + str(counts[name]) + "}"

    return _PLACEHOLDER_RE.sub(repl, text)


def template_to_regex(template: str):
    tmpl = uniquify_placeholders(template)
    tokens = []
    pos = 0
    for match in _PLACEHOLDER_RE.finditer(tmpl):
        tokens.append(("lit", tmpl[pos:match.start()]))
        tokens.append(("var", match.group(1)))
        pos = match.end()
    tokens.append(("lit", tmpl[pos:]))
    var_indexes = [i for i, tok in enumerate(tokens) if tok[0] == "var"]
    last_var = var_indexes[-1] if var_indexes else None
    parts = ["^"]
    for i, (kind, val) in enumerate(tokens):
        if kind == "lit":
            parts.append(re.escape(val))
        else:
            greedy = "+" if i == last_var else "+?"
            parts.append(f"(?P<{val}>[\\s\\S]{greedy})")
    parts.append("$")
    return re.compile("".join(parts))


# Runtime strings are deliberately kept separate from command descriptions.
# Discord translates command metadata at sync time, while these strings must be
# resolved for the guild that is using the command.
RUNTIME_TRANSLATIONS = {
    "es": {
        "common": {
            "valid_amount": "Introduce una cantidad válida.",
            "positive_amount": "La cantidad debe ser positiva.",
            "nonnegative_amount": "La cantidad no puede ser negativa.",
            "insufficient_wallet": "No tienes suficiente dinero en la cartera.",
            "insufficient_bank": "No tienes suficiente dinero en el banco.",
            "insufficient_money": "No tienes suficiente dinero.",
            "no_guild_economy": "La economía funciona por servidor. Usa este comando dentro de un servidor.",
            "invalid_coin": "Indica heads/cara o tails/cruz.",
            "self_money": "No puedes darte dinero a ti mismo.",
            "self_item": "No puedes darte objetos a ti mismo.",
            "invalid_type": "El tipo debe ser «wallet» o «bank».",
            "empty_inventory": "{member} no tiene objetos en su inventario.",
            "not_in_shop": "Ese objeto no está en la tienda de este servidor.",
            "cooldown_hours": "Puedes volver a usar este comando en {hours} horas.",
            "cooldown_minutes": "Puedes volver a usar este comando en {minutes} minutos.",
            "command_help": "Usa `/eco balance`, `/eco work`, `/eco shop`, etc.",
            "admin_command_help": "Usa `/ecoadmin additem`, `/ecoadmin setmoney`, etc.",
            "cooldown_seconds": "⏳ Espera {seconds:.1f}s antes de volver a usar este comando.",
            "missing_permissions": "⛔ No tienes permisos para usar este comando.",
            "bot_missing_permissions": "⛔ Me faltan permisos: `{missing}`.",
            "usage": "ℹ️ Uso: `{prefix}{command} {signature}`",
            "nsfw_only": "🔞 Este comando solo se puede usar en canales NSFW.",
            "command_failed": "❌ Ese comando falló. Inténtalo de nuevo.",
        },
        "economy": {
            "balance_title": "Saldo de {member}",
            "balance_description": "Economía de **{guild}** (no se comparte con otros servidores).",
            "wallet": "Cartera", "bank": "Banco", "total": "Total",
            "deposit": "Depositaste {symbol} {amount} en el banco de este servidor.",
            "withdraw": "Retiraste {symbol} {amount} del banco de este servidor.",
            "work": "Trabajaste de **{job}** en **{guild}** y ganaste **{symbol} {amount}**.",
            "daily": "Recompensa diaria de **{guild}**: **{symbol} {amount}**.",
            "crime_success": "El crimen salió bien: **{symbol} {amount}**.",
            "crime_caught": "Te pillaron. Multa: **{symbol} {amount}**.",
            "coin_win": "Salió **{outcome}**. Ganaste **{symbol} {amount}**.",
            "coin_loss": "Salió **{outcome}**. Perdiste **{symbol} {amount}**.",
            "dice_user": "Tú sacaste: **{roll}**\nEl bot sacó: **{bot_roll}**\n",
            "dice_draw": "Empate, el dinero vuelve.",
            "dice_win": "Ganaste **{symbol} {amount}**.",
            "dice_loss": "Perdiste **{symbol} {amount}**.",
            "shop_title": "Tienda de {guild}",
            "shop_empty": "La tienda de este servidor está vacía. Un admin puede usar `/ecoadmin additem`.",
            "need_for_purchase": "Necesitas **{symbol} {cost}** para comprar {quantity}x {item}.",
            "purchase": "Compraste {quantity}x **{item}** por **{symbol} {cost}**.",
            "give_money": "💸 {author} dio **{symbol} {amount}** a {member} en este servidor.",
            "give_item": "📦 {author} dio 1 **{item}** a {member}.",
            "inventory_title": "Inventario - {member}",
            "top_title": "💰 Economía · {guild}",
            "top_empty": "Nadie ha ganado dinero aquí todavía.",
            "item_added": "Objeto **{item}** añadido a la tienda de este servidor · {symbol} {price}.",
            "item_removed": "Objeto **{item}** quitado de la tienda de este servidor.",
            "money_added": "Añadido **{symbol} {amount}** a {member} en **{guild}**.",
            "money_removed": "Quitado **{symbol} {amount}** a {member} en este servidor.",
            "money_set": "{member} ahora tiene **{symbol} {amount}** en {type} de este servidor.",
        },
        "leveling": {
            "rank_card_title": "Tarjeta de nivel - {member}",
            "server_level": "Nivel (servidor)", "server_xp": "XP del servidor", "global_level": "Nivel global",
            "leaderboard_title": "🌍 Clasificación del servidor", "leaderboard_empty": "¡Todavía nadie ha conseguido XP!",
            "level_min": "El nivel debe ser al menos 1.",
            "level_set": "El nivel de {member} ahora es **{level}** (XP reiniciada a 0).",
            "xp_set": "El XP de {member} ahora es **{amount}**. Nivel **{level}** con **{xp}** XP.",
            "channel_set": "✅ Anuncios de subida de nivel → {channel}", "channel_default": "✅ Anuncios de subida de nivel → mismo canal del mensaje.",
            "role_level_min": "❌ El nivel debe ser 1 o superior.", "role_updated": "✅ Recompensa del nivel **{level}** actualizada a {role}.",
            "role_set": "✅ {role} será la recompensa del nivel **{level}**.", "roles_empty": "❌ No hay roles de nivel configurados. Usa `/level addrole`.",
            "role_missing": "❌ No hay recompensa para el nivel **{level}**.", "role_removed": "✅ Recompensa del nivel **{level}** eliminada.",
            "background_updated": "✅ Fondo actualizado", "bot_name_set": "✅ Nombre del bot establecido: **{name}**",
            "avatar_updated": "✅ Avatar del bot actualizado", "leveling_enabled": "✅ Sistema de niveles **{status}**.",
            "custom_text_default": "Nivel {level} · {xp} XP", "status_on": "activado", "status_off": "desactivado",
        },
        "moderation": {
            "dm_title": "Sanción de Dabot — Caso #{case_id}",
            "dm_title_nocase": "Sanción de Dabot",
            "action_warn": "Advertencia",
            "action_kick": "Expulsión",
            "action_ban": "Ban",
            "action_timeout": "Timeout",
            "action_tempban": "Ban temporal",
            "action_unban": "Desbaneo",
            "action_unwarn": "Sanción eliminada",
            "default_body": "Has recibido una sanción (**{action}**) en **{guild}**.\nMotivo: {reason}",
            "origin_name": "Servidor de origen",
            "origin_members": "Miembros",
            "origin_age": "Antigüedad",
            "origin_id": "ID del servidor",
            "origin_name_clash": "Hay otro servidor con el mismo nombre. Comprueba el ID de arriba para confirmar el origen.",
            "origin_new": "Este servidor se creó hace menos de 14 días.",
            "origin_verified": "Servidor verificado por Dabot.",
            "appeal_button": "Apelar",
            "links_warning": "El motivo incluye enlaces. Dabot no los comprueba; no pulses nada que no reconozcas.",
            "footer": "Dabot · dabot.davito.es · ID servidor {guild_id}",
            "age_days": "{days} día(s) (creado el {date})",
            "age_years": "{years} año(s) y {days} día(s) (creado el {date})",
            "age_unknown": "desconocida",
            "staff_dm_sent": "📬 MD entregado al usuario.",
            "staff_dm_blocked": "📬 No se pudo entregar el MD (tiene los privados cerrados o bloqueó al bot).",
            "staff_dm_not_member": "📬 No se envió MD: el usuario no está en este servidor (así no se avisa a gente de otros servers).",
            "staff_dm_failed": "📬 No se pudo entregar el MD.",
            "staff_dm_rate_limited": "📬 MD no enviado: se evitó un envío repetido o un posible abuso.",
        },
    },
    "en": {
        "common": {
            "valid_amount": "Please enter a valid amount.", "positive_amount": "Amount must be positive.",
            "nonnegative_amount": "Amount must not be negative.", "insufficient_wallet": "You don't have enough money in your wallet.",
            "insufficient_bank": "You don't have enough money in your bank.", "insufficient_money": "You don't have enough money.",
            "no_guild_economy": "The economy is per server. Use this command inside a server.",
            "invalid_coin": "Please specify heads/cara or tails/cruz.", "self_money": "You cannot give money to yourself.",
            "self_item": "You cannot give items to yourself.", "invalid_type": "Type must be 'wallet' or 'bank'.",
            "empty_inventory": "{member} has an empty inventory.", "not_in_shop": "That item is not in this server's shop.",
            "cooldown_hours": "You can use this command again in {hours} hours.",
            "cooldown_minutes": "You can use this command again in {minutes} minutes.",
            "command_help": "Use `/eco balance`, `/eco work`, `/eco shop`, etc.",
            "admin_command_help": "Use `/ecoadmin additem`, `/ecoadmin setmoney`, etc.",
            "cooldown_seconds": "⏳ Wait {seconds:.1f}s before using this command again.",
            "missing_permissions": "⛔ You do not have permission to use this command.",
            "bot_missing_permissions": "⛔ I am missing these permissions: `{missing}`.",
            "usage": "ℹ️ Usage: `{prefix}{command} {signature}`",
            "nsfw_only": "🔞 This command can only be used in NSFW channels.",
            "command_failed": "❌ That command failed. Please try again.",
        },
        "economy": {
            "balance_title": "{member}'s balance", "balance_description": "Economy of **{guild}** (not shared with other servers).",
            "wallet": "Wallet", "bank": "Bank", "total": "Total", "deposit": "Deposited {symbol} {amount} into this server's bank.",
            "withdraw": "Withdrew {symbol} {amount} from this server's bank.", "work": "You worked as a **{job}** in **{guild}** and earned **{symbol} {amount}**.",
            "daily": "Daily reward for **{guild}**: **{symbol} {amount}**.", "crime_success": "The crime succeeded: **{symbol} {amount}**.",
            "crime_caught": "You were caught. Fine: **{symbol} {amount}**.", "coin_win": "It landed on **{outcome}**. You won **{symbol} {amount}**.",
            "coin_loss": "It landed on **{outcome}**. You lost **{symbol} {amount}**.", "dice_user": "You rolled: **{roll}**\nBot rolled: **{bot_roll}**\n",
            "dice_draw": "Draw, your money is returned.", "dice_win": "You won **{symbol} {amount}**.", "dice_loss": "You lost **{symbol} {amount}**.",
            "shop_title": "{guild} shop", "shop_empty": "This server's shop is empty. An admin can use `/ecoadmin additem`.",
            "need_for_purchase": "You need **{symbol} {cost}** to buy {quantity}x {item}.", "purchase": "You bought {quantity}x **{item}** for **{symbol} {cost}**.",
            "give_money": "💸 {author} gave **{symbol} {amount}** to {member} in this server.", "give_item": "📦 {author} gave 1 **{item}** to {member}.",
            "inventory_title": "Inventory - {member}", "top_title": "💰 Economy · {guild}", "top_empty": "Nobody has earned money here yet.",
            "item_added": "Item **{item}** added to this server's shop · {symbol} {price}.", "item_removed": "Item **{item}** removed from this server's shop.",
            "money_added": "Added **{symbol} {amount}** to {member} in **{guild}**.", "money_removed": "Removed **{symbol} {amount}** from {member} in this server.",
            "money_set": "{member} now has **{symbol} {amount}** in their {type} in this server.",
        },
        "leveling": {
            "rank_card_title": "Level card - {member}", "server_level": "Server level", "server_xp": "Server XP", "global_level": "Global level",
            "leaderboard_title": "🌍 Server leaderboard", "leaderboard_empty": "No one has gained XP yet!", "level_min": "Level must be at least 1.",
            "level_set": "Set {member}'s level to **{level}** (XP reset to 0).", "xp_set": "Set {member}'s XP to **{amount}**. Now level **{level}** with **{xp}** XP.",
            "channel_set": "✅ Level-up announcements → {channel}", "channel_default": "✅ Level-up announcements → same channel as message.",
            "role_level_min": "❌ Level must be 1 or higher.", "role_updated": "✅ Updated level **{level}** reward to {role}.",
            "role_set": "✅ Set {role} as reward for level **{level}**.", "roles_empty": "❌ No level roles configured. Use `/level addrole`.",
            "role_missing": "❌ No role reward for level **{level}**.", "role_removed": "✅ Removed role reward for level **{level}**.",
            "background_updated": "✅ Background updated", "bot_name_set": "✅ Bot name set to: **{name}**", "avatar_updated": "✅ Bot avatar updated",
            "leveling_enabled": "✅ Leveling system **{status}**.", "custom_text_default": "Level {level} · {xp} XP", "status_on": "enabled", "status_off": "disabled",
        },
        "moderation": {
            "dm_title": "Dabot sanction — Case #{case_id}",
            "dm_title_nocase": "Dabot sanction",
            "action_warn": "Warning",
            "action_kick": "Kick",
            "action_ban": "Ban",
            "action_timeout": "Timeout",
            "action_tempban": "Temporary ban",
            "action_unban": "Unban",
            "action_unwarn": "Sanction removed",
            "default_body": "You received a sanction (**{action}**) in **{guild}**.\nReason: {reason}",
            "origin_name": "Origin server",
            "origin_members": "Members",
            "origin_age": "Server age",
            "origin_id": "Server ID",
            "origin_name_clash": "There is another server with the same name. Check the ID above to confirm the origin.",
            "origin_new": "This server was created less than 14 days ago.",
            "origin_verified": "Server verified by Dabot.",
            "appeal_button": "Appeal",
            "links_warning": "The reason includes links. Dabot does not check them; do not click anything you do not recognize.",
            "footer": "Dabot · dabot.davito.es · server ID {guild_id}",
            "age_days": "{days} day(s) (created {date})",
            "age_years": "{years} year(s) and {days} day(s) (created {date})",
            "age_unknown": "unknown",
            "staff_dm_sent": "📬 DM delivered to the user.",
            "staff_dm_blocked": "📬 Could not deliver the DM (user has DMs closed or blocked the bot).",
            "staff_dm_not_member": "📬 DM not sent: the user is not in this server (prevents messaging people from other servers).",
            "staff_dm_failed": "📬 Could not deliver the DM.",
            "staff_dm_rate_limited": "📬 DM not sent: a repeated send or possible abuse was blocked.",
        },
    },
    "de": {
        "common": {
            "valid_amount": "Bitte gib einen gültigen Betrag ein.",
            "positive_amount": "Der Betrag muss positiv sein.",
            "nonnegative_amount": "Der Betrag darf nicht negativ sein.",
            "insufficient_wallet": "Du hast nicht genug Geld in deiner Brieftasche.",
            "insufficient_bank": "Du hast nicht genug Geld auf der Bank.",
            "insufficient_money": "Du hast nicht genug Geld.",
            "no_guild_economy": "Die Wirtschaft ist serverbezogen. Verwende diesen Befehl auf einem Server.",
            "invalid_coin": "Gib heads/cara oder tails/cruz an.",
            "self_money": "Du kannst dir selbst kein Geld geben.",
            "self_item": "Du kannst dir selbst keine Gegenstände geben.",
            "invalid_type": "Der Typ muss 'wallet' oder 'bank' sein.",
            "empty_inventory": "{member} hat ein leeres Inventar.",
            "not_in_shop": "Dieser Gegenstand ist nicht im Shop dieses Servers.",
            "cooldown_hours": "Du kannst diesen Befehl in {hours} Stunden wieder verwenden.",
            "cooldown_minutes": "Du kannst diesen Befehl in {minutes} Minuten wieder verwenden.",
            "command_help": "Verwende `/eco balance`, `/eco work`, `/eco shop` usw.",
            "admin_command_help": "Verwende `/ecoadmin additem`, `/ecoadmin setmoney` usw.",
            "cooldown_seconds": "⏳ Warte {seconds:.1f}s, bevor du diesen Befehl erneut verwendest.",
            "missing_permissions": "⛔ Du hast keine Berechtigung für diesen Befehl.",
            "bot_missing_permissions": "⛔ Mir fehlen diese Berechtigungen: `{missing}`.",
            "usage": "ℹ️ Verwendung: `{prefix}{command} {signature}`",
            "nsfw_only": "🔞 Dieser Befehl ist nur in NSFW-Kanälen erlaubt.",
            "command_failed": "❌ Dieser Befehl ist fehlgeschlagen. Bitte versuche es erneut."
        },
        "economy": {
            "balance_title": "Guthaben von {member}",
            "balance_description": "Wirtschaft von **{guild}** (wird nicht mit anderen Servern geteilt).",
            "wallet": "Brieftasche",
            "bank": "Bank",
            "total": "Gesamt",
            "deposit": "{symbol} {amount} auf die Bank dieses Servers eingezahlt.",
            "withdraw": "{symbol} {amount} von der Bank dieses Servers abgehoben.",
            "work": "Du hast als **{job}** in **{guild}** gearbeitet und **{symbol} {amount}** verdient.",
            "daily": "Tägliche Belohnung für **{guild}**: **{symbol} {amount}**.",
            "crime_success": "Das Verbrechen ist gelungen: **{symbol} {amount}**.",
            "crime_caught": "Du wurdest erwischt. Strafe: **{symbol} {amount}**.",
            "coin_win": "Es landete auf **{outcome}**. Du hast **{symbol} {amount}** gewonnen.",
            "coin_loss": "Es landete auf **{outcome}**. Du hast **{symbol} {amount}** verloren.",
            "dice_user": "Du hast gewürfelt: **{roll}**\nDer Bot: **{bot_roll}**\n",
            "dice_draw": "Unentschieden, das Geld kommt zurück.",
            "dice_win": "Du hast **{symbol} {amount}** gewonnen.",
            "dice_loss": "Du hast **{symbol} {amount}** verloren.",
            "shop_title": "Shop von {guild}",
            "shop_empty": "Der Shop dieses Servers ist leer. Ein Admin kann `/ecoadmin additem` verwenden.",
            "need_for_purchase": "Du brauchst **{symbol} {cost}**, um {quantity}x {item} zu kaufen.",
            "purchase": "Du hast {quantity}x **{item}** für **{symbol} {cost}** gekauft.",
            "give_money": "💸 {author} gab **{symbol} {amount}** an {member} auf diesem Server.",
            "give_item": "📦 {author} gab 1 **{item}** an {member}.",
            "inventory_title": "Inventar - {member}",
            "top_title": "💰 Wirtschaft · {guild}",
            "top_empty": "Hier hat noch niemand Geld verdient.",
            "item_added": "Gegenstand **{item}** zum Shop dieses Servers hinzugefügt · {symbol} {price}.",
            "item_removed": "Gegenstand **{item}** aus dem Shop dieses Servers entfernt.",
            "money_added": "**{symbol} {amount}** zu {member} in **{guild}** hinzugefügt.",
            "money_removed": "**{symbol} {amount}** von {member} auf diesem Server entfernt.",
            "money_set": "{member} hat jetzt **{symbol} {amount}** in {type} auf diesem Server."
        },
        "leveling": {
            "rank_card_title": "Levelkarte - {member}",
            "server_level": "Server-Level",
            "server_xp": "Server-XP",
            "global_level": "Globales Level",
            "leaderboard_title": "🌍 Server-Rangliste",
            "leaderboard_empty": "Noch niemand hat XP gesammelt!",
            "level_min": "Das Level muss mindestens 1 sein.",
            "level_set": "Das Level von {member} ist jetzt **{level}** (XP auf 0 zurückgesetzt).",
            "xp_set": "XP von {member} ist jetzt **{amount}**. Level **{level}** mit **{xp}** XP.",
            "channel_set": "✅ Level-up-Ankündigungen → {channel}",
            "channel_default": "✅ Level-up-Ankündigungen → derselbe Kanal wie die Nachricht.",
            "role_level_min": "❌ Das Level muss 1 oder höher sein.",
            "role_updated": "✅ Belohnung für Level **{level}** auf {role} aktualisiert.",
            "role_set": "✅ {role} ist die Belohnung für Level **{level}**.",
            "roles_empty": "❌ Keine Level-Rollen. Verwende `/level addrole`.",
            "role_missing": "❌ Keine Rollenbelohnung für Level **{level}**.",
            "role_removed": "✅ Rollenbelohnung für Level **{level}** entfernt.",
            "background_updated": "✅ Hintergrund aktualisiert",
            "bot_name_set": "✅ Bot-Name gesetzt: **{name}**",
            "avatar_updated": "✅ Bot-Avatar aktualisiert",
            "leveling_enabled": "✅ Level-System **{status}**.",
            "custom_text_default": "Level {level} · {xp} XP",
            "status_on": "aktiviert",
            "status_off": "deaktiviert"
        }
    },
    "fr": {
        "common": {
            "valid_amount": "Saisis un montant valide.",
            "positive_amount": "Le montant doit être positif.",
            "nonnegative_amount": "Le montant ne peut pas être négatif.",
            "insufficient_wallet": "Tu n'as pas assez d'argent dans ton portefeuille.",
            "insufficient_bank": "Tu n'as pas assez d'argent en banque.",
            "insufficient_money": "Tu n'as pas assez d'argent.",
            "no_guild_economy": "L'économie est propre à chaque serveur. Utilise cette commande dans un serveur.",
            "invalid_coin": "Indique heads/cara ou tails/cruz.",
            "self_money": "Tu ne peux pas te donner de l'argent.",
            "self_item": "Tu ne peux pas te donner d'objet.",
            "invalid_type": "Le type doit être 'wallet' ou 'bank'.",
            "empty_inventory": "{member} a un inventaire vide.",
            "not_in_shop": "Cet objet n'est pas dans la boutique de ce serveur.",
            "cooldown_hours": "Tu pourras réutiliser cette commande dans {hours} heures.",
            "cooldown_minutes": "Tu pourras réutiliser cette commande dans {minutes} minutes.",
            "command_help": "Utilise `/eco balance`, `/eco work`, `/eco shop`, etc.",
            "admin_command_help": "Utilise `/ecoadmin additem`, `/ecoadmin setmoney`, etc.",
            "cooldown_seconds": "⏳ Attends {seconds:.1f}s avant de réutiliser cette commande.",
            "missing_permissions": "⛔ Tu n'as pas la permission d'utiliser cette commande.",
            "bot_missing_permissions": "⛔ Il me manque ces permissions : `{missing}`.",
            "usage": "ℹ️ Usage : `{prefix}{command} {signature}`",
            "nsfw_only": "🔞 Cette commande ne peut être utilisée que dans les salons NSFW.",
            "command_failed": "❌ Cette commande a échoué. Réessaie."
        },
        "economy": {
            "balance_title": "Solde de {member}",
            "balance_description": "Économie de **{guild}** (non partagée avec les autres serveurs).",
            "wallet": "Portefeuille",
            "bank": "Banque",
            "total": "Total",
            "deposit": "Dépôt de {symbol} {amount} à la banque de ce serveur.",
            "withdraw": "Retrait de {symbol} {amount} de la banque de ce serveur.",
            "work": "Tu as travaillé comme **{job}** dans **{guild}** et gagné **{symbol} {amount}**.",
            "daily": "Récompense quotidienne de **{guild}** : **{symbol} {amount}**.",
            "crime_success": "Le crime a réussi : **{symbol} {amount}**.",
            "crime_caught": "Tu t'es fait prendre. Amende : **{symbol} {amount}**.",
            "coin_win": "C'est tombé sur **{outcome}**. Tu as gagné **{symbol} {amount}**.",
            "coin_loss": "C'est tombé sur **{outcome}**. Tu as perdu **{symbol} {amount}**.",
            "dice_user": "Tu as lancé : **{roll}**\nLe bot : **{bot_roll}**\n",
            "dice_draw": "Égalité, l'argent est rendu.",
            "dice_win": "Tu as gagné **{symbol} {amount}**.",
            "dice_loss": "Tu as perdu **{symbol} {amount}**.",
            "shop_title": "Boutique de {guild}",
            "shop_empty": "La boutique de ce serveur est vide. Un admin peut utiliser `/ecoadmin additem`.",
            "need_for_purchase": "Il te faut **{symbol} {cost}** pour acheter {quantity}x {item}.",
            "purchase": "Tu as acheté {quantity}x **{item}** pour **{symbol} {cost}**.",
            "give_money": "💸 {author} a donné **{symbol} {amount}** à {member} sur ce serveur.",
            "give_item": "📦 {author} a donné 1 **{item}** à {member}.",
            "inventory_title": "Inventaire - {member}",
            "top_title": "💰 Économie · {guild}",
            "top_empty": "Personne n'a encore gagné d'argent ici.",
            "item_added": "Objet **{item}** ajouté à la boutique de ce serveur · {symbol} {price}.",
            "item_removed": "Objet **{item}** retiré de la boutique de ce serveur.",
            "money_added": "**{symbol} {amount}** ajouté à {member} dans **{guild}**.",
            "money_removed": "**{symbol} {amount}** retiré à {member} sur ce serveur.",
            "money_set": "{member} a maintenant **{symbol} {amount}** en {type} sur ce serveur."
        },
        "leveling": {
            "rank_card_title": "Carte de niveau - {member}",
            "server_level": "Niveau du serveur",
            "server_xp": "XP du serveur",
            "global_level": "Niveau global",
            "leaderboard_title": "🌍 Classement du serveur",
            "leaderboard_empty": "Personne n'a encore gagné d'XP !",
            "level_min": "Le niveau doit être au moins 1.",
            "level_set": "Le niveau de {member} est maintenant **{level}** (XP remise à 0).",
            "xp_set": "L'XP de {member} est maintenant **{amount}**. Niveau **{level}** avec **{xp}** XP.",
            "channel_set": "✅ Annonces de montée de niveau → {channel}",
            "channel_default": "✅ Annonces de montée de niveau → même salon que le message.",
            "role_level_min": "❌ Le niveau doit être 1 ou plus.",
            "role_updated": "✅ Récompense du niveau **{level}** mise à jour : {role}.",
            "role_set": "✅ {role} est la récompense du niveau **{level}**.",
            "roles_empty": "❌ Aucun rôle de niveau. Utilise `/level addrole`.",
            "role_missing": "❌ Pas de récompense pour le niveau **{level}**.",
            "role_removed": "✅ Récompense du niveau **{level}** retirée.",
            "background_updated": "✅ Fond mis à jour",
            "bot_name_set": "✅ Nom du bot défini : **{name}**",
            "avatar_updated": "✅ Avatar du bot mis à jour",
            "leveling_enabled": "✅ Système de niveaux **{status}**.",
            "custom_text_default": "Niveau {level} · {xp} XP",
            "status_on": "activé",
            "status_off": "désactivé"
        }
    },
    "it": {
        "common": {
            "valid_amount": "Inserisci un importo valido.",
            "positive_amount": "L'importo deve essere positivo.",
            "nonnegative_amount": "L'importo non può essere negativo.",
            "insufficient_wallet": "Non hai abbastanza denaro nel portafoglio.",
            "insufficient_bank": "Non hai abbastanza denaro in banca.",
            "insufficient_money": "Non hai abbastanza denaro.",
            "no_guild_economy": "L'economia è separata per server. Usa questo comando in un server.",
            "invalid_coin": "Specifica heads/cara o tails/cruz.",
            "self_money": "Non puoi dare denaro a te stesso.",
            "self_item": "Non puoi dare oggetti a te stesso.",
            "invalid_type": "Il tipo deve essere 'wallet' o 'bank'.",
            "empty_inventory": "{member} ha l'inventario vuoto.",
            "not_in_shop": "Questo oggetto non è nel negozio del server.",
            "cooldown_hours": "Potrai usare di nuovo questo comando tra {hours} ore.",
            "cooldown_minutes": "Potrai usare di nuovo questo comando tra {minutes} minuti.",
            "command_help": "Usa `/eco balance`, `/eco work`, `/eco shop`, ecc.",
            "admin_command_help": "Usa `/ecoadmin additem`, `/ecoadmin setmoney`, ecc.",
            "cooldown_seconds": "⏳ Attendi {seconds:.1f}s prima di riusare questo comando.",
            "missing_permissions": "⛔ Non hai il permesso di usare questo comando.",
            "bot_missing_permissions": "⛔ Mi mancano questi permessi: `{missing}`.",
            "usage": "ℹ️ Uso: `{prefix}{command} {signature}`",
            "nsfw_only": "🔞 Questo comando si usa solo nei canali NSFW.",
            "command_failed": "❌ Questo comando non è riuscito. Riprova."
        },
        "economy": {
            "balance_title": "Saldo di {member}",
            "balance_description": "Economia di **{guild}** (non condivisa con altri server).",
            "wallet": "Portafoglio",
            "bank": "Banca",
            "total": "Totale",
            "deposit": "Depositati {symbol} {amount} nella banca di questo server.",
            "withdraw": "Prelevati {symbol} {amount} dalla banca di questo server.",
            "work": "Hai lavorato come **{job}** in **{guild}** e hai guadagnato **{symbol} {amount}**.",
            "daily": "Ricompensa giornaliera di **{guild}**: **{symbol} {amount}**.",
            "crime_success": "Il crimine è riuscito: **{symbol} {amount}**.",
            "crime_caught": "Ti hanno beccato. Multa: **{symbol} {amount}**.",
            "coin_win": "È uscito **{outcome}**. Hai vinto **{symbol} {amount}**.",
            "coin_loss": "È uscito **{outcome}**. Hai perso **{symbol} {amount}**.",
            "dice_user": "Hai tirato: **{roll}**\nIl bot: **{bot_roll}**\n",
            "dice_draw": "Pareggio, i soldi tornano.",
            "dice_win": "Hai vinto **{symbol} {amount}**.",
            "dice_loss": "Hai perso **{symbol} {amount}**.",
            "shop_title": "Negozio di {guild}",
            "shop_empty": "Il negozio di questo server è vuoto. Un admin può usare `/ecoadmin additem`.",
            "need_for_purchase": "Ti servono **{symbol} {cost}** per comprare {quantity}x {item}.",
            "purchase": "Hai comprato {quantity}x **{item}** per **{symbol} {cost}**.",
            "give_money": "💸 {author} ha dato **{symbol} {amount}** a {member} in questo server.",
            "give_item": "📦 {author} ha dato 1 **{item}** a {member}.",
            "inventory_title": "Inventario - {member}",
            "top_title": "💰 Economia · {guild}",
            "top_empty": "Qui nessuno ha ancora guadagnato denaro.",
            "item_added": "Oggetto **{item}** aggiunto al negozio di questo server · {symbol} {price}.",
            "item_removed": "Oggetto **{item}** rimosso dal negozio di questo server.",
            "money_added": "Aggiunti **{symbol} {amount}** a {member} in **{guild}**.",
            "money_removed": "Rimossi **{symbol} {amount}** da {member} in questo server.",
            "money_set": "{member} ora ha **{symbol} {amount}** in {type} in questo server."
        },
        "leveling": {
            "rank_card_title": "Card livello - {member}",
            "server_level": "Livello del server",
            "server_xp": "XP del server",
            "global_level": "Livello globale",
            "leaderboard_title": "🌍 Classifica del server",
            "leaderboard_empty": "Nessuno ha ancora ottenuto XP!",
            "level_min": "Il livello deve essere almeno 1.",
            "level_set": "Il livello di {member} è ora **{level}** (XP azzerata).",
            "xp_set": "L'XP di {member} è ora **{amount}**. Livello **{level}** con **{xp}** XP.",
            "channel_set": "✅ Annunci di livello → {channel}",
            "channel_default": "✅ Annunci di livello → stesso canale del messaggio.",
            "role_level_min": "❌ Il livello deve essere 1 o superiore.",
            "role_updated": "✅ Ricompensa del livello **{level}** aggiornata a {role}.",
            "role_set": "✅ {role} è la ricompensa del livello **{level}**.",
            "roles_empty": "❌ Nessun ruolo di livello. Usa `/level addrole`.",
            "role_missing": "❌ Nessuna ricompensa per il livello **{level}**.",
            "role_removed": "✅ Ricompensa del livello **{level}** rimossa.",
            "background_updated": "✅ Sfondo aggiornato",
            "bot_name_set": "✅ Nome del bot impostato: **{name}**",
            "avatar_updated": "✅ Avatar del bot aggiornato",
            "leveling_enabled": "✅ Sistema di livelli **{status}**.",
            "custom_text_default": "Livello {level} · {xp} XP",
            "status_on": "attivato",
            "status_off": "disattivato"
        }
    },
    "pt": {
        "common": {
            "valid_amount": "Introduz um valor válido.",
            "positive_amount": "O valor deve ser positivo.",
            "nonnegative_amount": "O valor não pode ser negativo.",
            "insufficient_wallet": "Não tens dinheiro suficiente na carteira.",
            "insufficient_bank": "Não tens dinheiro suficiente no banco.",
            "insufficient_money": "Não tens dinheiro suficiente.",
            "no_guild_economy": "A economia é por servidor. Usa este comando num servidor.",
            "invalid_coin": "Indica heads/cara ou tails/cruz.",
            "self_money": "Não podes dar dinheiro a ti próprio.",
            "self_item": "Não podes dar itens a ti próprio.",
            "invalid_type": "O tipo deve ser 'wallet' ou 'bank'.",
            "empty_inventory": "{member} tem o inventário vazio.",
            "not_in_shop": "Esse item não está na loja deste servidor.",
            "cooldown_hours": "Podes usar este comando novamente em {hours} horas.",
            "cooldown_minutes": "Podes usar este comando novamente em {minutes} minutos.",
            "command_help": "Usa `/eco balance`, `/eco work`, `/eco shop`, etc.",
            "admin_command_help": "Usa `/ecoadmin additem`, `/ecoadmin setmoney`, etc.",
            "cooldown_seconds": "⏳ Espera {seconds:.1f}s antes de voltar a usar este comando.",
            "missing_permissions": "⛔ Não tens permissão para usar este comando.",
            "bot_missing_permissions": "⛔ Faltam-me estas permissões: `{missing}`.",
            "usage": "ℹ️ Uso: `{prefix}{command} {signature}`",
            "nsfw_only": "🔞 Este comando só se usa em canais NSFW.",
            "command_failed": "❌ Esse comando falhou. Tenta novamente."
        },
        "economy": {
            "balance_title": "Saldo de {member}",
            "balance_description": "Economia de **{guild}** (não é partilhada com outros servidores).",
            "wallet": "Carteira",
            "bank": "Banco",
            "total": "Total",
            "deposit": "Depositaste {symbol} {amount} no banco deste servidor.",
            "withdraw": "Levantaste {symbol} {amount} do banco deste servidor.",
            "work": "Trabalhaste de **{job}** em **{guild}** e ganhaste **{symbol} {amount}**.",
            "daily": "Recompensa diária de **{guild}**: **{symbol} {amount}**.",
            "crime_success": "O crime correu bem: **{symbol} {amount}**.",
            "crime_caught": "Apanharam-te. Multa: **{symbol} {amount}**.",
            "coin_win": "Saiu **{outcome}**. Ganhaste **{symbol} {amount}**.",
            "coin_loss": "Saiu **{outcome}**. Perdeste **{symbol} {amount}**.",
            "dice_user": "Tu: **{roll}**\nO bot: **{bot_roll}**\n",
            "dice_draw": "Empate, o dinheiro volta.",
            "dice_win": "Ganhaste **{symbol} {amount}**.",
            "dice_loss": "Perdeste **{symbol} {amount}**.",
            "shop_title": "Loja de {guild}",
            "shop_empty": "A loja deste servidor está vazia. Um admin pode usar `/ecoadmin additem`.",
            "need_for_purchase": "Precisas de **{symbol} {cost}** para comprar {quantity}x {item}.",
            "purchase": "Compraste {quantity}x **{item}** por **{symbol} {cost}**.",
            "give_money": "💸 {author} deu **{symbol} {amount}** a {member} neste servidor.",
            "give_item": "📦 {author} deu 1 **{item}** a {member}.",
            "inventory_title": "Inventário - {member}",
            "top_title": "💰 Economia · {guild}",
            "top_empty": "Ainda ninguém ganhou dinheiro aqui.",
            "item_added": "Item **{item}** adicionado à loja deste servidor · {symbol} {price}.",
            "item_removed": "Item **{item}** removido da loja deste servidor.",
            "money_added": "Adicionado **{symbol} {amount}** a {member} em **{guild}**.",
            "money_removed": "Removido **{symbol} {amount}** a {member} neste servidor.",
            "money_set": "{member} agora tem **{symbol} {amount}** em {type} neste servidor."
        },
        "leveling": {
            "rank_card_title": "Cartão de nível - {member}",
            "server_level": "Nível do servidor",
            "server_xp": "XP do servidor",
            "global_level": "Nível global",
            "leaderboard_title": "🌍 Classificação do servidor",
            "leaderboard_empty": "Ainda ninguém ganhou XP!",
            "level_min": "O nível deve ser pelo menos 1.",
            "level_set": "O nível de {member} agora é **{level}** (XP a 0).",
            "xp_set": "O XP de {member} agora é **{amount}**. Nível **{level}** com **{xp}** XP.",
            "channel_set": "✅ Anúncios de subida de nível → {channel}",
            "channel_default": "✅ Anúncios de subida de nível → o mesmo canal da mensagem.",
            "role_level_min": "❌ O nível deve ser 1 ou superior.",
            "role_updated": "✅ Recompensa do nível **{level}** atualizada para {role}.",
            "role_set": "✅ {role} é a recompensa do nível **{level}**.",
            "roles_empty": "❌ Sem cargos de nível. Usa `/level addrole`.",
            "role_missing": "❌ Sem recompensa para o nível **{level}**.",
            "role_removed": "✅ Recompensa do nível **{level}** removida.",
            "background_updated": "✅ Fundo atualizado",
            "bot_name_set": "✅ Nome do bot definido: **{name}**",
            "avatar_updated": "✅ Avatar do bot atualizado",
            "leveling_enabled": "✅ Sistema de níveis **{status}**.",
            "custom_text_default": "Nível {level} · {xp} XP",
            "status_on": "ativado",
            "status_off": "desativado"
        }
    },
    "ja": {
        "common": {
            "valid_amount": "有効な金額を入力してください。",
            "positive_amount": "金額は正数である必要があります。",
            "nonnegative_amount": "金額を負にすることはできません。",
            "insufficient_wallet": "財布のお金が足りません。",
            "insufficient_bank": "銀行のお金が足りません。",
            "insufficient_money": "お金が足りません。",
            "no_guild_economy": "経済はサーバーごとに分かれています。サーバー内で使用してください。",
            "invalid_coin": "heads/cara または tails/cruz を指定してください。",
            "self_money": "自分自身にお金を渡すことはできません。",
            "self_item": "自分自身にアイテムを渡すことはできません。",
            "invalid_type": "タイプは 'wallet' または 'bank' です。",
            "empty_inventory": "{member} のインベントリは空です。",
            "not_in_shop": "そのアイテムはこのサーバーのショップにありません。",
            "cooldown_hours": "あと {hours} 時間で再使用できます。",
            "cooldown_minutes": "あと {minutes} 分で再使用できます。",
            "command_help": "`/eco balance`、`/eco work`、`/eco shop` などを使用してください。",
            "admin_command_help": "`/ecoadmin additem`、`/ecoadmin setmoney` などを使用してください。",
            "cooldown_seconds": "⏳ {seconds:.1f}秒待ってから再使用してください。",
            "missing_permissions": "⛔ このコマンドを使う権限がありません。",
            "bot_missing_permissions": "⛔ これらの権限が不足しています: `{missing}`。",
            "usage": "ℹ️ 使い方: `{prefix}{command} {signature}`",
            "nsfw_only": "🔞 このコマンドは NSFW チャンネルでのみ使用できます。",
            "command_failed": "❌ コマンドに失敗しました。もう一度お試しください。"
        },
        "economy": {
            "balance_title": "{member} の残高",
            "balance_description": "**{guild}** の経済（他サーバーとは共有されません）。",
            "wallet": "財布",
            "bank": "銀行",
            "total": "合計",
            "deposit": "このサーバーの銀行に {symbol} {amount} を預けました。",
            "withdraw": "このサーバーの銀行から {symbol} {amount} を引き出しました。",
            "work": "**{guild}** で **{job}** として働き、**{symbol} {amount}** を得ました。",
            "daily": "**{guild}** のデイリー報酬: **{symbol} {amount}**。",
            "crime_success": "犯罪は成功: **{symbol} {amount}**。",
            "crime_caught": "捕まりました。罰金: **{symbol} {amount}**。",
            "coin_win": "**{outcome}** が出ました。**{symbol} {amount}** 勝ち。",
            "coin_loss": "**{outcome}** が出ました。**{symbol} {amount}** 負け。",
            "dice_user": "あなた: **{roll}**\nボット: **{bot_roll}**\n",
            "dice_draw": "引き分け。お金は戻ります。",
            "dice_win": "**{symbol} {amount}** 勝ち。",
            "dice_loss": "**{symbol} {amount}** 負け。",
            "shop_title": "{guild} のショップ",
            "shop_empty": "このサーバーのショップは空です。管理者は `/ecoadmin additem` を使えます。",
            "need_for_purchase": "{quantity}x {item} を買うには **{symbol} {cost}** が必要です。",
            "purchase": "{quantity}x **{item}** を **{symbol} {cost}** で買いました。",
            "give_money": "💸 {author} がこのサーバーで {member} に **{symbol} {amount}** を渡しました。",
            "give_item": "📦 {author} が {member} に **{item}** を 1 個渡しました。",
            "inventory_title": "インベントリ - {member}",
            "top_title": "💰 経済 · {guild}",
            "top_empty": "まだ誰もここでお金を稼いでいません。",
            "item_added": "アイテム **{item}** をこのサーバーのショップに追加 · {symbol} {price}。",
            "item_removed": "アイテム **{item}** をこのサーバーのショップから削除。",
            "money_added": "**{guild}** の {member} に **{symbol} {amount}** を追加。",
            "money_removed": "このサーバーの {member} から **{symbol} {amount}** を削除。",
            "money_set": "{member} のこのサーバーの {type} は **{symbol} {amount}** です。"
        },
        "leveling": {
            "rank_card_title": "レベルカード - {member}",
            "server_level": "サーバーレベル",
            "server_xp": "サーバーXP",
            "global_level": "グローバルレベル",
            "leaderboard_title": "🌍 サーバーランキング",
            "leaderboard_empty": "まだ誰もXPを得ていません！",
            "level_min": "レベルは 1 以上である必要があります。",
            "level_set": "{member} のレベルを **{level}** に設定（XPは 0）。",
            "xp_set": "{member} のXPを **{amount}** に設定。レベル **{level}**、**{xp}** XP。",
            "channel_set": "✅ レベルアップ告知 → {channel}",
            "channel_default": "✅ レベルアップ告知 → メッセージと同じチャンネル。",
            "role_level_min": "❌ レベルは 1 以上である必要があります。",
            "role_updated": "✅ レベル **{level}** の報酬を {role} に更新。",
            "role_set": "✅ {role} をレベル **{level}** の報酬に設定。",
            "roles_empty": "❌ レベルロールがありません。`/level addrole` を使ってください。",
            "role_missing": "❌ レベル **{level}** の報酬がありません。",
            "role_removed": "✅ レベル **{level}** の報酬を削除。",
            "background_updated": "✅ 背景を更新",
            "bot_name_set": "✅ ボット名: **{name}**",
            "avatar_updated": "✅ ボットのアバターを更新",
            "leveling_enabled": "✅ レベルシステム **{status}**。",
            "custom_text_default": "レベル {level} · {xp} XP",
            "status_on": "有効",
            "status_off": "無効"
        }
    },
    "ko": {
        "common": {
            "valid_amount": "유효한 금액을 입력하세요.",
            "positive_amount": "금액은 양수여야 합니다.",
            "nonnegative_amount": "금액은 음수일 수 없습니다.",
            "insufficient_wallet": "지갑의 잔액이 부족합니다.",
            "insufficient_bank": "은행 잔액이 부족합니다.",
            "insufficient_money": "잔액이 부족합니다.",
            "no_guild_economy": "경제는 서버별로 적용됩니다. 서버에서 사용하세요.",
            "invalid_coin": "heads/cara 또는 tails/cruz를 입력하세요.",
            "self_money": "자신에게 돈을 보낼 수 없습니다.",
            "self_item": "자신에게 아이템을 보낼 수 없습니다.",
            "invalid_type": "유형은 'wallet' 또는 'bank'여야 합니다.",
            "empty_inventory": "{member}의 인벤토리가 비어 있습니다.",
            "not_in_shop": "이 아이템은 이 서버 상점에 없습니다.",
            "cooldown_hours": "{hours}시간 후에 다시 사용할 수 있습니다.",
            "cooldown_minutes": "{minutes}분 후에 다시 사용할 수 있습니다.",
            "command_help": "`/eco balance`, `/eco work`, `/eco shop` 등을 사용하세요.",
            "admin_command_help": "`/ecoadmin additem`, `/ecoadmin setmoney` 등을 사용하세요.",
            "cooldown_seconds": "⏳ {seconds:.1f}초 후에 다시 사용하세요.",
            "missing_permissions": "⛔ 이 명령을 사용할 권한이 없습니다.",
            "bot_missing_permissions": "⛔ 다음 권한이 부족합니다: `{missing}`.",
            "usage": "ℹ️ 사용법: `{prefix}{command} {signature}`",
            "nsfw_only": "🔞 이 명령은 NSFW 채널에서만 사용할 수 있습니다.",
            "command_failed": "❌ 명령이 실패했습니다. 다시 시도하세요."
        },
        "economy": {
            "balance_title": "{member}의 잔액",
            "balance_description": "**{guild}** 경제 (다른 서버와 공유되지 않음).",
            "wallet": "지갑",
            "bank": "은행",
            "total": "합계",
            "deposit": "이 서버 은행에 {symbol} {amount}을(를) 입금했습니다.",
            "withdraw": "이 서버 은행에서 {symbol} {amount}을(를) 출금했습니다.",
            "work": "**{guild}**에서 **{job}**(으)로 일해 **{symbol} {amount}**을(를) 벌었습니다.",
            "daily": "**{guild}** 일일 보상: **{symbol} {amount}**.",
            "crime_success": "범죄 성공: **{symbol} {amount}**.",
            "crime_caught": "잡혔습니다. 벌금: **{symbol} {amount}**.",
            "coin_win": "**{outcome}**이(가) 나왔습니다. **{symbol} {amount}** 승리.",
            "coin_loss": "**{outcome}**이(가) 나왔습니다. **{symbol} {amount}** 패배.",
            "dice_user": "당신: **{roll}**\n봇: **{bot_roll}**\n",
            "dice_draw": "무승부, 돈이 반환됩니다.",
            "dice_win": "**{symbol} {amount}** 승리.",
            "dice_loss": "**{symbol} {amount}** 패배.",
            "shop_title": "{guild} 상점",
            "shop_empty": "이 서버 상점이 비어 있습니다. 관리자는 `/ecoadmin additem`을 사용할 수 있습니다.",
            "need_for_purchase": "{quantity}x {item}을(를) 사려면 **{symbol} {cost}**이(가) 필요합니다.",
            "purchase": "{quantity}x **{item}**을(를) **{symbol} {cost}**에 샀습니다.",
            "give_money": "💸 {author}이(가) 이 서버에서 {member}에게 **{symbol} {amount}**을(를) 줬습니다.",
            "give_item": "📦 {author}이(가) {member}에게 **{item}** 1개를 줬습니다.",
            "inventory_title": "인벤토리 - {member}",
            "top_title": "💰 경제 · {guild}",
            "top_empty": "아직 여기서 돈을 번 사람이 없습니다.",
            "item_added": "아이템 **{item}**을(를) 이 서버 상점에 추가 · {symbol} {price}.",
            "item_removed": "아이템 **{item}**을(를) 이 서버 상점에서 제거.",
            "money_added": "**{guild}**의 {member}에게 **{symbol} {amount}** 추가.",
            "money_removed": "이 서버의 {member}에게서 **{symbol} {amount}** 제거.",
            "money_set": "{member}의 이 서버 {type}는 이제 **{symbol} {amount}**입니다."
        },
        "leveling": {
            "rank_card_title": "레벨 카드 - {member}",
            "server_level": "서버 레벨",
            "server_xp": "서버 XP",
            "global_level": "글로벌 레벨",
            "leaderboard_title": "🌍 서버 랭킹",
            "leaderboard_empty": "아직 XP를 얻은 사람이 없습니다!",
            "level_min": "레벨은 최소 1이어야 합니다.",
            "level_set": "{member}의 레벨이 **{level}**(으)로 설정됨 (XP 0).",
            "xp_set": "{member}의 XP가 **{amount}**. 레벨 **{level}**, **{xp}** XP.",
            "channel_set": "✅ 레벨업 알림 → {channel}",
            "channel_default": "✅ 레벨업 알림 → 메시지와 같은 채널.",
            "role_level_min": "❌ 레벨은 1 이상이어야 합니다.",
            "role_updated": "✅ 레벨 **{level}** 보상을 {role}(으)로 업데이트.",
            "role_set": "✅ {role}을(를) 레벨 **{level}** 보상으로 설정.",
            "roles_empty": "❌ 레벨 역할이 없습니다. `/level addrole`을 사용하세요.",
            "role_missing": "❌ 레벨 **{level}** 보상이 없습니다.",
            "role_removed": "✅ 레벨 **{level}** 보상을 제거했습니다.",
            "background_updated": "✅ 배경 업데이트",
            "bot_name_set": "✅ 봇 이름: **{name}**",
            "avatar_updated": "✅ 봇 아바타 업데이트",
            "leveling_enabled": "✅ 레벨 시스템 **{status}**.",
            "custom_text_default": "레벨 {level} · {xp} XP",
            "status_on": "켜짐",
            "status_off": "꺼짐"
        }
    },
    "zh": {
        "common": {
            "valid_amount": "请输入有效金额。",
            "positive_amount": "金额必须为正数。",
            "nonnegative_amount": "金额不能为负数。",
            "insufficient_wallet": "钱包余额不足。",
            "insufficient_bank": "银行余额不足。",
            "insufficient_money": "余额不足。",
            "no_guild_economy": "经济系统按服务器独立计算，请在服务器内使用。",
            "invalid_coin": "请输入 heads/cara 或 tails/cruz。",
            "self_money": "不能给自己转账。",
            "self_item": "不能给自己物品。",
            "invalid_type": "类型必须是 'wallet' 或 'bank'。",
            "empty_inventory": "{member} 的背包为空。",
            "not_in_shop": "该物品不在本服务器商店中。",
            "cooldown_hours": "{hours} 小时后可以再次使用。",
            "cooldown_minutes": "{minutes} 分钟后可以再次使用。",
            "command_help": "请使用 `/eco balance`、`/eco work`、`/eco shop` 等命令。",
            "admin_command_help": "请使用 `/ecoadmin additem`、`/ecoadmin setmoney` 等命令。",
            "cooldown_seconds": "⏳ 请等待 {seconds:.1f} 秒后再使用此命令。",
            "missing_permissions": "⛔ 你没有使用此命令的权限。",
            "bot_missing_permissions": "⛔ 我缺少这些权限：`{missing}`。",
            "usage": "ℹ️ 用法：`{prefix}{command} {signature}`",
            "nsfw_only": "🔞 此命令只能在 NSFW 频道使用。",
            "command_failed": "❌ 该命令失败。请重试。"
        },
        "economy": {
            "balance_title": "{member} 的余额",
            "balance_description": "**{guild}** 的经济（不与其他服务器共享）。",
            "wallet": "钱包",
            "bank": "银行",
            "total": "总计",
            "deposit": "已向本服务器银行存入 {symbol} {amount}。",
            "withdraw": "已从本服务器银行取出 {symbol} {amount}。",
            "work": "你在 **{guild}** 担任 **{job}**，获得 **{symbol} {amount}**。",
            "daily": "**{guild}** 的每日奖励：**{symbol} {amount}**。",
            "crime_success": "犯罪成功：**{symbol} {amount}**。",
            "crime_caught": "你被抓住了。罚款：**{symbol} {amount}**。",
            "coin_win": "结果是 **{outcome}**。你赢了 **{symbol} {amount}**。",
            "coin_loss": "结果是 **{outcome}**。你输了 **{symbol} {amount}**。",
            "dice_user": "你掷出：**{roll}**\n机器人：**{bot_roll}**\n",
            "dice_draw": "平局，金钱退回。",
            "dice_win": "你赢了 **{symbol} {amount}**。",
            "dice_loss": "你输了 **{symbol} {amount}**。",
            "shop_title": "{guild} 商店",
            "shop_empty": "本服务器商店为空。管理员可使用 `/ecoadmin additem`。",
            "need_for_purchase": "购买 {quantity}x {item} 需要 **{symbol} {cost}**。",
            "purchase": "你花 **{symbol} {cost}** 买了 {quantity}x **{item}**。",
            "give_money": "💸 {author} 在本服务器给了 {member} **{symbol} {amount}**。",
            "give_item": "📦 {author} 给了 {member} 1 个 **{item}**。",
            "inventory_title": "背包 - {member}",
            "top_title": "💰 经济 · {guild}",
            "top_empty": "这里还没有人赚到钱。",
            "item_added": "已将物品 **{item}** 加入本服务器商店 · {symbol} {price}。",
            "item_removed": "已从本服务器商店移除物品 **{item}**。",
            "money_added": "已向 **{guild}** 的 {member} 添加 **{symbol} {amount}**。",
            "money_removed": "已从本服务器的 {member} 移除 **{symbol} {amount}**。",
            "money_set": "{member} 现在在本服务器的 {type} 中有 **{symbol} {amount}**。"
        },
        "leveling": {
            "rank_card_title": "等级卡 - {member}",
            "server_level": "服务器等级",
            "server_xp": "服务器 XP",
            "global_level": "全局等级",
            "leaderboard_title": "🌍 服务器排行榜",
            "leaderboard_empty": "还没有人获得 XP！",
            "level_min": "等级至少为 1。",
            "level_set": "{member} 的等级现为 **{level}**（XP 已重置为 0）。",
            "xp_set": "{member} 的 XP 现为 **{amount}**。等级 **{level}**，**{xp}** XP。",
            "channel_set": "✅ 升级公告 → {channel}",
            "channel_default": "✅ 升级公告 → 与消息相同的频道。",
            "role_level_min": "❌ 等级必须为 1 或更高。",
            "role_updated": "✅ 已将等级 **{level}** 奖励更新为 {role}。",
            "role_set": "✅ 已将 {role} 设为等级 **{level}** 的奖励。",
            "roles_empty": "❌ 未配置等级身份组。请使用 `/level addrole`。",
            "role_missing": "❌ 等级 **{level}** 没有奖励。",
            "role_removed": "✅ 已移除等级 **{level}** 的奖励。",
            "background_updated": "✅ 背景已更新",
            "bot_name_set": "✅ 机器人名称设为：**{name}**",
            "avatar_updated": "✅ 机器人头像已更新",
            "leveling_enabled": "✅ 等级系统 **{status}**。",
            "custom_text_default": "等级 {level} · {xp} XP",
            "status_on": "已启用",
            "status_off": "已关闭"
        }
    }
}

# Legacy replies are progressively being moved to ``runtime`` keys. Keeping
# this compatibility catalog means older cogs can still follow the guild
# language while they are migrated, instead of producing mixed-language UX.
LEGACY_TRANSLATIONS = {
    "es": {
        "Use `/mod kick`, `/mod ban`, `/mod warn`, etc.": "Usa `/mod kick`, `/mod ban`, `/mod warn`, etc.",
        "Use `/eco balance`, `/eco work`, `/eco shop`, etc.": "Usa `/eco balance`, `/eco work`, `/eco shop`, etc.",
        "You are not in a voice channel.": "No estás en un canal de voz.",
        "This is not a temporary channel.": "Este no es un canal temporal.",
        "You don't own this channel.": "No eres el propietario de este canal.",
        "Please enter a valid amount.": "Introduce una cantidad válida.",
        "Amount must be positive.": "La cantidad debe ser positiva.",
        "You don't have enough money.": "No tienes suficiente dinero.",
        "You don't have enough money in your wallet.": "No tienes suficiente dinero en la cartera.",
        "You don't have enough money in your bank.": "No tienes suficiente dinero en el banco.",
        "You cannot give money to yourself.": "No puedes darte dinero a ti mismo.",
        "You cannot give items to yourself.": "No puedes darte objetos a ti mismo.",
        "No configuration found.": "No se encontró ninguna configuración.",
        "Invalid language code.": "Código de idioma no válido.",
        "You do not have permission to use this command.": "No tienes permisos para usar este comando.",
        "I don't have permission to do that.": "No tengo permisos para hacer eso.",
        "Please upload a valid image file.": "Sube un archivo de imagen válido.",
        "Invalid image.": "Imagen no válida.",
        "Timed out.": "Tiempo de espera agotado.",
        "Operation cancelled.": "Operación cancelada.",
        "No one has gained XP yet!": "¡Todavía nadie ha conseguido XP!",
        "Weekly XP has been reset!": "¡El XP semanal se ha reiniciado!",
        "Price cannot be negative.": "El precio no puede ser negativo.",
        "Type must be 'wallet' or 'bank'.": "El tipo debe ser 'wallet' o 'bank'.",
    },
    "en": {},
    "de": {
        "You are not in a voice channel.": "Du bist in keinem Sprachkanal.",
        "This is not a temporary channel.": "Dies ist kein temporärer Kanal.",
        "Please enter a valid amount.": "Bitte gib einen gültigen Betrag ein.",
        "Amount must be positive.": "Der Betrag muss positiv sein.",
        "You don't have enough money.": "Du hast nicht genug Geld.",
        "You do not have permission to use this command.": "Du hast keine Berechtigung für diesen Befehl.",
        "Please upload a valid image file.": "Bitte lade eine gültige Bilddatei hoch.",
    },
    "fr": {
        "You are not in a voice channel.": "Tu n'es pas dans un canal vocal.",
        "This is not a temporary channel.": "Ce n'est pas un canal temporaire.",
        "Please enter a valid amount.": "Saisis un montant valide.",
        "Amount must be positive.": "Le montant doit être positif.",
        "You don't have enough money.": "Tu n'as pas assez d'argent.",
        "You do not have permission to use this command.": "Tu n'as pas la permission d'utiliser cette commande.",
        "Please upload a valid image file.": "Envoie un fichier image valide.",
    },
    "it": {
        "You are not in a voice channel.": "Non sei in un canale vocale.",
        "This is not a temporary channel.": "Questo non è un canale temporaneo.",
        "Please enter a valid amount.": "Inserisci un importo valido.",
        "Amount must be positive.": "L'importo deve essere positivo.",
        "You don't have enough money.": "Non hai abbastanza denaro.",
        "You do not have permission to use this command.": "Non hai il permesso di usare questo comando.",
        "Please upload a valid image file.": "Carica un file immagine valido.",
    },
    "pt": {
        "You are not in a voice channel.": "Não estás num canal de voz.",
        "This is not a temporary channel.": "Este não é um canal temporário.",
        "Please enter a valid amount.": "Introduz um valor válido.",
        "Amount must be positive.": "O valor deve ser positivo.",
        "You don't have enough money.": "Não tens dinheiro suficiente.",
        "You do not have permission to use this command.": "Não tens permissão para usar este comando.",
        "Please upload a valid image file.": "Envia um ficheiro de imagem válido.",
    },
    "ja": {
        "You are not in a voice channel.": "ボイスチャンネルに参加していません。",
        "This is not a temporary channel.": "これは一時チャンネルではありません。",
        "Please enter a valid amount.": "有効な金額を入力してください。",
        "Amount must be positive.": "金額は正数である必要があります。",
        "You don't have enough money.": "お金が足りません。",
        "You do not have permission to use this command.": "このコマンドを使う権限がありません。",
        "Please upload a valid image file.": "有効な画像ファイルをアップロードしてください。",
    },
    "ko": {
        "You are not in a voice channel.": "음성 채널에 있지 않습니다.",
        "This is not a temporary channel.": "임시 채널이 아닙니다.",
        "Please enter a valid image file.": "유효한 이미지 파일을 업로드하세요.",
        "Amount must be positive.": "금액은 양수여야 합니다.",
        "You don't have enough money.": "잔액이 부족합니다.",
        "You do not have permission to use this command.": "이 명령을 사용할 권한이 없습니다.",
    },
    "zh": {
        "You are not in a voice channel.": "你不在语音频道中。",
        "This is not a temporary channel.": "这不是临时频道。",
        "Please enter a valid amount.": "请输入有效金额。",
        "Amount must be positive.": "金额必须为正数。",
        "You don't have enough money.": "余额不足。",
        "You do not have permission to use this command.": "你没有使用此命令的权限。",
        "Please upload a valid image file.": "请上传有效的图片文件。",
    },
}

LEGACY_TRANSLATIONS["es"].update({
    "You cannot kick this user due to role hierarchy.": "No puedes expulsar a este usuario por la jerarquía de roles.",
    "You cannot ban this user due to role hierarchy.": "No puedes banear a este usuario por la jerarquía de roles.",
    "You cannot timeout this user due to role hierarchy.": "No puedes aislar a este usuario por la jerarquía de roles.",
    "You cannot kick the bot owner.": "No puedes expulsar al propietario del bot.",
    "You cannot ban the bot owner.": "No puedes banear al propietario del bot.",
    "You cannot timeout the bot owner.": "No puedes aislar al propietario del bot.",
    "You cannot warn the bot owner.": "No puedes advertir al propietario del bot.",
    "❌ Case not found.": "❌ Caso no encontrado.", "Limit is 1000.": "El límite es 1000.",
    "Max 6 hours.": "Máximo 6 horas.", "Format: 1d, 12h, 30m": "Formato: 1d, 12h, 30m",
    "❌ Invalid user ID.": "❌ ID de usuario no válido.", "❌ User not found.": "❌ Usuario no encontrado.",
    "❌ I don't have permission to ban this user.": "❌ No tengo permisos para banear a este usuario.",
    "❌ I do not have permission to unban this user.": "❌ No tengo permisos para desbanear a este usuario.",
    "❌ You are not connected to a voice channel.": "❌ No estás conectado a un canal de voz.",
    "You are not connected to a voice channel.": "No estás conectado a un canal de voz.",
    "Not connected to a voice channel.": "No estás conectado a un canal de voz.",
    "❌ Nothing is playing.": "❌ No se está reproduciendo nada.", "Empty queue.": "La cola está vacía.",
    "⏭️ Skipped.": "⏭️ Pista omitida.", "👋 Disconnected and queue cleared.": "👋 Desconectado y cola vaciada.",
    "🔓 Channel unlocked!": "🔓 Canal desbloqueado.", "🔒 Channel locked!": "🔒 Canal bloqueado.",
    "👁️ Channel revealed!": "👁️ Canal visible.", "👻 Channel hidden!": "👻 Canal oculto.",
    "Use `/game trivia`, `/game rps`, `/game count`, etc.": "Usa `/game trivia`, `/game rps`, `/game count`, etc.",
    "❌ A game is already active in this channel!": "❌ Ya hay un juego activo en este canal.",
    "❌ A game is active here.": "❌ Ya hay un juego activo aquí.", "❌ No counting channel set.": "❌ No se ha configurado un canal de conteo.",
    "⬆️ Higher!": "⬆️ Más alto.", "⬇️ Lower!": "⬇️ Más bajo.", "🛑 Counting game stopped.": "🛑 Juego de conteo detenido.",
    "❌ You already have an active game of blackjack! Complete that one first.": "❌ Ya tienes una partida de blackjack activa. Termínala primero.",
    "❌ Minimum bet is 10 coins!": "❌ La apuesta mínima es de 10 monedas.", "❌ Minimum bet is 5 coins!": "❌ La apuesta mínima es de 5 monedas.",
    "❌ Minimum bet is 20 coins!": "❌ La apuesta mínima es de 20 monedas.", "❌ Minimum bet is 15 coins!": "❌ La apuesta mínima es de 15 monedas.",
    "❌ Choose a horse between 1 and 5!": "❌ Elige un caballo entre 1 y 5.",
    "❌ Invalid duration format. Use: 10m, 2h, 1d": "❌ Formato de duración no válido. Usa: 10m, 2h, 1d",
    "❌ Maximum 10 options allowed.": "❌ Se permiten como máximo 10 opciones.",
    "📅 No scheduled messages.": "📅 No hay mensajes programados.", "✅ Giveaway ended!": "✅ ¡Sorteo finalizado!",
    "❌ No active giveaway found with that message ID!": "❌ No hay ningún sorteo activo con ese ID de mensaje.",
    "❌ No giveaway found with that message ID!": "❌ No se encontró ningún sorteo con ese ID de mensaje.",
    "❌ No participants to reroll!": "❌ No hay participantes para volver a sortear.", "📊 No active giveaways!": "📊 No hay sorteos activos.",
    "❌ Invalid message ID!": "❌ ID de mensaje no válido.", "No custom commands found.": "No se encontraron comandos personalizados.",
    "No birthdays set.": "No hay cumpleaños configurados.", "No upcoming birthdays in the next 30 days.": "No hay próximos cumpleaños en los siguientes 30 días.",
    "❌ Invalid date.": "❌ Fecha no válida.", "✅ Birthday removed.": "✅ Cumpleaños eliminado.",
    "❌ Quarantine is not configured.": "❌ La cuarentena no está configurada.", "❌ Quarantine role not found.": "❌ No se encontró el rol de cuarentena.",
    "✅ Quarantine system disabled.": "✅ Sistema de cuarentena deshabilitado.", "❌ Invalid feed URL.": "❌ URL de feed no válida.",
    "❌ No entries.": "❌ No hay entradas.", "❌ Feed already followed.": "❌ Este feed ya está seguido.",
    "⚠️ Are you sure you want to delete **all** your notes?": "⚠️ ¿Seguro que quieres borrar **todas** tus notas?",
    "📝 You have no notes yet. Use `/note add` to create one.": "📝 Todavía no tienes notas. Usa `/note add` para crear una.",
    "❌ You cannot give reputation to yourself!": "❌ ¡No puedes darte reputación a ti mismo!",
    "❌ You cannot give reputation to bots!": "❌ ¡No puedes dar reputación a bots!",
    "📊 No reputation data yet! Use `/rep @user` to give reputation.": "📊 ¡Todavía no hay reputación! Usa `/rep @usuario` para darla.",
    "No active giveaways!": "No hay sorteos activos.", "No birthdays set.": "No hay cumpleaños configurados.",
})

# Build the reverse direction automatically for Spanish-origin replies. This
# is important for servers configured in English when an older cog still emits
# a Spanish literal.
for _source, _translated in LEGACY_TRANSLATIONS["es"].items():
    LEGACY_TRANSLATIONS["en"].setdefault(_translated, _source)

LEGACY_TRANSLATIONS["en"].update({
    "No estás en un canal de voz.": "You are not in a voice channel.",
    "Este no es un canal temporal.": "This is not a temporary channel.",
    "No tienes suficiente dinero.": "You don't have enough money.",
    "La cantidad debe ser positiva.": "Amount must be positive.",
    "Introduce una cantidad válida.": "Please enter a valid amount.",
    "No puedes darte dinero a ti mismo.": "You cannot give money to yourself.",
    "No se encontró ninguna configuración.": "No configuration found.",
    "❌ Usuario no encontrado.": "❌ User not found.",
    "❌ Caso no encontrado.": "❌ Case not found.",
    "❌ Imagen no válida.": "❌ Invalid image.",
    "❌ No tengo permisos para hacer eso.": "❌ I don't have permission to do that.",
    "✅ Canal desbloqueado.": "✅ Channel unlocked!", "🔒 Canal bloqueado.": "🔒 Channel locked!",
    "👁️ Canal visible.": "👁️ Channel revealed!", "👻 Canal oculto.": "👻 Channel hidden!",
})

# Remaining high-frequency legacy replies from older cogs. New code should use
# runtime keys, but this map keeps old commands from switching to English in a
# Spanish server while those handlers are gradually replaced.
LEGACY_TRANSLATIONS["es"].update({
    "Invalid time format. Use: 10s, 5m, 2h, 1d": "Formato de tiempo no válido. Usa: 10s, 5m, 2h, 1d",
    "❌ Invalid hex color. Example: `/color #FF5733`": "❌ Color hexadecimal no válido. Ejemplo: `/color #FF5733`",
    "❌ You need **Manage Messages** permission.": "❌ Necesitas permiso para **Gestionar mensajes**.",
    "❌ Not enough messages to summarize.": "❌ No hay suficientes mensajes para resumir.",
    "❌ AI service unavailable.": "❌ El servicio de IA no está disponible.",
    "❌ AI service unavailable. Make sure the Chatbot cog is loaded.": "❌ El servicio de IA no está disponible. Comprueba que el módulo Chatbot esté cargado.",
    "❌ Not enough messages to analyze.": "❌ No hay suficientes mensajes para analizar.",
    "❌ Failed to generate image. Please try again later.": "❌ No se pudo generar la imagen. Inténtalo más tarde.",
    "📡 No stream alerts configured.": "📡 No hay alertas de streams configuradas.",
    "✅ Giveaway ended!": "✅ ¡Sorteo finalizado!", "✅ You've left the giveaway.": "✅ Has salido del sorteo.",
    "❌ Invalid duration format. Use: 10m, 2h, 1d": "❌ Formato de duración no válido. Usa: 10m, 2h, 1d",
    "❌ No active giveaway found with that message ID!": "❌ No se encontró ningún sorteo activo con ese ID de mensaje.",
    "❌ No giveaway found with that message ID!": "❌ No se encontró ningún sorteo con ese ID de mensaje.",
    "❌ No participants to reroll!": "❌ No hay participantes para volver a sortear.", "📊 No active giveaways!": "📊 No hay sorteos activos.",
    "❌ This giveaway has ended!": "❌ ¡Este sorteo ha terminado!", "❌ You're already entered! Use the **Leave** button to withdraw.": "❌ ¡Ya estás participando! Usa el botón **Salir** para retirarte.",
    "❌ You're not entered in this giveaway!": "❌ ¡No estás participando en este sorteo!", "❌ Invalid message ID!": "❌ ID de mensaje no válido.",
    "📅 No scheduled messages.": "📅 No hay mensajes programados.", "❌ Maximum 10 options allowed.": "❌ Se permiten como máximo 10 opciones.",
    "❌ A game is already active in this channel!": "❌ Ya hay un juego activo en este canal.", "❌ A game is active here.": "❌ Ya hay un juego activo aquí.",
    "🔢 I've picked a number between **1** and **100**. Start guessing!": "🔢 He elegido un número entre **1** y **100**. ¡Empieza a adivinar!",
    "🔢 Counting channel set! Start with **1**.": "🔢 ¡Canal de conteo configurado! Empieza por **1**.", "🛑 Counting game stopped.": "🛑 Juego de conteo detenido.",
    "Not your game!": "¡Este juego no es tuyo!", "✅ Correct!": "✅ ¡Correcto!", "❌ Error fetching question.": "❌ Error al obtener la pregunta.",
    "Only in a server.": "Solo se puede usar en un servidor.", "Only in a server.": "Solo se puede usar en un servidor.", "Sin permiso.": "Sin permiso.",
    "❌ Must be exactly 5 letters.": "❌ Deben ser exactamente 5 letras.", "❌ This is not your game!": "❌ Este juego no es tuyo.",
    "❌ Enter a single letter.": "❌ Introduce una sola letra.", "⏳ Wait for your turn!": "⏳ ¡Espera tu turno!",
    "❌ You need to challenge a real human!": "❌ ¡Tienes que desafiar a una persona real!", "❌ Only the challenged player can accept.": "❌ Solo el jugador desafiado puede aceptar.", "❌ Only the challenged player can decline.": "❌ Solo el jugador desafiado puede rechazar.",
    "❌ You are not connected to a voice channel.": "❌ No estás conectado a un canal de voz.", "⏭️ Skipped.": "⏭️ Pista omitida.", "❌ Nothing is playing.": "❌ No se está reproduciendo nada.", "Empty queue.": "La cola está vacía.", "👋 Disconnected and queue cleared.": "👋 Desconectado y cola vaciada.",
    "⚠️ Are you sure you want to delete **all** your notes?": "⚠️ ¿Seguro que quieres borrar **todas** tus notas?", "📝 You have no notes yet. Use `/note add` to create one.": "📝 Todavía no tienes notas. Usa `/note add` para crear una.",
    "❌ Failed to save configuration.": "❌ No se pudo guardar la configuración.", "✅ Anti-raid disabled.": "✅ Anti-raid desactivado.", "🔒 Server lockdown activated.": "🔒 Bloqueo del servidor activado.", "🔓 Server lockdown deactivated.": "🔓 Bloqueo del servidor desactivado.",
    "🔄 Restarting system...": "🔄 Reiniciando el sistema…", "⛔ Only the owner can restart the bot.": "⛔ Solo el propietario puede reiniciar el bot.", "No users are currently blacklisted.": "No hay usuarios en la lista negra.",
    "❌ Invalid User ID.": "❌ ID de usuario no válido.", "❌ User not found via Discord API.": "❌ No se encontró al usuario mediante la API de Discord.", "✅ **System Repair Successful!** Bot has restarted and is stable.": "✅ **¡Reparación del sistema completada!** El bot se ha reiniciado y está estable.",
    "It's not your turn!": "¡No es tu turno!", "You chose!": "¡Has elegido!", "Use `/fun help` or select a subcommand.": "Usa `/fun help` o selecciona un subcomando.", "You cannot play against yourself or a bot.": "No puedes jugar contra ti mismo ni contra un bot.",
    "Could not fetch a meme at the moment.": "No se ha podido obtener un meme en este momento.", "Could not fetch image.": "No se ha podido obtener la imagen.", "No repos tracked.": "No hay repositorios registrados.",
    "❌ Invalid interaction.": "❌ Interacción no válida.", "❌ Could not fetch image. Try again later.": "❌ No se pudo obtener la imagen. Inténtalo más tarde.", "❌ Could not fetch image.": "❌ No se pudo obtener la imagen.",
    "No custom commands found.": "No se encontraron comandos personalizados.", "No birthdays set.": "No hay cumpleaños configurados.", "No upcoming birthdays in the next 30 days.": "No hay próximos cumpleaños en los siguientes 30 días.", "❌ Invalid date.": "❌ Fecha no válida.", "✅ Birthday removed.": "✅ Cumpleaños eliminado.",
    "❌ `feedparser` not installed.": "❌ `feedparser` no está instalado.", "❌ Invalid feed URL.": "❌ URL de feed no válida.", "📰 No feeds.": "📰 No hay feeds.", "❌ No entries.": "❌ No hay entradas.", "❌ Feed already followed.": "❌ Este feed ya está seguido.",
    "❌ Server configuration not found.": "❌ No se encontró la configuración del servidor.", "❌ Suggestions channel not configured. Ask an admin to set it up!": "❌ No se ha configurado el canal de sugerencias. ¡Pide a un administrador que lo configure!", "❌ Suggestions channel not found.": "❌ No se encontró el canal de sugerencias.", "✅ Your suggestion has been submitted!": "✅ ¡Tu sugerencia se ha enviado!",
    "Usage: `/rr add <message_link> <role> [label] [emoji]`": "Uso: `/rr add <enlace_del_mensaje> <rol> [etiqueta] [emoji]`", "❌ Invalid message link.": "❌ Enlace de mensaje no válido.", "❌ This message has too many buttons.": "❌ Este mensaje tiene demasiados botones.", "❌ Button for that role not found on the message.": "❌ No se encontró un botón para ese rol en el mensaje.", "❌ Role not found. It might have been deleted.": "❌ No se encontró el rol. Puede que se haya eliminado.",
})

# Include the late legacy additions in the reverse English catalog as well.
for _source, _translated in LEGACY_TRANSLATIONS["es"].items():
    LEGACY_TRANSLATIONS["en"].setdefault(_translated, _source)

# The existing locale files remain the source for command metadata. Runtime
# keys fall back to English until their locale has a dedicated translation.

class I18n:
    def __init__(self, bot):
        self.bot = bot
        self.langs_dir = "langs"
        self.default_lang = "es"
        self.translations = {}
        self.reply_maps = {lang: {} for lang in SUPPORTED_LOCALES}
        self.reply_patterns = {lang: [] for lang in SUPPORTED_LOCALES}
        self.logger = logging.getLogger("Dabot.I18n")

    def load_languages(self):
        """Loads all language files from the langs directory."""
        if not os.path.exists(self.langs_dir):
            os.makedirs(self.langs_dir)
            self.logger.warning(f"Created {self.langs_dir} directory.")
            return

        for filename in os.listdir(self.langs_dir):
            if filename.endswith(".json"):
                lang_code = filename[:-5]
                try:
                    file_path = os.path.join(self.langs_dir, filename)
                    with open(file_path, "r", encoding="utf-8") as f:
                        self.translations[lang_code] = json.load(f)
                    self.logger.info(f"Loaded language: {lang_code}")
                    print(f"DEBUG: Loaded language {lang_code} from {os.path.abspath(file_path)} with {len(self.translations[lang_code])} keys")
                except Exception as e:
                    self.logger.error(f"Failed to load language {lang_code}: {e}")
                    print(f"DEBUG: Failed to load language {lang_code}: {e}")
        self._load_reply_catalogs()

    def _load_reply_catalogs(self):
        """Load exact + templated user-facing replies from langs/replies/."""
        self.reply_maps = {lang: {} for lang in SUPPORTED_LOCALES}
        self.reply_patterns = {lang: [] for lang in SUPPORTED_LOCALES}
        replies_dir = os.path.join(self.langs_dir, "replies")
        if not os.path.isdir(replies_dir):
            return

        catalog = {}
        for filename in os.listdir(replies_dir):
            if not filename.endswith(".json") or filename.startswith("_"):
                continue
            path = os.path.join(replies_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as exc:
                self.logger.error("Failed to load reply catalog %s: %s", filename, exc)
                continue
            if not isinstance(data, dict):
                continue
            stem = filename[:-5]
            for source, translated in data.items():
                if not isinstance(source, str):
                    continue
                bucket = catalog.setdefault(source, {})
                if isinstance(translated, str) and stem in SUPPORTED_LOCALES:
                    bucket[stem] = translated
                elif isinstance(translated, dict):
                    for lang, text in translated.items():
                        if lang in SUPPORTED_LOCALES and isinstance(text, str) and text:
                            bucket[lang] = text

        pattern_count = 0
        for source, by_lang in catalog.items():
            has_placeholder = bool(_PLACEHOLDER_RE.search(source))
            regex = None
            if has_placeholder:
                try:
                    regex = template_to_regex(source)
                except Exception:
                    regex = None
            for lang in SUPPORTED_LOCALES:
                dest = by_lang.get(lang) or by_lang.get("en") or source
                self.reply_maps[lang][source] = dest
                slash = self.translations.setdefault(lang, {}).setdefault("slash_commands", {})
                slash.setdefault(source, dest)
                if regex is not None:
                    try:
                        self.reply_patterns[lang].append((len(source), regex, uniquify_placeholders(dest)))
                        pattern_count += 1
                    except Exception:
                        pass

        for lang in SUPPORTED_LOCALES:
            self.reply_patterns[lang].sort(key=lambda item: -item[0])

        self.logger.info(
            "Loaded reply catalog: %s sources, %s pattern slots",
            len(catalog),
            pattern_count,
        )

    def load_translations(self):
        """Alias used by repair tools; same as load_languages."""
        return self.load_languages()

    def get(self, key, locale="en", **kwargs):
        """
        Retrieves a translation string.
        Fallback to default language if key or language is missing.
        Supports formatting with kwargs.
        """
        locale = str(locale or self.default_lang).split("-")[0].lower()
        if locale not in self.translations:
            locale = self.default_lang
        
        # Traverse nested keys
        keys = key.split('.')
        value = self.translations.get(locale, {})
        
        try:
            for k in keys:
                value = value[k]
        except (KeyError, TypeError):
            # Runtime strings are resolved here so cogs do not need to know
            # where the locale data is stored. This also gives us a safe
            # English fallback for newly added messages.
            runtime = RUNTIME_TRANSLATIONS.get(locale, {})
            if key.startswith("runtime."):
                try:
                    value = runtime
                    for k in keys[1:]:
                        value = value[k]
                except (KeyError, TypeError):
                    if locale != "en":
                        return self.get(key, "en", **kwargs)
                    return key
            elif locale not in ("en", self.default_lang):
                # A missing German/French/etc. key must not silently become
                # Spanish. English is the neutral fallback for incomplete
                # locale files. Never recurse on "en" itself.
                return self.get(key, "en", **kwargs)
            else:
                return key

        if isinstance(value, str):
            try:
                return value.format(**kwargs)
            except KeyError as e:
                self.logger.warning(f"Missing format key {e} for string {key} in {locale}")
                return value

        return value

    def _lookup_reply(self, text, locale):
        """Exact then templated lookup against the full reply catalog."""
        mapping = self.reply_maps.get(locale) or {}
        hit = mapping.get(text)
        if hit is not None:
            return hit
        for _length, regex, template in self.reply_patterns.get(locale) or []:
            match = regex.fullmatch(text)
            if not match:
                continue
            try:
                return template.format(**match.groupdict())
            except Exception:
                continue
        return None

    def translate_text(self, text, locale="es"):
        """Translate user-facing replies, including multiline static fragments."""
        if not isinstance(text, str) or not text:
            return text
        locale = str(locale or self.default_lang).split("-")[0].lower()
        if locale not in SUPPORTED_LOCALES:
            locale = "en" if locale != self.default_lang else self.default_lang

        catalog_hit = self._lookup_reply(text, locale)
        if catalog_hit is not None:
            return catalog_hit

        mapping = LEGACY_TRANSLATIONS.get(locale, {})
        fallback_mapping = LEGACY_TRANSLATIONS.get("en", {}) if locale != "en" else {}
        translated = mapping.get(text)
        if translated is None and fallback_mapping:
            translated = fallback_mapping.get(text)
        if translated is not None:
            return translated
        lines = text.splitlines(keepends=True)
        changed = False
        for index, line in enumerate(lines):
            body = line.rstrip("\r\n")
            replacement = self._lookup_reply(body, locale)
            if replacement is None:
                replacement = mapping.get(body)
            if replacement is None and fallback_mapping:
                replacement = fallback_mapping.get(body)
            if replacement is not None:
                lines[index] = replacement + line[len(body):]
                changed = True
        if changed:
            return "".join(lines)
        return text

    def translate_embed(self, embed, locale="es"):
        """Translate user-visible embed text while preserving the original embed."""
        if embed is None:
            return embed
        try:
            result = embed.copy()
        except Exception:
            result = copy.deepcopy(embed)
        translate = lambda value: self.translate_text(value, locale) if isinstance(value, str) else value
        for attr in ("title", "description"):
            value = getattr(result, attr, None)
            if value:
                setattr(result, attr, translate(value))
        author = getattr(result, "author", None)
        if author and getattr(author, "name", None):
            result.set_author(name=translate(author.name), icon_url=getattr(author, "icon_url", None), url=getattr(author, "url", None))
        footer = getattr(result, "footer", None)
        if footer and getattr(footer, "text", None):
            result.set_footer(text=translate(footer.text), icon_url=getattr(footer, "icon_url", None))
        for index, field in enumerate(list(getattr(result, "fields", []) or [])):
            result.set_field_at(index, name=translate(field.name), value=translate(field.value), inline=field.inline)
        return result

    def translate_view(self, view, locale="es"):
        """Translate labels/placeholders/options in a Discord component view."""
        if view is None:
            return view
        translate = lambda value: self.translate_text(value, locale) if isinstance(value, str) else value
        for item in list(getattr(view, "children", []) or []):
            if hasattr(item, "label") and isinstance(item.label, str):
                item.label = translate(item.label)
            if hasattr(item, "placeholder") and isinstance(item.placeholder, str):
                item.placeholder = translate(item.placeholder)
            for option in list(getattr(item, "options", []) or []):
                if isinstance(getattr(option, "label", None), str):
                    option.label = translate(option.label)
                if isinstance(getattr(option, "description", None), str):
                    option.description = translate(option.description)
        return view

    def translate_modal(self, modal, locale="es"):
        """Translate a modal title and its input labels/placeholders."""
        if modal is None:
            return modal
        translate = lambda value: self.translate_text(value, locale) if isinstance(value, str) else value
        if isinstance(getattr(modal, "title", None), str):
            modal.title = translate(modal.title)
        for item in list(getattr(modal, "children", []) or []):
            for attr in ("label", "placeholder"):
                if isinstance(getattr(item, attr, None), str):
                    setattr(item, attr, translate(getattr(item, attr)))
        return modal

class DiscordTranslator(app_commands.Translator):
    def __init__(self, i18n_instance):
        self.i18n = i18n_instance

    async def translate(self, string: app_commands.locale_str, locale: discord.Locale, context: app_commands.TranslationContext):
        """Translate descriptions only. Command *names* stay ASCII English so Discord sync never breaks."""
        loc = getattr(context.location, "name", str(context.location))
        if loc in ("command_name", "group_name", "parameter_name"):
            return None
        lang = str(locale).split("-")[0]
        if lang not in self.i18n.translations:
            return None
        msg = getattr(string, "message", None) or str(string)
        root = self.i18n.translations.get(lang, {}).get("slash_commands", {})
        hit = root.get(msg)
        if not hit:
            hit = (self.i18n.reply_maps.get(lang) or {}).get(msg)
        if not isinstance(hit, str):
            return None
        hit = hit.strip()
        # Discord rejects the whole sync if any localized description is
        # empty or longer than 100 characters (error 50035).
        desc_locs = (
            "command_description",
            "group_description",
            "parameter_description",
            "choice_name",
            "choice_description",
        )
        if loc in desc_locs and (not hit or len(hit) > 100):
            return None
        if hit and hit != msg:
            return hit
        return None
