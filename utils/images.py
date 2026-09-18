from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
import io
import aiohttp
import discord
import os
import asyncio
import ipaddress
from urllib.parse import urlparse

_FONT_CANDIDATES = (
    "assets/font.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "arial.ttf",
)

MAX_REMOTE_IMAGE_BYTES = 8 * 1024 * 1024


def _safe_remote_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname.lower().rstrip(".")
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
            return False
        try:
            address = ipaddress.ip_address(host)
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
                return False
        except ValueError:
            pass
        return True
    except Exception:
        return False


async def _read_limited(response, limit: int = MAX_REMOTE_IMAGE_BYTES) -> bytes:
    length = response.headers.get("Content-Length")
    if length and int(length) > limit:
        raise ValueError("remote image too large")
    data = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            raise ValueError("remote image too large")
    return bytes(data)


def get_font(size):
    for path in _FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            return ImageFont.truetype(path, int(size))
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=int(size))
    except TypeError:
        return ImageFont.load_default()

def circular_avatar(image, size):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0) + size, fill=255)
    output = ImageOps.fit(image, size, centering=(0.5, 0.5))
    output.putalpha(mask)
    return output

def draw_rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    """Draw a rectangle with rounded corners."""
    x0, y0, x1, y1 = xy
    # Clamp radius
    max_radius = min((x1 - x0) // 2, (y1 - y0) // 2)
    radius = min(radius, max_radius)
    if radius < 1:
        draw.rectangle(xy, fill=fill, outline=outline, width=width)
        return
    # Draw rounded corners + center
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

def create_rounded_mask(size, radius):
    """Create a mask for a rounded rectangle."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask

def draw_gradient_bar(draw, xy, progress, colors_start, colors_end):
    """Draw a progress bar with a horizontal gradient."""
    x0, y0, x1, y1 = xy
    bar_width = x1 - x0
    bar_height = y1 - y0
    fill_width = int(bar_width * progress)
    
    if fill_width <= 0:
        return
    
    for x in range(fill_width):
        ratio = x / max(bar_width - 1, 1)
        r = int(colors_start[0] + (colors_end[0] - colors_start[0]) * ratio)
        g = int(colors_start[1] + (colors_end[1] - colors_start[1]) * ratio)
        b = int(colors_start[2] + (colors_end[2] - colors_start[2]) * ratio)
        draw.line([(x0 + x, y0), (x0 + x, y1)], fill=(r, g, b))

def get_rank_badge(rank):
    """Plain text badge — the bundled font has no emoji glyphs."""
    if rank == 1:
        return "TOP 1"
    if rank == 2:
        return "TOP 2"
    if rank == 3:
        return "TOP 3"
    if rank <= 10:
        return "TOP 10"
    return ""


def strip_draw_text(text: str) -> str:
    """Drop emoji/symbols the rank-card font cannot render."""
    import re
    cleaned = re.sub(
        r"[\U0001F000-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF"
        r"\U0000FE00-\U0000FE0F\U0000200D\U0001F1E0-\U0001F1FF]+",
        "",
        str(text or ""),
    )
    return " ".join(cleaned.split()).strip()

async def load_background(source, session=None):
    if not source:
        return None
        
    try:
        if str(source).startswith("http"):
            if not _safe_remote_url(str(source)):
                return None
            if session:
                async with session.get(str(source)) as resp:
                    if resp.status == 200:
                        data = await _read_limited(resp)
                        return Image.open(io.BytesIO(data)).convert("RGBA")
            else:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10, connect=3, sock_read=8)) as session_temp:
                    async with session_temp.get(str(source)) as resp:
                        if resp.status == 200:
                            data = await _read_limited(resp)
                            return Image.open(io.BytesIO(data)).convert("RGBA")
        elif os.path.exists(str(source)):
            def _open_file():
                return Image.open(str(source)).convert("RGBA")
            return await asyncio.to_thread(_open_file)
    except Exception as e:
        print(f"Failed to load background {source}: {e}")
    return None


async def persist_discord_image(attachment, guild_id, purpose="welcome"):
    """Persist a Discord upload before its CDN/ephemeral URL expires."""
    if not attachment or not str(getattr(attachment, "content_type", "")).startswith("image/"):
        raise ValueError("The attachment is not an image")
    size = int(getattr(attachment, "size", 0) or 0)
    if size > 8 * 1024 * 1024:
        raise ValueError("The image is larger than 8 MB")
    data = await attachment.read()
    if not data or len(data) > 8 * 1024 * 1024:
        raise ValueError("The image is empty or larger than 8 MB")

    def validate_and_write():
        from PIL import Image as _Image
        with _Image.open(io.BytesIO(data)) as image:
            image.verify()
        database_path = os.environ.get("DATABASE_PATH", "dabot.db")
        data_dir = os.path.dirname(os.path.abspath(database_path))
        folder = "premium_avatars" if purpose == "bot_avatar" else "welcome_backgrounds"
        target_dir = os.path.join(data_dir, folder)
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, f"{int(guild_id)}.png")
        # Keep the on-disk format stable and remove metadata from user uploads.
        with _Image.open(io.BytesIO(data)) as image:
            image.convert("RGB").save(target, format="PNG", optimize=True)
        return os.path.relpath(target, os.getcwd())

    return await asyncio.to_thread(validate_and_write)

def _create_welcome_card_sync(avatar_bytes, background, background_source, member_name, member_guild_members_count,
                              welcome_text="BIENVENIDO", member_label="Miembro", custom_text="", layout=None):
    target_size = (1024, 500)
    layout = layout if isinstance(layout, dict) else {}

    def coord(key, default, low, high):
        try:
            return max(low, min(high, int(layout.get(key, default))))
        except (TypeError, ValueError):
            return default

    avatar_x = coord("avatar_x", 512, 0, target_size[0])
    avatar_y = coord("avatar_y", 205, 0, target_size[1])
    avatar_size = coord("avatar_size", 220, 64, 360)
    heading_x = coord("heading_x", 512, 0, target_size[0])
    heading_y = coord("heading_y", 330, 0, target_size[1] - 60)
    name_x = coord("name_x", 512, 0, target_size[0])
    name_y = coord("name_y", 391, 0, target_size[1] - 45)
    member_x = coord("member_x", 512, 0, target_size[0])
    member_y = coord("member_y", 435, 0, target_size[1] - 30)
    custom_x = coord("custom_x", 512, 0, target_size[0])
    custom_y = coord("custom_y", 60, 0, target_size[1] - 30)
    custom_size = coord("custom_size", 26, 12, 64)
    
    if not background:
        if background_source and os.path.exists(background_source):
             background = Image.open(background_source).convert("RGBA")
        else:
             background = Image.new("RGBA", target_size, (90, 18, 12, 255))
             bg_draw = ImageDraw.Draw(background)
             for x in range(target_size[0]):
                 ratio = x / max(target_size[0] - 1, 1)
                 r = int(90 + 140 * ratio)
                 g = int(18 + 70 * ratio)
                 b = int(12 + 8 * ratio)
                 bg_draw.line([(x, 0), (x, target_size[1])], fill=(r, g, b, 255))

    background = background.resize(target_size)
    bg_blurred = background.filter(ImageFilter.GaussianBlur(radius=3))
    background = Image.blend(background, bg_blurred, 0.3)

    overlay = Image.new("RGBA", target_size, (0, 0, 0, 120))
    background = Image.alpha_composite(background, overlay)

    glass_panel = Image.new("RGBA", target_size, (0, 0, 0, 0))
    glass_draw = ImageDraw.Draw(glass_panel)
    panel_margin = 60
    panel_rect = (panel_margin, panel_margin, target_size[0] - panel_margin, target_size[1] - panel_margin)
    draw_rounded_rect(glass_draw, panel_rect, radius=30, fill=(255, 255, 255, 35))
    draw_rounded_rect(glass_draw, panel_rect, radius=30, outline=(255, 255, 255, 60), width=2)
    background = Image.alpha_composite(background, glass_panel)

    draw = ImageDraw.Draw(background)

    if avatar_bytes:
        try:
            avatar_image = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar_dimensions = (avatar_size, avatar_size)
            avatar_image = circular_avatar(avatar_image, avatar_dimensions)

            ring = Image.new("RGBA", (avatar_size + 12, avatar_size + 12), (0, 0, 0, 0))
            ring_draw = ImageDraw.Draw(ring)
            ring_draw.ellipse((0, 0, avatar_size + 11, avatar_size + 11), outline=(226, 61, 40, 230), width=5)

            avatar_left = avatar_x - avatar_size // 2
            avatar_top = avatar_y - avatar_size // 2
            background.paste(ring, (avatar_left - 6, avatar_top - 6), ring)
            background.paste(avatar_image, (avatar_left, avatar_top), avatar_image)
        except Exception as e:
            print(f"Error processing avatar: {e}")

    font_large = get_font(56)
    font_small = get_font(36)

    welcome_text = (strip_draw_text(welcome_text) or "BIENVENIDO")[:24]
    text_bbox = draw.textbbox((0, 0), welcome_text, font=font_large)
    text_width = text_bbox[2] - text_bbox[0]
    text_x = heading_x - text_width / 2
    draw.text((text_x + 2, heading_y + 2), welcome_text, font=font_large, fill=(0, 0, 0, 150))
    draw.text((text_x, heading_y), welcome_text, font=font_large, fill=(255, 244, 232))

    name_text = member_name.upper()
    if len(name_text) > 22:
        name_text = name_text[:21] + "…"
    name_bbox = draw.textbbox((0, 0), name_text, font=font_small)
    name_width = name_bbox[2] - name_bbox[0]
    name_left = name_x - name_width / 2
    draw.text((name_left + 1, name_y + 2), name_text, font=font_small, fill=(0, 0, 0, 100))
    draw.text((name_left, name_y), name_text, font=font_small, fill=(226, 61, 40))

    member_text = f"{(strip_draw_text(member_label) or 'Miembro')[:20]} #{member_guild_members_count}"
    count_bbox = draw.textbbox((0, 0), member_text, font=get_font(26))
    count_width = count_bbox[2] - count_bbox[0]
    draw.text((member_x - count_width / 2, member_y), member_text, font=get_font(26), fill=(255, 196, 160))

    custom_text = strip_draw_text(custom_text)
    if custom_text:
        custom_text = custom_text[:60]
        custom_font = get_font(custom_size)
        custom_bbox = draw.textbbox((0, 0), custom_text, font=custom_font)
        custom_width = custom_bbox[2] - custom_bbox[0]
        custom_left = custom_x - custom_width / 2
        draw.text((custom_left + 1, custom_y + 1), custom_text, font=custom_font, fill=(0, 0, 0, 130))
        draw.text((custom_left, custom_y), custom_text, font=custom_font, fill=(255, 255, 255, 235))

    mask = create_rounded_mask(target_size, 25)
    output = Image.new("RGBA", target_size, (0, 0, 0, 0))
    output.paste(background, (0, 0), mask)

    buffer = io.BytesIO()
    output.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

async def create_welcome_card(member: discord.Member, background_source="assets/welcome_background.jpg", session=None,
                              welcome_text="BIENVENIDO", member_label="Miembro", custom_text="", layout=None):
    background = await load_background(background_source, session=session)
    
    avatar_bytes = None
    try:
        avatar_bytes = await member.display_avatar.read()
    except Exception as e:
        print(f"Error reading avatar: {e}")

    buffer = await asyncio.to_thread(
        _create_welcome_card_sync,
        avatar_bytes=avatar_bytes,
        background=background,
        background_source=background_source,
        member_name=member.name,
        member_guild_members_count=len(member.guild.members),
        welcome_text=welcome_text,
        member_label=member_label,
        custom_text=custom_text,
        layout=layout,
    )
    return discord.File(buffer, filename="welcome.png")

def _create_level_card_sync(avatar_bytes, background, background_source, member_display_name, level, xp, target_xp, rank,
                            custom_text="", layout=None):
    width, height = 1200, 400
    layout = layout if isinstance(layout, dict) else {}

    def coord(key, default, low, high):
        try:
            return max(low, min(high, int(layout.get(key, default))))
        except (TypeError, ValueError):
            return default

    avatar_x = coord("avatar_x", 158, 0, width)
    avatar_y = coord("avatar_y", 200, 0, height)
    avatar_size = coord("avatar_size", 220, 64, 320)
    name_x = coord("name_x", 310, 0, width)
    name_y = coord("name_y", 48, 0, height - 50)
    rank_x = coord("rank_x", 310, 0, width)
    rank_y = coord("rank_y", 118, 0, height - 45)
    level_x = coord("level_x", 1152, 0, width)
    level_y = coord("level_y", 40, 0, height - 90)
    bar_x = coord("bar_x", 310, 0, width - 100)
    bar_y = coord("bar_y", 250, 0, height - 60)
    bar_w = coord("bar_width", 830, 160, width - bar_x)
    bar_h = coord("bar_height", 44, 20, 80)
    xp_x = coord("xp_x", bar_x, 0, width)
    xp_y = coord("xp_y", 200, 0, height - 40)
    percent_x = coord("percent_x", bar_x + bar_w, 0, width)
    percent_y = coord("percent_y", 200, 0, height - 40)
    brand_x = coord("brand_x", 48, 0, width)
    brand_y = coord("brand_y", height - 52, 0, height - 25)
    custom_x = coord("custom_x", 720, 0, width)
    custom_y = coord("custom_y", 345, 0, height - 25)
    custom_size = coord("custom_size", 28, 12, 64)
    
    if not background:
         if background_source and os.path.exists(background_source):
             background = Image.open(background_source).convert("RGBA")
         else:
             background = Image.new("RGBA", (width, height), (40, 8, 6, 255))
             bg_draw = ImageDraw.Draw(background)
             for x in range(width):
                 ratio = x / width
                 r = int(90 + 140 * ratio)
                 g = int(18 + 70 * ratio)
                 b = int(12 + 8 * ratio)
                 bg_draw.line([(x, 0), (x, height)], fill=(r, g, b, 255))

    background = background.resize((width, height))
    bg_blurred = background.filter(ImageFilter.GaussianBlur(radius=2))
    background = Image.blend(background, bg_blurred, 0.2)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 160))
    background = Image.alpha_composite(background, overlay)

    glass = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glass_draw = ImageDraw.Draw(glass)
    panel_rect = (20, 20, width - 20, height - 20)
    draw_rounded_rect(glass_draw, panel_rect, radius=20, fill=(255, 255, 255, 25))
    draw_rounded_rect(glass_draw, panel_rect, radius=20, outline=(255, 255, 255, 40), width=2)
    background = Image.alpha_composite(background, glass)
    
    draw = ImageDraw.Draw(background)

    if avatar_bytes:
        try:
            avatar_image = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar_size = (avatar_size, avatar_size)
            avatar_image = circular_avatar(avatar_image, avatar_size)
            
            ring_size = (avatar_size[0] + 14, avatar_size[1] + 14)
            ring = Image.new("RGBA", ring_size, (0, 0, 0, 0))
            ring_draw = ImageDraw.Draw(ring)
            ring_draw.ellipse((0, 0, ring_size[0] - 1, ring_size[1] - 1), outline=(226, 61, 40), width=7)
            
            avatar_left = avatar_x - avatar_size[0] // 2
            avatar_top = avatar_y - avatar_size[1] // 2
            background.paste(ring, (avatar_left - 7, avatar_top - 7), ring)
            background.paste(avatar_image, (avatar_left, avatar_top), avatar_image)
        except:
            pass

    font_large = get_font(82)
    font_medium = get_font(54)
    font_small = get_font(40)
    font_tiny = get_font(36)
    lobster_red = (226, 61, 40)
    lobster_orange = (249, 115, 22)
    cream = (255, 244, 232)
    stroke = (40, 8, 6)

    username = strip_draw_text(member_display_name) or "Usuario"
    if len(username) > 18:
        username = username[:17] + "…"
    draw.text((name_x, name_y), username, font=font_medium, fill=cream, stroke_width=3, stroke_fill=stroke)

    badge = get_rank_badge(rank)
    rank_text = f"{badge}  RANK  #{rank}".strip() if badge else f"RANK  #{rank}"
    rank_text = strip_draw_text(rank_text)
    draw.text((rank_x, rank_y), rank_text, font=font_small, fill=(255, 210, 170), stroke_width=2, stroke_fill=stroke)

    level_text = f"NV. {level}"
    level_bbox = draw.textbbox((0, 0), level_text, font=font_large)
    level_width = level_bbox[2] - level_bbox[0]
    draw.text((level_x - level_width, level_y), level_text, font=font_large, fill=lobster_red, stroke_width=4, stroke_fill=stroke)

    draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=18, fill=(60, 60, 80))

    if target_xp > 0:
        progress = min(xp / target_xp, 1.0)
    else:
        progress = 0
    
    fill_w = int(bar_w * progress)
    if fill_w > 4:
        gradient_bar = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gradient_bar)
        draw_rounded_rect(gd, (0, 0, bar_w, bar_h), radius=16, fill=(60, 60, 80))
        
        for x in range(fill_w):
            ratio = x / max(bar_w - 1, 1)
            r = int(226 + (249 - 226) * ratio)
            g = int(61 + (115 - 61) * ratio)
            b = int(40 + (22 - 40) * ratio)
            gd.line([(x, 0), (x, bar_h)], fill=(r, g, b))
        
        bar_mask = create_rounded_mask((bar_w, bar_h), 16)
        gradient_bar.putalpha(bar_mask)
        background.paste(gradient_bar, (bar_x, bar_y), gradient_bar)
        draw = ImageDraw.Draw(background)

    xp_text = f"{xp:,}  /  {target_xp:,}  XP"
    draw.text((xp_x, xp_y), xp_text, font=font_tiny, fill=(255, 220, 190), stroke_width=2, stroke_fill=stroke)

    pct = int(progress * 100)
    pct_text = f"{pct}%"
    pct_bbox = draw.textbbox((0, 0), pct_text, font=font_tiny)
    pct_width = pct_bbox[2] - pct_bbox[0]
    draw.text((percent_x - pct_width, percent_y), pct_text, font=font_tiny, fill=lobster_orange, stroke_width=2, stroke_fill=stroke)

    brand = "DABOT"
    draw.text((brand_x, brand_y), brand, font=get_font(28), fill=(255, 140, 90), stroke_width=2, stroke_fill=stroke)

    custom_text = strip_draw_text(custom_text)
    if custom_text:
        custom_text = custom_text[:80]
        custom_font = get_font(custom_size)
        custom_bbox = draw.textbbox((0, 0), custom_text, font=custom_font)
        custom_width = custom_bbox[2] - custom_bbox[0]
        draw.text((custom_x - custom_width / 2 + 1, custom_y + 1), custom_text,
                  font=custom_font, fill=(0, 0, 0, 140))
        draw.text((custom_x - custom_width / 2, custom_y), custom_text,
                  font=custom_font, fill=(255, 244, 232, 235))

    mask = create_rounded_mask((width, height), 20)
    output = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    output.paste(background, (0, 0), mask)

    buffer = io.BytesIO()
    output.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

async def create_level_card(member: discord.Member, level, xp, target_xp, rank,
                            background_source="assets/card_background.jpg", session=None,
                            custom_text="", layout=None):
    background = await load_background(background_source, session=session)
    
    avatar_bytes = None
    try:
        avatar_bytes = await member.display_avatar.read()
    except Exception as e:
        print(f"Error reading avatar: {e}")

    buffer = await asyncio.to_thread(
        _create_level_card_sync,
        avatar_bytes=avatar_bytes,
        background=background,
        background_source=background_source,
        member_display_name=member.display_name,
        level=level,
        xp=xp,
        target_xp=target_xp,
        rank=rank,
        custom_text=custom_text,
        layout=layout,
    )
    return discord.File(buffer, filename="rank.png")

async def prepare_sticker_image(url, session=None):
    try:
        if not _safe_remote_url(url):
            return None
        if session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await _read_limited(resp)
                    
                    def _process():
                        image = Image.open(io.BytesIO(data))
                        image.thumbnail((320, 320))
                        buf = io.BytesIO()
                        image.save(buf, format="PNG")
                        buf.seek(0)
                        return buf
                        
                    return await asyncio.to_thread(_process)
        else:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10, connect=3, sock_read=8)) as session_temp:
                async with session_temp.get(url) as resp:
                    if resp.status == 200:
                        data = await _read_limited(resp)
                        
                        def _process():
                            image = Image.open(io.BytesIO(data))
                            image.thumbnail((320, 320))
                            buf = io.BytesIO()
                            image.save(buf, format="PNG")
                            buf.seek(0)
                            return buf
                            
                        return await asyncio.to_thread(_process)
    except Exception as e:
        print(f"Sticker error: {e}")
        return None

def _create_side_by_side_comparison_sync(before_bytes, after_bytes, label_before="ANTES", label_after="DESPUÉS"):
    try:
        img_before = Image.open(io.BytesIO(before_bytes)).convert("RGBA")
        img_after = Image.open(io.BytesIO(after_bytes)).convert("RGBA")
    except Exception as e:
        print(f"Error opening image bytes for side-by-side comparison: {e}")
        return None

    size = (256, 256)
    img_before = img_before.resize(size)
    img_after = img_after.resize(size)

    width = size[0] * 2 + 80
    height = size[1] + 80
    
    canvas = Image.new("RGBA", (width, height), (30, 30, 40, 255))
    draw = ImageDraw.Draw(canvas)
    
    font = get_font(20)
    
    x_before = 20
    y_img = 50
    canvas.paste(img_before, (x_before, y_img), img_before)
    
    x_after = size[0] + 60
    canvas.paste(img_after, (x_after, y_img), img_after)
    
    def draw_centered_text(xy, text, font, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x, y = xy
        draw.text((x - w // 2, y - h // 2), text, font=font, fill=fill)
        
    draw_centered_text((x_before + size[0] // 2, 25), label_before, font, (255, 100, 100))
    draw_centered_text((x_after + size[0] // 2, 25), label_after, font, (0, 255, 200))
    draw_centered_text((size[0] + 40, y_img + size[1] // 2), "➡️", font, (255, 255, 255))

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

async def create_side_by_side_comparison(before_bytes, after_bytes, label_before="ANTES", label_after="DESPUÉS"):
    return await asyncio.to_thread(_create_side_by_side_comparison_sync, before_bytes, after_bytes, label_before, label_after)

async def create_avatar_comparison(before_bytes, after_bytes):
    return await create_side_by_side_comparison(before_bytes, after_bytes, "ANTES", "DESPUÉS")

def _create_activity_chart_sync(data_points, title):
    # Dimensions
    width, height = 800, 400
    img = Image.new("RGBA", (width, height), (15, 15, 19, 255)) 
    draw = ImageDraw.Draw(img)
    
    title_font = get_font(24)
    label_font = get_font(12)
    val_font = get_font(14)
    
    draw.rectangle([0, 0, width, height], outline=(50, 50, 60, 255), width=2)
    draw.text((30, 25), title, fill=(255, 255, 255, 255), font=title_font)
    
    margin_left = 60
    margin_right = 40
    margin_top = 80
    margin_bottom = 50
    
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom
    
    if not data_points:
        draw.text((width//2 - 100, height//2), "Sin datos de actividad", fill=(120, 120, 130, 255), font=val_font)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer
        
    labels = [d[0] for d in data_points]
    values = [d[1] for d in data_points]
    
    max_val = max(values) if max(values) > 0 else 10
    y_max = int(max_val * 1.2)
    num_points = len(data_points)
    x_step = chart_width / (num_points - 1) if num_points > 1 else chart_width
    
    for i in range(5):
        y_val = int(y_max * i / 4)
        y_pos = margin_top + chart_height - (y_val / y_max) * chart_height
        
        if i > 0 and i < 4:
            draw.line([margin_left, y_pos, width - margin_right, y_pos], fill=(40, 40, 50, 255), width=1)
            
        draw.text((margin_left - 15, y_pos - 7), str(y_val), fill=(150, 150, 160, 255), font=label_font, anchor="rm")
        
    coords = []
    for i, (label, val) in enumerate(data_points):
        x = margin_left + i * x_step
        y = margin_top + chart_height - (val / y_max) * chart_height
        coords.append((x, y))
        
        short_label = label
        if len(label) >= 10:
            short_label = label[5:] 
        draw.text((x, margin_top + chart_height + 15), short_label, fill=(150, 150, 160, 255), font=label_font, anchor="mm")
        
    if len(coords) > 1:
        for i in range(len(coords) - 1):
            draw.line([coords[i], coords[i+1]], fill=(0, 210, 242, 50), width=6)
        for i in range(len(coords) - 1):
            draw.line([coords[i], coords[i+1]], fill=(0, 242, 254, 255), width=3)
            
    for i, (x, y) in enumerate(coords):
        val = values[i]
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(0, 242, 254, 255))
        draw.ellipse([x - 8, y - 8, x + 8, y + 8], outline=(0, 210, 242, 100), width=2)
        draw.text((x, y - 18), str(val), fill=(255, 255, 255, 255), font=val_font, anchor="mm")
        
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

async def create_activity_chart(data_points, title):
    return await asyncio.to_thread(_create_activity_chart_sync, data_points, title)
