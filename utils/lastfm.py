import asyncio
import io
import logging
import os
import time
import urllib.parse
from datetime import datetime, timezone
import aiohttp

log = logging.getLogger("Dabot.LastFM")

LASTFM_API_KEY = os.getenv("LASTFM_API_KEY", "")
BASE_URL = "https://ws.audioscrobbler.com/2.0/"
USER_AGENT = "Dabot/3.1.0 (https://dabot.davito.es)"

_CACHE = {}  # key -> (data, expire_at)


def _get_cache(key: str):
    now = time.time()
    if key in _CACHE:
        val, exp = _CACHE[key]
        if exp > now:
            return val
        del _CACHE[key]
    return None


def _set_cache(key: str, data, ttl: int = 20):
    _CACHE[key] = (data, time.time() + ttl)


def get_spotify_search_url(track: str, artist: str) -> str:
    query = f"{artist} {track}".strip()
    return f"https://open.spotify.com/search/{urllib.parse.quote(query)}"


class LastFMClient:
    """Asynchronous client for the Last.fm AudioScrobbler 2.0 API with caching."""

    def __init__(self, api_key: str = None, session: aiohttp.ClientSession = None):
        self.api_key = api_key or LASTFM_API_KEY
        self.session = session
        self._internal_session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        if self._internal_session is None or self._internal_session.closed:
            self._internal_session = aiohttp.ClientSession(
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._internal_session

    async def close(self):
        if self._internal_session and not self._internal_session.closed:
            await self._internal_session.close()

    async def _request(self, method: str, params: dict, ttl: int = 15) -> dict | None:
        cache_key = f"{method}:{sorted(params.items())}"
        cached = _get_cache(cache_key)
        if cached is not None:
            return cached

        req_params = {
            "method": method,
            "api_key": self.api_key,
            "format": "json",
            **params
        }

        try:
            session = await self._get_session()
            async with session.get(BASE_URL, params=req_params) as resp:
                if resp.status != 200:
                    log.warning(f"Last.fm API returned HTTP {resp.status} for {method}")
                    return None
                data = await resp.json()
                if "error" in data:
                    log.warning(f"Last.fm API error {data.get('error')}: {data.get('message')}")
                    return None
                _set_cache(cache_key, data, ttl=ttl)
                return data
        except Exception as e:
            log.error(f"Last.fm API request error ({method}): {e}")
            return None

    async def get_user_info(self, username: str) -> dict | None:
        """Fetch general profile info for a user."""
        data = await self._request("user.getinfo", {"user": username}, ttl=60)
        if not data or "user" not in data:
            return None
        u = data["user"]
        images = u.get("image", [])
        avatar = ""
        for img in reversed(images):
            if img.get("#text"):
                avatar = img["#text"]
                break

        return {
            "name": u.get("name", username),
            "realname": u.get("realname", ""),
            "playcount": int(u.get("playcount", 0)),
            "registered": u.get("registered", {}).get("#text", ""),
            "registered_uts": int(u.get("registered", {}).get("unixtime", 0)),
            "url": u.get("url", f"https://www.last.fm/user/{username}"),
            "avatar": avatar,
            "country": u.get("country", "")
        }

    async def get_recent_tracks(self, username: str, limit: int = 2) -> dict | None:
        """Fetch recent tracks for a user and check if one is currently playing."""
        data = await self._request("user.getrecenttracks", {"user": username, "limit": limit}, ttl=10)
        if not data or "recenttracks" not in data:
            return None

        rt = data["recenttracks"]
        raw_tracks = rt.get("track", [])
        if isinstance(raw_tracks, dict):
            raw_tracks = [raw_tracks]

        total_scrobbles = int(rt.get("@attr", {}).get("total", 0))

        tracks = []
        now_playing = False
        current_track = None

        for t in raw_tracks:
            artist_name = t.get("artist", {}).get("#text", "")
            track_name = t.get("name", "")
            album_name = t.get("album", {}).get("#text", "")
            url = t.get("url", "")
            is_now = t.get("@attr", {}).get("nowplaying") == "true"

            images = t.get("image", [])
            img_url = ""
            for img in reversed(images):
                if img.get("#text"):
                    img_url = img["#text"]
                    break

            date_str = t.get("date", {}).get("#text", "")
            uts = t.get("date", {}).get("uts", "")

            track_obj = {
                "name": track_name,
                "artist": artist_name,
                "album": album_name,
                "image": img_url,
                "url": url,
                "now_playing": is_now,
                "date": date_str,
                "uts": uts,
                "spotify_url": get_spotify_search_url(track_name, artist_name)
            }
            tracks.append(track_obj)
            if is_now and current_track is None:
                now_playing = True
                current_track = track_obj

        if not current_track and tracks:
            current_track = tracks[0]

        return {
            "username": rt.get("@attr", {}).get("user", username),
            "now_playing": now_playing,
            "current": current_track,
            "tracks": tracks,
            "total_scrobbles": total_scrobbles
        }

    async def get_track_info(self, artist: str, track: str, username: str = None) -> dict:
        """Get details about a track including personal playcount and loved status."""
        params = {"artist": artist, "track": track}
        if username:
            params["username"] = username

        data = await self._request("track.getinfo", params, ttl=30)
        if not data or "track" not in data:
            return {"userplaycount": 0, "userloved": False, "listeners": 0, "playcount": 0, "tags": []}

        t = data["track"]
        tags = [tag.get("name") for tag in t.get("toptags", {}).get("tag", []) if tag.get("name")]
        return {
            "userplaycount": int(t.get("userplaycount", 0)),
            "userloved": str(t.get("userloved", "0")) == "1",
            "listeners": int(t.get("listeners", 0)),
            "playcount": int(t.get("playcount", 0)),
            "duration": int(t.get("duration", 0)),
            "tags": tags[:4],
            "url": t.get("url", "")
        }

    async def get_artist_info(self, artist: str, username: str = None) -> dict:
        """Get details about an artist including personal playcount and tags."""
        params = {"artist": artist}
        if username:
            params["username"] = username

        data = await self._request("artist.getinfo", params, ttl=30)
        if not data or "artist" not in data:
            return {"userplaycount": 0, "listeners": 0, "playcount": 0, "tags": [], "bio_summary": ""}

        a = data["artist"]
        stats = a.get("stats", {})
        tags = [tag.get("name") for tag in a.get("tags", {}).get("tag", []) if tag.get("name")]
        bio = a.get("bio", {}).get("summary", "")
        if bio:
            bio = bio.split("<a href=")[0].strip()

        return {
            "userplaycount": int(stats.get("userplaycount", 0)),
            "listeners": int(stats.get("listeners", 0)),
            "playcount": int(stats.get("playcount", 0)),
            "tags": tags[:4],
            "bio_summary": bio[:200]
        }

    async def get_top_artists(self, username: str, period: str = "7day", limit: int = 10) -> list[dict]:
        """Fetch top artists for a period (7day, 1month, 3month, 6month, 12month, overall)."""
        data = await self._request("user.gettopartists", {"user": username, "period": period, "limit": limit}, ttl=60)
        if not data or "topartists" not in data:
            return []
        items = data["topartists"].get("artist", [])
        if isinstance(items, dict):
            items = [items]

        result = []
        for a in items:
            images = a.get("image", [])
            img_url = ""
            for img in reversed(images):
                if img.get("#text"):
                    img_url = img["#text"]
                    break
            result.append({
                "name": a.get("name", ""),
                "playcount": int(a.get("playcount", 0)),
                "url": a.get("url", ""),
                "image": img_url
            })
        return result

    async def get_top_albums(self, username: str, period: str = "7day", limit: int = 10) -> list[dict]:
        """Fetch top albums for a period."""
        data = await self._request("user.gettopalbums", {"user": username, "period": period, "limit": limit}, ttl=60)
        if not data or "topalbums" not in data:
            return []
        items = data["topalbums"].get("album", [])
        if isinstance(items, dict):
            items = [items]

        result = []
        for alb in items:
            images = alb.get("image", [])
            img_url = ""
            for img in reversed(images):
                if img.get("#text"):
                    img_url = img["#text"]
                    break
            result.append({
                "name": alb.get("name", ""),
                "artist": alb.get("artist", {}).get("name", "") if isinstance(alb.get("artist"), dict) else str(alb.get("artist", "")),
                "playcount": int(alb.get("playcount", 0)),
                "url": alb.get("url", ""),
                "image": img_url
            })
        return result

    async def get_top_tracks(self, username: str, period: str = "7day", limit: int = 10) -> list[dict]:
        """Fetch top tracks for a period."""
        data = await self._request("user.gettoptracks", {"user": username, "period": period, "limit": limit}, ttl=60)
        if not data or "toptracks" not in data:
            return []
        items = data["toptracks"].get("track", [])
        if isinstance(items, dict):
            items = [items]

        result = []
        for tr in items:
            images = tr.get("image", [])
            img_url = ""
            for img in reversed(images):
                if img.get("#text"):
                    img_url = img["#text"]
                    break
            artist_name = tr.get("artist", {}).get("name", "") if isinstance(tr.get("artist"), dict) else str(tr.get("artist", ""))
            result.append({
                "name": tr.get("name", ""),
                "artist": artist_name,
                "playcount": int(tr.get("playcount", 0)),
                "url": tr.get("url", ""),
                "image": img_url,
                "spotify_url": get_spotify_search_url(tr.get("name", ""), artist_name)
            })
        return result

    async def compare_users(self, user1: str, user2: str, period: str = "1month") -> dict:
        """Compare musical taste between two users based on top 50 artists."""
        top1, top2 = await asyncio.gather(
            self.get_top_artists(user1, period=period, limit=50),
            self.get_top_artists(user2, period=period, limit=50)
        )

        dict1 = {a["name"].lower(): a["playcount"] for a in top1}
        dict2 = {a["name"].lower(): a["playcount"] for a in top2}

        common_keys = set(dict1.keys()) & set(dict2.keys())
        common_artists = []
        for k in common_keys:
            # find original casing
            orig_name = next((a["name"] for a in top1 if a["name"].lower() == k), k)
            common_artists.append({
                "name": orig_name,
                "plays1": dict1[k],
                "plays2": dict2[k],
                "total": dict1[k] + dict2[k]
            })

        common_artists.sort(key=lambda x: x["total"], reverse=True)

        if not dict1 or not dict2:
            score = 0
        else:
            jaccard = len(common_keys) / (len(set(dict1.keys()) | set(dict2.keys())) or 1)
            score = min(100, int(jaccard * 250))

        if score >= 80:
            rating = "¡Almas Gemelas! 💖"
        elif score >= 60:
            rating = "Muy Alta 🔥"
        elif score >= 40:
            rating = "Media 🎶"
        elif score >= 20:
            rating = "Baja 📻"
        else:
            rating = "Muy Distantes ❄️"

        return {
            "score": score,
            "rating": rating,
            "common_count": len(common_artists),
            "common_artists": common_artists[:10]
        }

    async def generate_chart_image(self, username: str, size: int = 3, period: str = "7day") -> io.BytesIO | None:
        """Generate a visual album collage (3x3, 4x4, or 5x5) using Pillow."""
        from PIL import Image, ImageDraw, ImageFont

        total_tiles = size * size
        albums = await self.get_top_albums(username, period=period, limit=total_tiles)
        if not albums:
            return None

        tile_size = 280
        canvas_dim = tile_size * size
        canvas = Image.new("RGB", (canvas_dim, canvas_dim), color=(15, 15, 18))

        session = await self._get_session()

        async def fetch_image(url: str):
            if not url:
                return None
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        return Image.open(io.BytesIO(data)).convert("RGB")
            except Exception:
                pass
            return None

        tasks = [fetch_image(alb.get("image", "")) for alb in albums[:total_tiles]]
        images = await asyncio.gather(*tasks)

        font_path = "/app/assets/font.ttf"
        if not os.path.exists(font_path):
            font_path = "/opt/dabot/assets/font.ttf"

        try:
            font_title = ImageFont.truetype(font_path, 15)
            font_artist = ImageFont.truetype(font_path, 13)
        except Exception:
            font_title = ImageFont.load_default()
            font_artist = ImageFont.load_default()

        for idx, alb in enumerate(albums[:total_tiles]):
            row = idx // size
            col = idx % size
            x = col * tile_size
            y = row * tile_size

            tile_img = images[idx] if idx < len(images) else None
            if tile_img:
                try:
                    resized = tile_img.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
                    canvas.paste(resized, (x, y))
                except Exception:
                    pass
            else:
                # Placeholder dark tile
                placeholder = Image.new("RGB", (tile_size, tile_size), color=(25, 25, 30))
                canvas.paste(placeholder, (x, y))

            # Overlay title gradient
            overlay = Image.new("RGBA", (tile_size, 65), color=(0, 0, 0, 190))
            canvas.paste(overlay, (x, y + tile_size - 65), mask=overlay)

            draw = ImageDraw.Draw(canvas)
            title = alb.get("name", "Desconocido")
            if len(title) > 28:
                title = title[:25] + "..."
            artist = alb.get("artist", "")
            if len(artist) > 30:
                artist = artist[:27] + "..."
            plays = f"{alb.get('playcount', 0)} scrobbles"

            draw.text((x + 10, y + tile_size - 58), title, fill=(255, 255, 255), font=font_title)
            draw.text((x + 10, y + tile_size - 38), f"{artist} · {plays}", fill=(180, 180, 180), font=font_artist)

        out = io.BytesIO()
        canvas.save(out, format="PNG", quality=92)
        out.seek(0)
        return out
