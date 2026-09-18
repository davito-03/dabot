"""Per-guild link filter: whitelist, blacklist, tracking vs referral."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\)\]\"']+",
    re.IGNORECASE,
)
MD_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)", re.IGNORECASE)

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "utm_reader", "utm_referrer",
    "fbclid", "gclid", "gbraid", "wbraid", "dclid", "msclkid",
    "twclid", "ttclid", "yclid", "li_fat_id", "rdt_cid", "sclid",
    "mc_cid", "mc_eid", "igshid", "_hsenc", "_hsmi", "vero_id",
    "gad_source", "gad_campaignid", "gclsrc", "gad",
    "spm", "scm", "clickid", "click_id", "campaignid", "adid", "adgroupid",
    "pk_campaign", "pk_kwd", "pk_source", "mtm_campaign", "mtm_kwd",
    "oly_anon_id", "oly_enc_id", "mc_eid",
    "si", "feature", "ref_src", "ref_url", "ncid", "icid",
    "fb_action_ids", "fb_action_types", "fb_source",
}

REFERRAL_PARAMS = {
    "ref", "referral", "referrer", "affiliate", "aff", "affid", "aff_id",
    "partner", "partnerid", "partner_id", "via", "promo", "coupon",
    "tag", "ascsubtag", "linkcode", "linkid", "camp",
    "invite", "invitedby", "refer", "referer", "referred_by",
}

ALWAYS_ALLOW = {
    "discord.com", "discordapp.com", "discord.gg", "discordcdn.com",
    "media.discordapp.net", "cdn.discordapp.com",
}

ACTIONS = ("delete", "warn", "timeout", "ban")
ACTION_RANK = {"delete": 1, "warn": 2, "timeout": 3, "ban": 4}


def _clean_url(raw: str) -> str:
    text = unquote(raw or "").strip().rstrip(".,;!?")
    text = text.rstrip(")")
    if text.lower().startswith("www."):
        text = "https://" + text
    return text


def extract_urls(text: str) -> list[str]:
    found: list[str] = []
    blob = text or ""
    for m in MD_LINK_RE.finditer(blob):
        found.append(_clean_url(m.group(1)))
    for m in URL_RE.finditer(blob):
        found.append(_clean_url(m.group(0)))
    # unique, keep order
    out, seen = [], set()
    for u in found:
        key = u.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def normalize_host(host: str) -> str:
    host = (host or "").strip().lower().strip(".")
    if ":" in host and not host.count(":") > 1:
        host = host.split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    try:
        host = host.encode("idna").decode("ascii")
    except Exception:
        pass
    return host


def host_of(url: str) -> str:
    parsed = urlparse(url if "://" in url else "https://" + url)
    return normalize_host(parsed.hostname or parsed.netloc or "")


def domain_matches(host: str, pattern: str) -> bool:
    host = normalize_host(host)
    pattern = normalize_host(pattern)
    if not host or not pattern:
        return False
    return host == pattern or host.endswith("." + pattern)


def query_names(url: str) -> set[str]:
    parsed = urlparse(url if "://" in url else "https://" + url)
    names = set()
    for key in parse_qs(parsed.query, keep_blank_values=True):
        names.add(key.lower())
    if parsed.fragment and "=" in parsed.fragment:
        for key in parse_qs(parsed.fragment, keep_blank_values=True):
            names.add(key.lower())
    return names


def classify_params(url: str, extra_tracking: list[str] | None = None) -> tuple[set[str], set[str]]:
    names = query_names(url)
    tracking = set(TRACKING_PARAMS)
    for extra in extra_tracking or []:
        extra = str(extra).strip().lower()
        if extra:
            tracking.add(extra)
    hit_track = {n for n in names if n in tracking}
    hit_ref = {n for n in names if n in REFERRAL_PARAMS}
    return hit_track, hit_ref


def _norm_list(items) -> list[str]:
    out = []
    for item in items or []:
        text = str(item or "").strip().lower()
        text = text.replace("https://", "").replace("http://", "").split("/")[0]
        text = normalize_host(text)
        if text:
            out.append(text)
    return out


def _blocked_rules(cfg: dict) -> list[dict]:
    rules = []
    raw_rules = cfg.get("blocked") or cfg.get("blacklist") or []
    for item in raw_rules:
        if isinstance(item, str):
            host = normalize_host(item.replace("https://", "").replace("http://", "").split("/")[0])
            if host:
                rules.append({"domain": host, "action": "delete"})
            continue
        if not isinstance(item, dict):
            continue
        host = normalize_host(str(item.get("domain") or item.get("host") or "").split("/")[0])
        action = str(item.get("action") or "delete").lower().strip()
        if action not in ACTION_RANK:
            action = "delete"
        if host:
            rules.append({"domain": host, "action": action})
    return rules


def strongest(action_a: str | None, action_b: str | None) -> str | None:
    if not action_a:
        return action_b
    if not action_b:
        return action_a
    return action_a if ACTION_RANK.get(action_a, 0) >= ACTION_RANK.get(action_b, 0) else action_b


def inspect_url(url: str, cfg: dict, *, premium: bool = False) -> dict | None:
    """Return a hit dict if the URL should be actioned, else None."""
    host = host_of(url)
    if not host:
        return None
    whitelist = _norm_list(cfg.get("whitelist") or cfg.get("allow") or [])
    blocked = _blocked_rules(cfg)
    default_action = str(cfg.get("default_action") or "delete").lower()
    if default_action not in ACTION_RANK:
        default_action = "delete"
    block_all = bool(cfg.get("block_all") or cfg.get("whitelist_only"))

    tracking_cfg = cfg.get("tracking") or {}
    tracking_on = bool(premium and tracking_cfg.get("enabled"))
    extra_params = tracking_cfg.get("params") or []
    hit_track, hit_ref = classify_params(url, extra_params)
    allow_referral = tracking_cfg.get("allow_referral", True)
    referral_domains = _norm_list(tracking_cfg.get("referral_domains") or [])
    tracking_action = str(tracking_cfg.get("action") or "delete").lower()
    if tracking_action not in ACTION_RANK:
        tracking_action = "delete"

    is_whitelisted = any(domain_matches(host, p) for p in whitelist)
    is_always = any(domain_matches(host, p) for p in ALWAYS_ALLOW)
    rule = next((r for r in blocked if domain_matches(host, r["domain"])), None)

    clean_referral = False
    if allow_referral and hit_ref and not hit_track:
        if not referral_domains or any(domain_matches(host, p) for p in referral_domains):
            clean_referral = True

    def tracking_hit():
        if not tracking_on or not hit_track or clean_referral:
            return None
        return {
            "action": tracking_action,
            "reason": "tracking",
            "domain": host,
            "url": url,
            "params": sorted(hit_track),
        }

    if rule:
        # explicit block wins, even over whitelist
        return {
            "action": rule["action"],
            "reason": "blacklist",
            "domain": host,
            "url": url,
            "matched": rule["domain"],
        }

    if is_whitelisted or is_always:
        return tracking_hit()

    if block_all:
        return {
            "action": default_action,
            "reason": "not_whitelisted",
            "domain": host,
            "url": url,
        }

    return tracking_hit()


def inspect_text(text: str, cfg: dict, *, premium: bool = False) -> dict | None:
    if not cfg or not cfg.get("enabled"):
        return None
    hit = None
    for url in extract_urls(text or ""):
        current = inspect_url(url, cfg, premium=premium)
        if not current:
            continue
        if hit is None or ACTION_RANK.get(current["action"], 0) > ACTION_RANK.get(hit["action"], 0):
            hit = current
    return hit
