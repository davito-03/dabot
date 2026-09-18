"""Hijacked-account / giveaway-scam detector.

The 2024–2026 wave of compromised Discord tokens posts a fake MrBeast (or
Nitro / Steam) giveaway *image* plus a phishing URL. Text-only automod misses
it. This module scores the message, hashes the image, and compares it to a
shared memory of known scam pictures.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse

from PIL import Image

SAFE_HOSTS = {
    "discord.com", "discordapp.com", "discord.gg", "discordapp.net",
    "cdn.discordapp.com", "media.discordapp.net",
    "youtube.com", "youtu.be", "m.youtube.com", "www.youtube.com",
    "twitter.com", "x.com", "instagram.com", "tiktok.com", "spotify.com",
    "twitch.tv", "github.com", "davito.es", "dabot.davito.es",
    "google.com", "wikipedia.org", "reddit.com", "tenor.com", "giphy.com",
    "steamcommunity.com", "store.steampowered.com",
}

# Hosts / paths that almost never appear in a legitimate Nitro/MrBeast post.
PHISH_HOST_RE = re.compile(
    r"("
    r"disc[o0]rd[\-.]?(nitro|gift|nltro|premium)|"
    r"dlscord|discrod|discorcl|discorclapp|"
    r"stea[mn]community|steamcommmunity|steamcomrnunity|steancommunity|"
    r"nitro[\-.]?(gift|free|discord)|"
    r"free[\-.]?nitro|gift[\-.]?nitro|"
    r"mr[\-.]?bea?st[\-.]?(gift|nitro|give)|"
    r"claim[\-.]?(nitro|prize|gift)"
    r")",
    re.I,
)

SHORTENER_HOSTS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "cutt.ly",
    "rb.gy", "rebrand.ly", "shorturl.at", "s.id", "tiny.cc", "b.link",
}

CELEBRITY_RE = re.compile(
    r"\b(mr\.?\s*bea?st|mister\s*beast|mrbeas+t|ishowspeed|kai\s*cenat|"
    r"xqc|ninja\b|pewdiepie|karmaland)\b",
    re.I,
)

GIVEAWAY_RE = re.compile(
    r"\b(giveaway|sorteo|regalo|nitro|steam\s*gift|gift\s*card|giftcard|"
    r"free\s*nitro|discord\s*nitro|3\s*months|1\s*year|claim\s*(now|here)|"
    r"click\s*(the|this)?\s*link|ending\s*soon|from\s*my\s*(last\s*)?video|"
    r"i('?m| am)\s*giving|últim[oa]\s*en\s*salir|ultimo\s*en\s*salir|"
    r"100,?000|1,?000,?000|iphone\s*1[456]|airpods|ps5)\b",
    re.I,
)

CLAIM_RE = re.compile(
    r"(click|pulsa|entra|claim|reclama|coge|cógele).{0,24}(link|enlace|aqui|aquí|here)",
    re.I,
)

URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", re.I)
INVITE_OBFUSCATED_RE = re.compile(
    r"(discord\s*[\.\[\(]*\s*(gg|com)|dsc\.gg|discord\.gift)",
    re.I,
)

# Mixed-script / homoglyph bait inside a supposed Discord URL.
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")


def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch if unicodedata.category(ch) != "Mn" else "" for ch in text)
    return text.lower()


def zalgo_ratio(text: str) -> float:
    if not text:
        return 0.0
    comb = sum(1 for c in text if unicodedata.combining(c))
    return comb / max(len(text), 1)


def extract_urls(*parts: str) -> list[str]:
    found: list[str] = []
    for part in parts:
        if not part:
            continue
        found.extend(URL_RE.findall(part))
    # de-dupe preserving order
    out, seen = [], set()
    for u in found:
        u = u.rstrip(").,]}>\"'")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def host_of(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def is_safe_url(url: str) -> bool:
    host = host_of(url)
    if not host:
        return False
    if host in SAFE_HOSTS:
        return True
    return any(host.endswith("." + s) for s in SAFE_HOSTS)


def url_is_phishy(url: str) -> tuple[int, str | None]:
    host = host_of(url)
    path = ""
    try:
        path = (urlparse(url).path or "") + "?" + (urlparse(url).query or "")
    except Exception:
        pass
    blob = f"{host}{path}"
    if CYRILLIC_RE.search(url) and ("discord" in normalize(url) or "nitro" in normalize(url)):
        return 50, "url_homoglyph"
    if PHISH_HOST_RE.search(blob):
        return 55, "url_phishing"
    if host in SHORTENER_HOSTS:
        return 22, "url_shortener"
    if host and not is_safe_url(url) and any(k in blob.lower() for k in ("nitro", "gift", "steam", "mrbeast", "claim")):
        return 40, "url_bait_host"
    return 0, None


def dhash(image: Image.Image, size: int = 16) -> str:
    """Difference hash; stable across Discord recompression of the same PNG."""
    gray = image.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    bits = []
    width = size + 1
    for y in range(size):
        row = pixels[y * width:(y + 1) * width]
        bits.extend("1" if row[x] > row[x + 1] else "0" for x in range(size))
    value = int("".join(bits), 2)
    return f"{value:0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except Exception:
        return 64


def content_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def score_text(text: str) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0
    if not text:
        return 0, reasons
    n = normalize(text)
    if CELEBRITY_RE.search(n):
        score += 28
        reasons.append("celebridad_giveaway")
    if GIVEAWAY_RE.search(n):
        score += 24
        reasons.append("lenguaje_sorteo")
    if CLAIM_RE.search(n):
        score += 18
        reasons.append("cta_reclamar")
    if INVITE_OBFUSCATED_RE.search(n) and "nitro" in n:
        score += 20
        reasons.append("invite_nitro")
    if zalgo_ratio(text) > 0.25:
        score += 12
        reasons.append("zalgo")
    # @everyone / @here in a giveaway pitch
    if ("@everyone" in n or "@here" in n) and score:
        score += 12
        reasons.append("ping_masivo")
    return score, reasons


def score_urls(urls: list[str]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    risky = 0
    for url in urls:
        pts, why = url_is_phishy(url)
        if pts:
            score += pts
            risky += 1
            if why and why not in reasons:
                reasons.append(why)
        elif is_safe_url(url):
            # Official YouTube/Twitter links are usually *not* the malware kit.
            score -= 8
            reasons.append("url_legitima")
    if risky >= 2:
        score += 10
        reasons.append("varios_enlaces_raros")
    if not risky:
        return 0, []
    return max(0, score), reasons


def combine_score(*, text_score: int, url_score: int, image: bool, known_hash: bool,
                  silent_member: bool, everyone: bool, staff: bool) -> tuple[int, list[str]]:
    """Final 0–100 score. Need bait + delivery so talking about MrBeast is safe."""
    extra: list[str] = []
    score = text_score + url_score
    delivery = url_score >= 20 or known_hash
    bait = text_score >= 20 or known_hash
    if image and delivery:
        score += 18
        extra.append("imagen_mas_enlace")
    if known_hash:
        score += 45
        extra.append("imagen_conocida")
    if silent_member and image and (delivery or bait):
        score += 16
        extra.append("cuenta_callada")
    if everyone and (delivery or bait):
        score += 10
        extra.append("everyone")
    if staff and score >= 40:
        score += 8
        extra.append("cuenta_staff")  # stolen admin tokens are the worst case
    # Talking about MrBeast with a YouTube link and no phishing host → clamp
    if url_score == 0 and not known_hash and not delivery:
        score = min(score, 35)
    return min(100, max(0, score)), extra


def verdict(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 62:
        return "high"
    if score >= 45:
        return "medium"
    return "low"
