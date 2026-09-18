import discord
import aiohttp
import os

async def send_webhook(bot, channel, content=None, file=None, embed=None, view=None):
    """
    Send a message via webhook with custom persona (if configured).
    Effectively replaces channel.send() for automated messages.
    """
    # Check if guild has Premium Persona configured
    try:
        if not await bot.db.is_guild_premium(channel.guild, bot):
            try:
                me = channel.guild.me
                if me and me.nick:
                    await me.edit(nick=None, reason="Dabot Premium persona disabled")
            except Exception:
                pass
            return await channel.send(content=content, file=file, embed=embed, view=view)

        data = await bot.db.fetch("SELECT custom_bot_name, custom_bot_avatar FROM premium_guilds WHERE guild_id = ?", channel.guild.id)
        
        custom_name = None
        custom_avatar = None
        
        if data:
            custom_name, custom_avatar = data
            
        # If no custom persona, just use normal send (cleaner than webhook default)
        if not custom_name and not custom_avatar:
            return await channel.send(content=content, file=file, embed=embed, view=view)

        # Keep the actual bot member name aligned too. The webhook is still
        # needed for a per-server avatar, which Discord cannot assign to a bot
        # user globally.
        try:
            me = channel.guild.me
            desired_nick = (custom_name or "").strip()[:32] or None
            if me and (me.nick or None) != desired_nick:
                await me.edit(nick=desired_nick, reason="Dabot Premium persona synchronization")
        except Exception:
            pass
            
        # If we have custom persona, we need a webhook
        webhook = None
        
        # 1. Check existing webhooks
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.name == "Dabot Persona" and wh.user == bot.user:
                webhook = wh
                break
        
        # 2. Create if not exists
        if not webhook:
            try:
                webhook = await channel.create_webhook(name="Dabot Persona")
            except Exception as e:
                # Fallback if perms missing or limit reached
                print(f"Failed to create webhook: {e}")
                return await channel.send(content=content, file=file, embed=embed, view=view)

        # 3. Send
        username = custom_name or bot.user.name
        avatar_url = custom_avatar or bot.user.display_avatar.url
        
        # Webhook.send doesn't support 'file' directly in same way as channel.send for some libs, 
        # but discord.py supports 'file' or 'files'.
        
        send_kwargs = {
            "content": content,
            "file": file,
            "embed": embed,
            "view": view,
            "username": username,
        }
        if custom_avatar and os.path.exists(str(custom_avatar)):
            with open(custom_avatar, "rb") as avatar_file:
                await webhook.edit(avatar=avatar_file.read())
        elif str(avatar_url).startswith(("http://", "https://")):
            send_kwargs["avatar_url"] = avatar_url
        elif custom_name and bot.user:
            # Do not leave an old custom avatar attached after the owner clears
            # it in the dashboard.
            try:
                await webhook.edit(avatar=await bot.user.display_avatar.read())
            except Exception:
                pass
        await webhook.send(**send_kwargs)
            
    except Exception as e:
        print(f"Webhook send error: {e}")
        # Always fallback to normal send
        return await channel.send(content=content, file=file, embed=embed, view=view)
