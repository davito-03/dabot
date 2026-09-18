"""Detect VPN / proxy / Tor / iCloud Private Relay for web verification.

The visitor IP is taken from the TCP peer or Cloudflare's connecting-ip
(only when the peer is a trusted proxy). Client-supplied headers are ignored
on direct hits so they cannot fake an IP.
"""
from __future__ import annotations

import bisect
import ipaddress
import json
import logging
import os
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta

logger = logging.getLogger("Dabot.ProxyDetect")

IP_API_FIELDS = (
    "status,message,country,countryCode,regionName,city,isp,org,as,asname,"
    "proxy,hosting,mobile,query"
)
IP_API_URL = "http://ip-api.com/json/{ip}?fields=" + IP_API_FIELDS
RELAY_URL = "https://mask-api.icloud.com/egress-ip-ranges.csv"
CACHE_TTL_H = 24
RELAY_TTL_H = 12

VPN_KEYWORDS = (
    "vpn", "nordvpn", "nord vpn", "expressvpn", "surfshark", "mullvad",
    "cyberghost", "protonvpn", "proton vpn", "proton ag",
    "private internet access", "ipvanish", "windscribe", "tunnelbear",
    "hotspot shield", "hide.me", "hidemyass", "vyprvpn", "purevpn",
    "urban vpn", "hola vpn", "zenmate", "ivacy", "atlasvpn", "torguard",
    "private relay", "icloud relay", "icloud private",
    "cloudflare warp", "cloudflare 1.1.1.1", "1.1.1.1 warp",
    "opera vpn", "ultrasurf", "psiphon", "outline vpn", "tailscale exit",
    "m247", "datacamp limited", "packethub", "zscaler", "perimeter 81",
    "exit node", "anonymizer", "proxy service",
)
HOSTING_KEYWORDS = (
    "digitalocean", "linode", "vultr", "hetzner",
    "ovh sas", "ovh hosting", "contabo", "choopa", "colocrossing", "leaseweb",
    "scaleway", "hostinger", "ionos", "psychz", "frantech", "buyvm",
    "datacamp", "dedicated server", "vps hosting",
)
# ASNs used almost exclusively as VPN/proxy egress (not general ISPs).
VPN_ASNS = {
    9009, 212238, 60068, 136787, 209103, 208885, 393886, 206092, 202425,
    16276, 20473, 14061, 63949, 24940, 51167, 40676, 53667, 35916, 46844,
    62240, 207990, 51395, 200557, 35540, 197540, 212238,
}

_relay_v4: list[tuple[int, int]] = []
_relay_v6: list[tuple[int, int]] = []
_relay_loaded_at = 0.0
_relay_lock = threading.Lock()
_relay_fetching = False

INTEL_SCHEMA = """
CREATE TABLE IF NOT EXISTS ip_intel (
    ip TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL
)
"""


def _header(headers, *names) -> str:
    if not headers:
        return ""
    getter = headers.get if hasattr(headers, "get") else None
    if not getter:
        return ""
    for n in names:
        val = getter(n)
        if val:
            return str(val).strip()
    return ""


def _trusted_proxy(peer: str) -> bool:
    if not peer:
        return False
    try:
        addr = ipaddress.ip_address(peer.strip())
    except Exception:
        return False
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local)


def connecting_ip(headers, peer: str = "") -> str:
    """Real client IP. Headers only count if the TCP peer is a trusted proxy."""
    peer = (peer or "").split(",")[0].strip()
    if _trusted_proxy(peer):
        for key in (
            "cf-connecting-ip", "CF-Connecting-IP",
            "true-client-ip", "True-Client-IP",
            "x-real-ip", "X-Real-IP",
        ):
            val = _header(headers, key)
            if val:
                cand = val.split(",")[0].strip()
                try:
                    ipaddress.ip_address(cand)
                    return cand
                except Exception:
                    continue
    return peer


def _parse_asn(as_field: str) -> int | None:
    m = re.search(r"AS(\d+)", as_field or "", re.I)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _blob(*parts) -> str:
    return " ".join(str(p or "") for p in parts).lower()


def _keyword_hit(text: str, words: tuple[str, ...]) -> str:
    for w in words:
        if w in text:
            return w
    return ""


def _data_dir() -> str:
    db = os.environ.get("DATABASE_PATH") or "dabot.db"
    return os.path.dirname(os.path.abspath(db)) or "."


def _relay_csv_path() -> str:
    return os.path.join(_data_dir(), "icloud_relay_cidrs.csv")


def _relay_cache_path() -> str:
    return os.path.join(_data_dir(), "icloud_relay_ranges.json")


def _merge_ranges(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not pairs:
        return []
    pairs = sorted(pairs)
    out = [list(pairs[0])]
    for s, e in pairs[1:]:
        if s <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(a, b) for a, b in out]


