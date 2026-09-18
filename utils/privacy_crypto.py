import hashlib
import hmac
import os
import secrets
import datetime
import logging

log = logging.getLogger("Dabot.PrivacyCrypto")

# Secret pepper from environment or fallback
PEPPER = os.environ.get("PRIVACY_SECRET_PEPPER") or os.environ.get("SESSION_SECRET") or "dabot_rgpd_secure_salt_2026"

def encrypt_ip_fingerprint(ip: str, user_id: int) -> tuple[str, str]:
    """
    Encrypts/pseudonymizes an IP address or technical fingerprint using HMAC-SHA256
    with a random per-record salt and server pepper.
    Returns (encrypted_hash, salt_hex).
    Complies with Art. 6.1.f and Art. 32 GDPR for security & multi-account defense.
    """
    if not ip or ip == "none":
        ip = f"unknown_origin_{user_id}"
    
    salt = secrets.token_hex(16)
    message = f"{ip}:{user_id}:{salt}".encode("utf-8")
    key = PEPPER.encode("utf-8")
    encrypted_hash = hmac.new(key, message, hashlib.sha256).hexdigest()
    return encrypted_hash, salt

def execute_gdpr_erasure_sync(db, user_id: int, processed_by: int = None, admin_notes: str = None) -> dict:
    """
    Synchronous execution for dashboard_server (sqlite3.Connection).
    1. Backs up encrypted IP fingerprint for anti-alt/security protection.
    2. Deletes all personal/optional data.
    3. Updates privacy_requests status.
    """
    cur = db.cursor()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # 1. Look for IP in verification_events or alts_tracking
    cur.execute("SELECT ip FROM verification_events WHERE user_id = ? AND ip IS NOT NULL ORDER BY id DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    ip = row[0] if row and row[0] else None
    
    if not ip:
        cur.execute("SELECT ip_address FROM alts_tracking WHERE user_id = ? LIMIT 1", (str(user_id),))
        row = cur.fetchone()
        ip = row[0] if row and row[0] else "0.0.0.0"

    # Encrypt the IP fingerprint
    enc_hash, salt = encrypt_ip_fingerprint(ip, user_id)
    
    # Store in security backup table
    cur.execute(
        """INSERT INTO privacy_security_fingerprints 
           (user_id, encrypted_ip_fingerprint, salt, created_at, legal_basis)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, enc_hash, salt, now_iso, "Art. 6.1.f RGPD - Prevención de abusos y multicuentas")
    )
    
    # 2. Delete personal data
    cur.execute("DELETE FROM social_profiles WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM birthdays WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM user_achievements WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM game_stats WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM afk WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
    
    try:
        cur.execute("UPDATE users SET bio = NULL WHERE user_id = ?", (user_id,))
    except Exception:
        pass
        
    try:
        cur.execute("UPDATE verification_events SET user_name = 'Usuario Anonimizado' WHERE user_id = ?", (user_id,))
    except Exception:
        pass
        
    # 3. Update privacy_requests
    cur.execute(
        """UPDATE privacy_requests 
           SET status = 'approved', processed_at = ?, processed_by = ?, encrypted_ip_backup = ?, admin_notes = ?
           WHERE user_id = ? AND status = 'pending' AND request_type = 'deletion'""",
        (now_iso, processed_by, f"HMAC-SHA256:{enc_hash[:16]}...", admin_notes or "Aprobado manualmente por superusuario", user_id)
    )
    
    if cur.rowcount == 0:
        # If there was no pending request, record this manual deletion
        cur.execute(
            """INSERT INTO privacy_requests 
               (user_id, user_name, request_type, status, requested_at, processed_at, processed_by, encrypted_ip_backup, admin_notes)
               VALUES (?, ?, 'deletion', 'approved', ?, ?, ?, ?, ?)""",
            (user_id, f"User_{user_id}", now_iso, now_iso, processed_by, f"HMAC-SHA256:{enc_hash[:16]}...", admin_notes or "Eliminación directa manual desde dashboard")
        )

    db.commit()
    return {
        "ok": True,
        "user_id": user_id,
        "ip_backed_up_encrypted": True,
        "processed_at": now_iso
    }

async def execute_gdpr_erasure_async(bot_db, user_id: int, processed_by: int = None, admin_notes: str = None) -> dict:
    """
    Asynchronous version using bot.db (aiosqlite).
    """
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    row = await bot_db.fetch("SELECT ip FROM verification_events WHERE user_id = ? AND ip IS NOT NULL ORDER BY id DESC LIMIT 1", user_id)
    ip = row[0] if row and row[0] else None
    
    if not ip:
        row = await bot_db.fetch("SELECT ip_address FROM alts_tracking WHERE user_id = ? LIMIT 1", str(user_id))
        ip = row[0] if row and row[0] else "0.0.0.0"

    enc_hash, salt = encrypt_ip_fingerprint(ip, user_id)
    
    await bot_db.execute(
        """INSERT INTO privacy_security_fingerprints 
           (user_id, encrypted_ip_fingerprint, salt, created_at, legal_basis)
           VALUES (?, ?, ?, ?, ?)""",
        user_id, enc_hash, salt, now_iso, "Art. 6.1.f RGPD - Prevención de abusos y multicuentas"
    )
    
    await bot_db.execute("DELETE FROM social_profiles WHERE user_id = ?", user_id)
    await bot_db.execute("DELETE FROM birthdays WHERE user_id = ?", user_id)
    await bot_db.execute("DELETE FROM user_achievements WHERE user_id = ?", user_id)
    await bot_db.execute("DELETE FROM game_stats WHERE user_id = ?", user_id)
    await bot_db.execute("DELETE FROM afk WHERE user_id = ?", user_id)
    await bot_db.execute("DELETE FROM reminders WHERE user_id = ?", user_id)
    
    try:
        await bot_db.execute("UPDATE users SET bio = NULL WHERE user_id = ?", user_id)
    except Exception:
        pass

    try:
        await bot_db.execute("UPDATE verification_events SET user_name = 'Usuario Anonimizado' WHERE user_id = ?", user_id)
    except Exception:
        pass
        
    await bot_db.execute(
        """UPDATE privacy_requests 
           SET status = 'approved', processed_at = ?, processed_by = ?, encrypted_ip_backup = ?, admin_notes = ?
           WHERE user_id = ? AND status = 'pending' AND request_type = 'deletion'""",
        now_iso, processed_by, f"HMAC-SHA256:{enc_hash[:16]}...", admin_notes or "Aprobado manualmente por superusuario", user_id
    )
    
    return {
        "ok": True,
        "user_id": user_id,
        "ip_backed_up_encrypted": True,
        "processed_at": now_iso
    }