def _parse_relay_csv(raw: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    v4, v6 = [], []
    for line in (raw or "").splitlines():
        tok = (line.split(",") or [""])[0].strip()
        if not tok or tok.startswith("#"):
            continue
        try:
            net = ipaddress.ip_network(tok, strict=False)
        except Exception:
            continue
        start = int(net.network_address)
        end = int(net.broadcast_address)
        (v4 if net.version == 4 else v6).append((start, end))
    return _merge_ranges(v4), _merge_ranges(v6)


def _save_relay_cache(v4, v6) -> None:
    try:
        os.makedirs(_data_dir(), exist_ok=True)
        with open(_relay_cache_path(), "w", encoding="utf-8") as f:
            json.dump({"v4": v4, "v6": v6, "ts": time.time()}, f)
    except Exception as e:
        logger.warning("relay cache write: %s", e)


def _load_relay_cache_file() -> bool:
    global _relay_v4, _relay_v6, _relay_loaded_at
    path = _relay_cache_path()
    try:
        if not os.path.isfile(path):
            return False
        if (time.time() - os.path.getmtime(path)) > RELAY_TTL_H * 3600:
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _relay_v4 = [tuple(x) for x in (data.get("v4") or [])]
        _relay_v6 = [tuple(x) for x in (data.get("v6") or [])]
        _relay_loaded_at = time.time()
        return True
    except Exception:
        return False


def _fetch_relay_csv() -> None:
    global _relay_v4, _relay_v6, _relay_loaded_at, _relay_fetching
    try:
        req = urllib.request.Request(
            RELAY_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Dabot/1.0; +https://dabot.davito.es)",
                "Accept": "text/csv,text/plain,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", "ignore")
        try:
            os.makedirs(_data_dir(), exist_ok=True)
            with open(_relay_csv_path(), "w", encoding="utf-8") as f:
                f.write(raw)
        except Exception:
            pass
        v4, v6 = _parse_relay_csv(raw)
        with _relay_lock:
            _relay_v4, _relay_v6 = v4, v6
            _relay_loaded_at = time.time()
        _save_relay_cache(v4, v6)
        logger.info("icloud private relay ranges loaded v4=%s v6=%s", len(v4), len(v6))
    except Exception as e:
        logger.warning("icloud relay list fetch failed: %s", e)
        csv_path = _relay_csv_path()
        try:
            if os.path.isfile(csv_path):
                with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
                    v4, v6 = _parse_relay_csv(f.read())
                with _relay_lock:
                    _relay_v4, _relay_v6 = v4, v6
                    _relay_loaded_at = time.time()
        except Exception:
            pass
    finally:
        _relay_fetching = False


def warmup() -> None:
    """Load Private Relay ranges in the background so the first verify is not slow."""
    global _relay_fetching
    if _load_relay_cache_file():
        return
    with _relay_lock:
        if _relay_fetching:
            return
        _relay_fetching = True
    threading.Thread(target=_fetch_relay_csv, name="icloud-relay", daemon=True).start()


def _in_ranges(ranges: list[tuple[int, int]], n: int) -> bool:
    if not ranges:
        return False
    i = bisect.bisect_right(ranges, (n, 2**128)) - 1
    return i >= 0 and ranges[i][0] <= n <= ranges[i][1]


def _in_relay(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except Exception:
        return False
    if not _relay_v4 and not _relay_v6:
        warmup()
    if not _relay_v4 and not _relay_v6:
        return False
    n = int(addr)
    return _in_ranges(_relay_v6 if addr.version == 6 else _relay_v4, n)


def _ensure_intel(conn) -> None:
    try:
        conn.execute(INTEL_SCHEMA)
        conn.commit()
    except Exception:
        pass


def lookup_ip(conn, ip: str) -> dict:
    """Cached ip-api.com payload. Empty dict on failure (fail-open)."""
    ip = (ip or "").strip()
    if not ip:
        return {}
    try:
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            return {"status": "skip", "query": ip, "private": True}
    except Exception:
        return {}
    _ensure_intel(conn)
    cur = conn.cursor()
    try:
        cur.execute("SELECT payload, fetched_at FROM ip_intel WHERE ip = ?", (ip,))
        row = cur.fetchone()
        if row:
            payload = row[0] if not hasattr(row, "keys") else row["payload"]
            fetched = row[1] if not hasattr(row, "keys") else row["fetched_at"]
            try:
                age = datetime.utcnow() - datetime.fromisoformat(str(fetched))
                if age < timedelta(hours=CACHE_TTL_H):
                    data = json.loads(payload)
                    if isinstance(data, dict):
                        return data
            except Exception:
                pass
    except Exception:
        pass
    data = {}
    try:
        url = IP_API_URL.format(ip=ip)
        req = urllib.request.Request(url, headers={"User-Agent": "Dabot/verify (davito.es)"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore") or "{}")
        if not isinstance(data, dict):
            data = {}
    except Exception as e:
        logger.warning("ip-api lookup failed for %s: %s", ip, e)
        data = {}
    if data:
        try:
            cur.execute(
                """INSERT INTO ip_intel (ip, payload, fetched_at) VALUES (?, ?, ?)
                   ON CONFLICT(ip) DO UPDATE SET payload = excluded.payload, fetched_at = excluded.fetched_at""",
                (ip, json.dumps(data, ensure_ascii=False), datetime.utcnow().isoformat()),
            )
            conn.commit()
        except Exception:
            pass
    return data


def _public_ips(values) -> list[str]:
    out = []
    for raw in values or []:
        s = str(raw or "").strip().split("%")[0]
        if not s or s.endswith(".local"):
            continue
        try:
            addr = ipaddress.ip_address(s)
        except Exception:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast:
            continue
        out.append(str(addr))
    # unique, cap
    seen = set()
    uniq = []
    for ip in out:
        if ip not in seen:
            seen.add(ip)
            uniq.append(ip)
    return uniq[:8]


def inspect(
    conn,
    ip: str,
    *,
    headers=None,
    webrtc_ips=None,
    timezone: str = "",
) -> dict:
    """Return network intel. blocked=True means the user must disable VPN/proxy."""
    ip = (ip or "").strip()
    kinds: list[str] = []
    reasons: list[str] = []
    cf_cc = (_header(headers, "cf-ipcountry", "CF-IPCountry") or "").upper()
    cf_city = _header(headers, "cf-ipcity", "CF-IPCity")
    lookup = lookup_ip(conn, ip) if ip else {}
    isp = str(lookup.get("isp") or "")
    org = str(lookup.get("org") or "")
    as_field = str(lookup.get("as") or lookup.get("asname") or "")
    asn = _parse_asn(as_field)
    city = str(lookup.get("city") or cf_city or "")
    country = str(lookup.get("countryCode") or lookup.get("country") or cf_cc or "")
    text = _blob(isp, org, as_field)

    if cf_cc == "T1":
        kinds.append("tor")
        reasons.append("Salida Tor (Cloudflare T1)")

    if ip and _in_relay(ip):
        kinds.append("icloud_relay")
        reasons.append("iCloud Private Relay (rango Apple)")

    kw = _keyword_hit(text, VPN_KEYWORDS)
    if kw:
        kinds.append("vpn")
        reasons.append(f"Proveedor VPN/proxy ({isp or org or kw})")

    if "private relay" in text or ("icloud" in text and "relay" in text):
        if "icloud_relay" not in kinds:
            kinds.append("icloud_relay")
            reasons.append("iCloud Private Relay (proveedor)")

    if lookup.get("proxy") is True:
        kinds.append("proxy")
        reasons.append("IP marcada como proxy")
    if lookup.get("hosting") is True:
        kinds.append("datacenter")
        reasons.append("IP de datacenter / hosting")

    if asn and asn in VPN_ASNS:
        kinds.append("vpn")
        reasons.append(f"ASN de VPN/hosting {as_field or asn}")

    hk = _keyword_hit(text, HOSTING_KEYWORDS)
    if hk and "datacenter" not in kinds and lookup.get("mobile") is not True:
        kinds.append("datacenter")
        reasons.append(f"Hosting ({isp or hk})")

    public_rtc = _public_ips(webrtc_ips)
    for wip in public_rtc:
        if wip == ip:
            continue
        extra = lookup_ip(conn, wip)
        wtext = _blob(extra.get("isp"), extra.get("org"), extra.get("as"))
        if extra.get("proxy") or extra.get("hosting") or _keyword_hit(wtext, VPN_KEYWORDS) or _in_relay(wip):
            kinds.append("webrtc_vpn")
            reasons.append("WebRTC revela otra IP de VPN/proxy")
            if not isp:
                isp = str(extra.get("isp") or isp)
            break

    def uniq(seq):
        s, o = set(), []
        for x in seq:
            if x and x not in s:
                s.add(x)
                o.append(x)
        return o

    kinds = uniq(kinds)
    reasons = uniq(reasons)
    return {
        "blocked": bool(kinds),
        "kinds": kinds,
        "reasons": reasons,
        "ip": ip,
        "isp": isp,
        "org": org,
        "asn": as_field,
        "asn_num": asn,
        "country": country,
        "city": city,
        "hosting": bool(lookup.get("hosting")),
        "proxy_flag": bool(lookup.get("proxy")),
        "mobile": bool(lookup.get("mobile")),
        "cf_country": cf_cc,
        "webrtc": public_rtc,
        "timezone": timezone or "",
        "source": "ip-api" if lookup.get("status") == "success" else ("skip" if lookup.get("private") else "local"),
    }


def public_payload(intel: dict, *, show_full_ip: bool = False) -> dict:
    """What we send to the verifying browser. No raw IPs."""
    from utils.alt_intel import redact_ips
    kinds = intel.get("kinds") or []
    return {
        "blocked": bool(intel.get("blocked")),
        "kinds": kinds,
        "reasons": [redact_ips(r) for r in (intel.get("reasons") or [])],
        "kind": kinds[0] if kinds else "",
        "isp": "",
        "country": "",
        "city": "",
    }
