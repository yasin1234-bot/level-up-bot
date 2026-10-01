# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Web Dashboard + Key Auth System
Embedded Async Web Server (aiohttp)
"""

import asyncio
import json
import os
import re
import time
import secrets
from typing import Dict, List, Any, Optional
from aiohttp import web

# ==================== CONFIG ====================
MASTER_PASSWORD = "YASIN2026"
KEYS_FILE = "keys.json"
SESSIONS_FILE = "sessions.json"
SAVED_ACCOUNTS_FILE = "admin_saved_accounts.json"
COOKIE_NAME = "sexymods_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days cookie lifetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ==================== ADMIN SAVED ACCOUNTS STORE ====================
class SavedAccountsStore:
    def __init__(self, path: str):
        self.path = path
        self.accounts: List[Dict[str, Any]] = []
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.accounts = data
                    elif isinstance(data, dict):
                        self.accounts = list(data.values())
            except Exception:
                self.accounts = []

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.accounts, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def _find_index_by_key(self, auth_type: str, identifier: str) -> int:
        for i, acc in enumerate(self.accounts):
            if acc.get("auth_type") != auth_type:
                continue
            if auth_type == "guest" and str(acc.get("input_uid", "")) == str(identifier):
                return i
            if auth_type == "token" and str(acc.get("access_token", "")) == str(identifier):
                return i
        return -1

    def add_or_update(self, entry: Dict[str, Any], owner_key: str = "") -> bool:
        auth_type = entry.get("auth_type", "guest")
        if auth_type == "guest":
            identifier = entry.get("input_uid", "")
        else:
            identifier = entry.get("access_token", "")

        idx = self._find_index_by_key(auth_type, identifier)
        if idx >= 0:
            existing = self.accounts[idx]
            existing.update({
                "nickname": entry.get("nickname", existing.get("nickname", "")),
                "region": entry.get("region", existing.get("region", "")),
                "level": entry.get("level", existing.get("level", 1)),
                "exp": entry.get("exp", existing.get("exp", 0)),
                "real_account_id": entry.get("real_account_id", existing.get("real_account_id", "")),
                "input_uid": entry.get("input_uid", existing.get("input_uid", "")),
                "input_password": entry.get("input_password", existing.get("input_password", "")),
                "access_token": entry.get("access_token", existing.get("access_token", "")),
                "last_online": time.time(),
                "updated_count": int(existing.get("updated_count", 1)) + 1,
                "online": True,
                "owner_key": owner_key or existing.get("owner_key", ""),
            })
            self.save()
            return False
        else:
            entry["created_at"] = time.time()
            entry["last_online"] = time.time()
            entry["updated_count"] = 1
            entry["online"] = True
            entry["owner_key"] = owner_key or ""
            self.accounts.append(entry)
            self.save()
            return True

    def set_online_status(self, real_account_id: str, online: bool):
        changed = False
        for acc in self.accounts:
            if str(acc.get("real_account_id", "")) == str(real_account_id):
                if acc.get("online") != online:
                    acc["online"] = online
                    changed = True
                if online:
                    acc["last_online"] = time.time()
        if changed:
            self.save()

    def set_online_by_identifier(self, auth_type: str, identifier: str, online: bool):
        idx = self._find_index_by_key(auth_type, str(identifier))
        if idx >= 0:
            self.accounts[idx]["online"] = online
            if online:
                self.accounts[idx]["last_online"] = time.time()
            self.save()

    def set_offline_by_key(self, owner_key: str) -> int:
        if not owner_key:
            return 0
        changed = 0
        for acc in self.accounts:
            if str(acc.get("owner_key", "")) == str(owner_key) and acc.get("online"):
                acc["online"] = False
                changed += 1
        if changed:
            self.save()
        return changed

    def delete(self, real_account_id: str) -> bool:
        before = len(self.accounts)
        self.accounts = [
            a for a in self.accounts
            if str(a.get("real_account_id", "")) != str(real_account_id)
        ]
        if len(self.accounts) != before:
            self.save()
            return True
        return False

    def list_all(self) -> List[Dict[str, Any]]:
        return sorted(self.accounts, key=lambda x: x.get("last_online", 0), reverse=True)


saved_accounts_store = SavedAccountsStore(SAVED_ACCOUNTS_FILE)


# ==================== KEY STORE ====================
class KeyStore:
    def __init__(self, path: str):
        self.path = path
        self.keys: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.keys = data
            except Exception:
                self.keys = {}

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.keys, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def generate(self, user_name: str, days: int, hours: int, minutes: int,
                 custom_key: Optional[str] = None) -> Dict[str, Any]:
        duration = (max(0, days) * 86400) + (max(0, hours) * 3600) + (max(0, minutes) * 60)
        if duration <= 0:
            duration = 60

        if custom_key and str(custom_key).strip():
            key = str(custom_key).strip().upper()
            is_custom = True
        else:
            clean_name = "".join(c for c in (user_name or "USER") if c.isalnum()).upper()
            clean_name = clean_name[:16] or "USER"
            key = f"{clean_name}-" + secrets.token_hex(4).upper()
            is_custom = False

        entry = {
            "key": key,
            "user_name": user_name or "User",
            "days": days,
            "hours": hours,
            "minutes": minutes,
            "duration_sec": duration,
            "created_at": time.time(),
            "expires_at": None,
            "revoked": False,
            "bound_session": None,
            "used_at": None,
            "custom": is_custom,
        }
        self.keys[key] = entry
        self.save()
        return entry

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self.keys.get(key)

    def exists(self, key: str) -> bool:
        return key in self.keys

    def revoke(self, key: str):
        if key in self.keys:
            self.keys[key]["revoked"] = True
            self.keys[key]["bound_session"] = None
            self.save()

    def delete(self, key: str):
        if key in self.keys:
            del self.keys[key]
            self.save()

    def is_expired(self, key: str) -> bool:
        e = self.keys.get(key)
        if not e:
            return True
        exp = e.get("expires_at")
        if exp is None:
            return False
        return time.time() > exp

    def is_usable(self, key: str) -> bool:
        e = self.keys.get(key)
        if not e:
            return False
        if e.get("revoked"):
            return False
        exp = e.get("expires_at")
        if exp is not None and time.time() > exp:
            return False
        return True

    def is_session_alive(self, key: str) -> bool:
        e = self.keys.get(key)
        if not e:
            return False
        if e.get("revoked"):
            return False
        exp = e.get("expires_at")
        if exp is not None and time.time() > exp:
            return False
        if e.get("bound_session"):
            return True
        return False


key_store = KeyStore(KEYS_FILE)


# ==================== SESSION STORE ====================
class SessionStore:
    def __init__(self, path: str):
        self.path = path
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.sessions = data
            except Exception:
                self.sessions = {}

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.sessions, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def create(self, key: str) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions[token] = {
            "key": key,
            "created_at": time.time(),
            "last_seen": time.time(),
        }
        self.save()
        return token

    def get(self, token: str) -> Optional[Dict[str, Any]]:
        return self.sessions.get(token)

    def touch(self, token: str):
        if token in self.sessions:
            self.sessions[token]["last_seen"] = time.time()

    def destroy(self, token: str):
        if token in self.sessions:
            del self.sessions[token]
            self.save()

    def destroy_by_key(self, key: str):
        dead = [t for t, s in self.sessions.items() if s.get("key") == key]
        for t in dead:
            self.sessions.pop(t, None)
        if dead:
            self.save()

    def cleanup_expired(self):
        dead = []
        for tok, s in self.sessions.items():
            k = s.get("key")
            e = key_store.get(k)
            if not e:
                dead.append(tok); continue
            if e.get("revoked"):
                dead.append(tok); continue
            exp = e.get("expires_at")
            if exp is not None and time.time() > exp:
                dead.append(tok); continue
        for tok in dead:
            self.sessions.pop(tok, None)
        if dead:
            self.save()


session_store = SessionStore(SESSIONS_FILE)


# ==================== BOT STATE ====================
class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 3000
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        self.account_targets: Dict[str, int] = {}
        self.account_owners: Dict[str, str] = {}

    _UID_RE = re.compile(r'\b(\d{6,})\b')

    def log(self, message: str, level: str = "info", uid: Optional[str] = None,
            owner_key: Optional[str] = None):
        resolved_owner = owner_key or ""
        if not resolved_owner and uid:
            try:
                resolved_owner = self.get_owner(str(uid))
            except Exception:
                resolved_owner = ""
        if not resolved_owner and message:
            try:
                candidates = self._UID_RE.findall(message)
                for c in candidates:
                    o = self.get_owner(str(c))
                    if o:
                        resolved_owner = o
                        break
                if not resolved_owner:
                    tok_matches = re.findall(r'tok_[A-Za-z0-9_\-]+', message)
                    for t in tok_matches:
                        o = self.get_owner(t)
                        if o:
                            resolved_owner = o
                            break
            except Exception:
                resolved_owner = ""

        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "uid": uid,
            "owner_key": resolved_owner,
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def set_owner(self, alias: str, owner_key: str):
        if alias and owner_key:
            self.account_owners[str(alias)] = owner_key

    def get_owner(self, alias: str) -> str:
        if not alias:
            return ""
        alias = str(alias)
        if alias in self.account_owners:
            return self.account_owners[alias]
        cred = self.account_credentials.get(alias)
        if cred:
            for k in (
                str(cred.get("account_id", "")),
                str(cred.get("auth_uid", "")),
                f"tok_{cred.get('auth_token','')[:10]}" if cred.get("auth_token") else "",
                f"tok_{cred.get('auth_token','')[:20]}" if cred.get("auth_token") else "",
            ):
                if k and k in self.account_owners:
                    return self.account_owners[k]
        for cred_alias, c in self.account_credentials.items():
            try:
                if str(c.get("account_id", "")) == alias \
                   or str(c.get("auth_uid", "")) == alias \
                   or (c.get("auth_token") and alias == f"tok_{c['auth_token'][:10]}") \
                   or (c.get("auth_token") and alias == f"tok_{c['auth_token'][:20]}"):
                    for k in (
                        str(c.get("account_id", "")),
                        str(c.get("auth_uid", "")),
                        f"tok_{c.get('auth_token','')[:10]}" if c.get("auth_token") else "",
                        f"tok_{c.get('auth_token','')[:20]}" if c.get("auth_token") else "",
                    ):
                        if k and k in self.account_owners:
                            return self.account_owners[k]
            except Exception:
                continue
        return ""

    def get_all_owners(self, *aliases: str) -> List[str]:
        owners: List[str] = []
        for a in aliases:
            o = self.get_owner(str(a))
            if o and o not in owners:
                owners.append(o)
        return owners

    def is_owner_key_expired(self, *aliases: str) -> bool:
        try:
            owners = self.get_all_owners(*aliases)
            if not owners:
                for a in aliases:
                    if a and key_store.exists(str(a)):
                        owners.append(str(a))
            if not owners:
                return False

            for owner_key in owners:
                e = key_store.get(owner_key)
                if not e:
                    return True
                if e.get("revoked"):
                    return True
                exp = e.get("expires_at")
                if exp is not None and time.time() > exp:
                    return True
            return False
        except Exception:
            return False

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int, likes: int = 0):
        uid_str = str(uid)
        resolved_target = self._resolve_target_for(uid_str)

        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "BD",
                "level": level or 1,
                "initial_exp": exp,
                "current_exp": exp,
                "gained_exp": 0,
                "likes": likes or 0,
                "status": "ONLINE",
                "matches_played": 0,
                "active_matches": 0,
                "last_match_time": None,
                "last_updated": time.strftime("%H:%M:%S"),
                "target_level": resolved_target
            }
        else:
            acc = self.accounts[uid_str]
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = region
            if level:
                acc["level"] = level
            acc["current_exp"] = exp
            acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            acc["likes"] = likes
            acc["status"] = "ONLINE"
            acc["last_updated"] = time.strftime("%H:%M:%S")
            if resolved_target > 0:
                acc["target_level"] = resolved_target
        self.recalc_totals()
        try:
            saved_accounts_store.set_online_status(uid_str, True)
        except Exception:
            pass

    def _resolve_target_for(self, uid_str: str) -> int:
        t = self.account_targets.get(uid_str, 0)
        if t > 0:
            return t
        cred = self.account_credentials.get(uid_str)
        if cred:
            auth_uid = cred.get("auth_uid")
            if auth_uid:
                t = self.account_targets.get(str(auth_uid), 0)
                if t > 0:
                    return t
            auth_token = cred.get("auth_token")
            if auth_token:
                t = self.account_targets.get(f"tok_{auth_token[:10]}", 0)
                if t > 0:
                    return t
        for alias, c in self.account_credentials.items():
            if str(c.get("account_id")) == uid_str:
                if c.get("auth_uid"):
                    t = self.account_targets.get(str(c["auth_uid"]), 0)
                    if t > 0:
                        return t
                if c.get("auth_token"):
                    t = self.account_targets.get(f"tok_{c['auth_token'][:10]}", 0)
                    if t > 0:
                        return t
        return 0

    def register_target(self, alias: str, real_account_id: Optional[str], target: int):
        if target <= 0:
            return
        if alias:
            self.account_targets[str(alias)] = target
        if real_account_id:
            self.account_targets[str(real_account_id)] = target
            if str(real_account_id) in self.accounts:
                self.accounts[str(real_account_id)]["target_level"] = target

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            old_exp = acc["current_exp"]
            acc["current_exp"] = current_exp
            if level is not None and level > 0:
                acc["level"] = level
            acc["gained_exp"] = max(0, current_exp - acc["initial_exp"])
            acc["last_updated"] = time.strftime("%H:%M:%S")
            diff = current_exp - old_exp
            owner = self.get_owner(uid_str)
            if diff > 0:
                self.log(
                    f"Account {acc['nickname']} ({uid_str}) gained +{diff} EXP! Total Gained: +{acc['gained_exp']}",
                    "success", uid_str, owner
                )
            self.recalc_totals()
            try:
                for sacc in saved_accounts_store.accounts:
                    if str(sacc.get("real_account_id", "")) == uid_str:
                        sacc["level"] = level if level else sacc.get("level", 1)
                        sacc["exp"] = current_exp
                        sacc["online"] = True
                        sacc["last_online"] = time.time()
                saved_accounts_store.save()
            except Exception:
                pass

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] += 1
            self.accounts[uid_str]["last_match_time"] = time.strftime("%H:%M:%S")
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
            owner = self.get_owner(uid_str)
            self.log(
                f"Account {self.accounts[uid_str]['nickname']} finished Match #{self.accounts[uid_str]['matches_played']}",
                "info", uid_str, owner
            )

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())

    def is_target_reached(self, uid: str) -> bool:
        uid_str = str(uid)
        target = self.account_targets.get(uid_str, 0)
        if target <= 0:
            target = self._resolve_target_for(uid_str)
        if target <= 0:
            return False

        acc = self.accounts.get(uid_str)
        if not acc:
            for alias, cred in self.account_credentials.items():
                if alias == uid_str or str(cred.get("auth_uid")) == uid_str \
                   or alias == f"tok_{uid_str}" \
                   or (cred.get("auth_token") and uid_str == f"tok_{cred['auth_token'][:10]}"):
                    real_id = str(cred.get("account_id"))
                    acc = self.accounts.get(real_id)
                    if acc:
                        break
        if not acc:
            return False
        return acc.get("level", 1) >= target


bot_state = BotState()


# ==================== HTTP HELPERS ====================
def _read_html(name: str, fallback: str = "<h1>Not found</h1>") -> str:
    for p in (
        os.path.join(BASE_DIR, "templates", name),
        os.path.join(BASE_DIR, name),
    ):
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    return fallback


def _get_session_token(request: web.Request) -> Optional[str]:
    return request.cookies.get(COOKIE_NAME)


def _get_key_from_request(request: web.Request) -> Optional[str]:
    tok = _get_session_token(request)
    if not tok:
        return None
    s = session_store.get(tok)
    if not s:
        return None
    key = s.get("key")
    e = key_store.get(key)
    if not e:
        session_store.destroy(tok); return None
    if e.get("revoked"):
        session_store.destroy(tok); return None
    exp = e.get("expires_at")
    if exp is not None and time.time() > exp:
        session_store.destroy(tok); return None
    if e.get("bound_session") != tok:
        session_store.destroy(tok); return None
    session_store.touch(tok)
    return key


def _check_master(data: Dict[str, Any]) -> bool:
    return str(data.get("master_password", "")) == MASTER_PASSWORD


# ==================== PAGE HANDLERS ====================
async def handle_index(request: web.Request) -> web.Response:
    key = _get_key_from_request(request)
    if not key:
        raise web.HTTPFound("/login")
    return web.Response(text=_read_html("index.html", "<h1>index.html missing</h1>"),
                        content_type="text/html", charset="utf-8")


async def handle_login_page(request: web.Request) -> web.Response:
    # যদি ইতিমধ্যে লগইন করা থাকে, তবে সোজা ড্যাশবোর্ডে পাঠান
    key = _get_key_from_request(request)
    if key:
        raise web.HTTPFound("/")
    return web.Response(text=_read_html("login.html", "<h1>login.html missing</h1>"),
                        content_type="text/html", charset="utf-8")


async def handle_admin_page(request: web.Request) -> web.Response:
    return web.Response(text=_read_html("admin.html", "<h1>admin.html missing</h1>"),
                        content_type="text/html", charset="utf-8")


# ==================== USER AUTH HANDLERS ====================
async def handle_user_login(request: web.Request) -> web.Response:
    """
    NEW LOGIC:
    - Key expired হলে লগইন হবে না।
    - Key revoked হলে লগইন হবে না।
    - Key অন্য কারো সেশনে অ্যাক্টিভ থাকলে লগইন হবে না (অন্য ডিভাইস)।
    - আপনি লগআউট করলে বা আপনার ব্রাউজার বন্ধ করলে, সেই কী দিয়ে আবার লগইন করা যাবে।
    - একই ব্রাউজারে বারবার লগইন করা যাবে যতক্ষণ কী-এর টাইম শেষ না হয়।
    """
    try:
        content_type = (request.headers.get("Content-Type", "") or "").lower()
        is_form = "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type

        if is_form:
            post = await request.post()
            key = str(post.get("key", "")).strip().upper()
        else:
            try:
                data = await request.json()
            except Exception:
                data = {}
            key = str(data.get("key", "")).strip().upper()

        if not key:
            if is_form:
                raise web.HTTPFound("/login?error=Key+required")
            return web.json_response({"status": "error", "error": "Key required"})

        entry = key_store.get(key)
        if not entry:
            if is_form:
                raise web.HTTPFound("/login?error=Invalid+key")
            return web.json_response({"status": "error", "error": "Invalid key"})
        
        # ১. কী রিভোক করা থাকলে
        if entry.get("revoked"):
            if is_form:
                raise web.HTTPFound("/login?error=Key+revoked")
            return web.json_response({"status": "error", "error": "Key revoked"})

        # ২. কী-এর টাইম এক্সপায়ার চেক
        exp = entry.get("expires_at")
        if exp is not None and time.time() > exp:
            if is_form:
                raise web.HTTPFound("/login?error=Key+expired")
            return web.json_response({"status": "error", "error": "This key has expired"})

        # ৩. চেক করুন কী-টি অন্য কোথাও অ্যাক্টিভ আছে কিনা
        bound_token = entry.get("bound_session")
        if bound_token:
            existing = session_store.get(bound_token)
            if existing:
                # সেশন এখনো অ্যাক্টিভ
                # কুকি থেকে বর্তমান ব্রাউজারের টোকেন নিন
                current_cookie_token = _get_session_token(request)
                
                if current_cookie_token and current_cookie_token == bound_token:
                    # আপনি নিজেই আছেন, লগইন করতে দিন
                    pass
                else:
                    # অন্য ডিভাইসে লগইন আছে
                    # তবে ৫ মিনিটের বেশি ইনঅ্যাক্টিভ থাকলে সেশনটি ডিলিট করে দিন
                    last_seen = existing.get("last_seen", 0)
                    if time.time() - last_seen > 300:  # 5 minutes
                        session_store.destroy(bound_token)
                        entry["bound_session"] = None
                        key_store.save()
                    else:
                        if is_form:
                            raise web.HTTPFound("/login?error=Key+already+in+use")
                        return web.json_response({
                            "status": "error",
                            "error": "This key is already in use on another device"
                        })
            else:
                # সেশনটি ডেড (লগআউট বা টাইমআউট)
                entry["bound_session"] = None
                key_store.save()

        # ৪. সফল লগইন
        if entry.get("expires_at") is None:
            entry["expires_at"] = time.time() + entry.get("duration_sec", 60)
        entry["used_at"] = time.time()

        token = session_store.create(key)
        entry["bound_session"] = token
        key_store.save()

        if is_form:
            resp = web.HTTPFound(f"/?login=success&key={key}")
            resp.set_cookie(COOKIE_NAME, token,
                            max_age=SESSION_MAX_AGE,
                            httponly=True, samesite="Lax")
            raise resp

        resp = web.json_response({"status": "ok", "key": key})
        resp.set_cookie(COOKIE_NAME, token,
                        max_age=SESSION_MAX_AGE,
                        httponly=True, samesite="Lax")
        return resp
    except web.HTTPException:
        raise
    except Exception as e:
        if (request.headers.get("Content-Type", "") or "").lower().startswith("application/x-www-form-urlencoded"):
            raise web.HTTPFound(f"/login?error={str(e)}")
        return web.json_response({"status": "error", "error": str(e)})


async def handle_user_logout(request: web.Request) -> web.Response:
    tok = _get_session_token(request)
    if tok:
        s = session_store.get(tok)
        if s:
            key = s.get("key")
            e = key_store.get(key)
            if e and e.get("bound_session") == tok:
                e["bound_session"] = None
                key_store.save()
        session_store.destroy(tok)
    resp = web.json_response({"status": "ok"})
    resp.del_cookie(COOKIE_NAME)
    return resp


async def handle_whoami(request: web.Request) -> web.Response:
    key = _get_key_from_request(request)
    if not key:
        return web.json_response({"status": "unauthorized"}, status=401)
    e = key_store.get(key) or {}
    exp = e.get("expires_at")
    remaining = 0
    if exp is not None:
        remaining = max(0, int(exp - time.time()))
    return web.json_response({
        "status": "ok",
        "key": key,
        "user_name": e.get("user_name"),
        "expires_at": exp or 0,
        "remaining_sec": remaining,
    })


# ==================== DASHBOARD DATA HANDLERS ====================
async def handle_get_stats(request: web.Request) -> web.Response:
    key = _get_key_from_request(request)
    if not key:
        return web.json_response({"status": "unauthorized"}, status=401)

    try:
        e = key_store.get(key) or {}
        exp = e.get("expires_at")
        if exp is not None and time.time() > exp:
            try:
                saved_accounts_store.set_offline_by_key(key)
            except Exception:
                pass
            return web.json_response({"status": "unauthorized", "error": "key expired"}, status=401)
    except Exception:
        pass

    owned_accounts = []
    owned_uids = set()
    for uid, acc in bot_state.accounts.items():
        owner = bot_state.get_owner(uid)
        if owner == key:
            owned_accounts.append(acc)
            owned_uids.add(str(uid))
    owned_accounts.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)

    owned_logs = []
    for l in bot_state.logs:
        if l.get("owner_key") == key:
            owned_logs.append(l)
            continue
        lu = l.get("uid")
        if lu and str(lu) in owned_uids:
            owned_logs.append(l)
            continue
        msg = l.get("message") or ""
        matched = False
        for ou in owned_uids:
            if ou and ou in msg:
                matched = True
                break
        if not matched:
            try:
                tok_matches = re.findall(r'tok_[A-Za-z0-9_\-]+', msg)
                for t in tok_matches:
                    if bot_state.get_owner(t) == key:
                        matched = True
                        break
            except Exception:
                pass
        if matched:
            owned_logs.append(l)

    total_matches = sum(a.get("matches_played", 0) for a in owned_accounts)
    total_gained = sum(a.get("gained_exp", 0) for a in owned_accounts)

    e = key_store.get(key) or {}
    exp = e.get("expires_at")
    return web.json_response({
        "total_accounts": len(owned_accounts),
        "total_matches": total_matches,
        "total_gained_exp": total_gained,
        "accounts": owned_accounts,
        "logs": owned_logs[-80:],
        "uptime": int(time.time() - bot_state.start_time),
        "key_expires_at": exp or 0,
        "key_user_name": e.get("user_name", ""),
    })


async def handle_add_account(request: web.Request) -> web.Response:
    key = _get_key_from_request(request)
    if not key:
        return web.json_response({"status": "error", "error": "Unauthorized"}, status=401)

    try:
        e = key_store.get(key) or {}
        exp = e.get("expires_at")
        if exp is not None and time.time() > exp:
            return web.json_response({"status": "error", "error": "Key expired"}, status=401)
    except Exception:
        pass

    try:
        data = await request.json()
        target_level = int(data.get("target_level", 0) or 0)

        accounts_file = os.path.join(BASE_DIR, f"accounts_{key}.json")
        existing = []
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password are required"})
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
            existing.append({"uid": uid, "password": pwd, "target_level": target_level})
            bot_state.register_target(uid, None, target_level)
            bot_state.set_owner(uid, key)
            bot_state.log(f"New account added: {uid} (Target Level: {target_level})",
                          "success", uid, key)
        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token is required"})
            existing = [acc for acc in existing if acc.get("token") != token]
            existing.append({"token": token, "target_level": target_level})
            alias = f"tok_{token[:10]}"
            bot_state.register_target(alias, None, target_level)
            bot_state.set_owner(alias, key)
            bot_state.set_owner(f"tok_{token[:20]}", key)
            bot_state.log(f"New account added via token (Target Level: {target_level})",
                          "success", None, key)
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        with open(accounts_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        payload_for_callback = dict(data)
        payload_for_callback["_owner_key"] = key

        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](payload_for_callback))

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    key = _get_key_from_request(request)
    if not key:
        return web.json_response({"status": "error", "error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()

        owner = bot_state.get_owner(uid)
        if owner and owner != key:
            return web.json_response({"status": "error", "error": "Not your account"}, status=403)

        accounts_file = os.path.join(BASE_DIR, f"accounts_{key}.json")
        if os.path.exists(accounts_file):
            with open(accounts_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing = [acc for acc in existing
                        if str(acc.get("uid")) != uid and acc.get("token", "")[:10] != uid]
            with open(accounts_file, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)

        if uid in bot_state.accounts:
            del bot_state.accounts[uid]

        if uid in bot_state.account_targets:
            del bot_state.account_targets[uid]

        cred = bot_state.account_credentials.get(uid)
        if cred:
            auth_uid = cred.get("auth_uid")
            if auth_uid and str(auth_uid) in bot_state.account_targets:
                del bot_state.account_targets[str(auth_uid)]
            auth_token = cred.get("auth_token")
            if auth_token:
                alias = f"tok_{auth_token[:10]}"
                if alias in bot_state.account_targets:
                    del bot_state.account_targets[alias]
            real_id = str(cred.get("account_id"))
            if real_id in bot_state.account_targets:
                del bot_state.account_targets[real_id]
            if real_id in bot_state.account_workers:
                w = bot_state.account_workers[real_id]
                if w and not w.done():
                    w.cancel()
                del bot_state.account_workers[real_id]

        if uid in bot_state.account_workers:
            w = bot_state.account_workers[uid]
            if w and not w.done():
                w.cancel()
            del bot_state.account_workers[uid]

        for k in list(bot_state.account_workers.keys()):
            if k.startswith("tok_") and uid.startswith("tok_"):
                if k == uid:
                    w = bot_state.account_workers[k]
                    if w and not w.done():
                        w.cancel()
                    del bot_state.account_workers[k]

        try:
            saved_accounts_store.set_online_by_identifier("guest", uid, False)
            saved_accounts_store.set_online_status(uid, False)
        except Exception:
            pass

        if "on_account_deleted" in bot_state.refresh_callbacks:
            try:
                await bot_state.refresh_callbacks["on_account_deleted"](uid)
            except Exception:
                pass

        bot_state.log(f"Account {uid} removed. Bot stopped.", "warning", uid, key)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    key = _get_key_from_request(request)
    if not key:
        return web.json_response({"status": "error", "error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        owner = bot_state.get_owner(uid)
        if owner and owner != key:
            return web.json_response({"status": "error", "error": "Not your account"}, status=403)
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


# ==================== ADMIN HANDLERS ====================
async def handle_admin_login(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        if _check_master(data):
            return web.json_response({"status": "ok"})
        return web.json_response({"status": "error", "error": "Wrong password"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_admin_generate(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        if not _check_master(data):
            return web.json_response({"status": "error", "error": "Unauthorized"})
        name = str(data.get("user_name", "User")).strip() or "User"
        days = int(data.get("days", 0) or 0)
        hours = int(data.get("hours", 0) or 0)
        minutes = int(data.get("minutes", 0) or 0)
        custom_key = data.get("custom_key", "")

        if days == 0 and hours == 0 and minutes == 0:
            return web.json_response({"status": "error", "error": "Set at least 1 minute"})

        if custom_key and str(custom_key).strip():
            ck = str(custom_key).strip().upper()
            if key_store.exists(ck):
                return web.json_response({"status": "error", "error": f"Key '{ck}' already exists"})

        entry = key_store.generate(name, days, hours, minutes, custom_key)
        return web.json_response({"status": "ok", "key_entry": entry})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_admin_keys(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        if not _check_master(data):
            return web.json_response({"status": "error", "error": "Unauthorized"})
        now = time.time()
        keys = []
        for k, e in key_store.keys.items():
            used = e.get("used_at") is not None
            exp = e.get("expires_at")
            expired = (exp is not None and now > exp)
            active = bool(e.get("bound_session")) and (not expired) and (not e.get("revoked"))
            remaining = 0
            if exp is not None and not expired:
                remaining = max(0, int(exp - now))
            keys.append({
                "key": k,
                "user_name": e.get("user_name"),
                "days": e.get("days", 0),
                "hours": e.get("hours", 0),
                "minutes": e.get("minutes", 0),
                "created_at": e.get("created_at"),
                "expires_at": exp,
                "revoked": e.get("revoked", False),
                "used": used,
                "used_at": e.get("used_at"),
                "in_use": active,
                "expired": expired,
                "remaining_sec": remaining,
                "custom": e.get("custom", False),
            })
        keys.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return web.json_response({"status": "ok", "keys": keys})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_admin_revoke(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        if not _check_master(data):
            return web.json_response({"status": "error", "error": "Unauthorized"})
        key = str(data.get("key", "")).strip()
        key_store.revoke(key)
        session_store.destroy_by_key(key)
        try:
            saved_accounts_store.set_offline_by_key(key)
        except Exception:
            pass
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_admin_delete(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        if not _check_master(data):
            return web.json_response({"status": "error", "error": "Unauthorized"})
        key = str(data.get("key", "")).strip()
        session_store.destroy_by_key(key)
        try:
            saved_accounts_store.set_offline_by_key(key)
        except Exception:
            pass
        key_store.delete(key)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


# ==================== ADMIN SAVED ACCOUNTS HANDLERS ====================
async def handle_admin_saved_accounts(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        if not _check_master(data):
            return web.json_response({"status": "error", "error": "Unauthorized"})
        return web.json_response({
            "status": "ok",
            "accounts": saved_accounts_store.list_all()
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_admin_saved_delete(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        if not _check_master(data):
            return web.json_response({"status": "error", "error": "Unauthorized"})
        real_id = str(data.get("real_account_id", "")).strip()
        if not real_id:
            return web.json_response({"status": "error", "error": "real_account_id required"})
        ok = saved_accounts_store.delete(real_id)
        return web.json_response({"status": "ok" if ok else "error",
                                  "error": "" if ok else "Not found"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


# ==================== BACKGROUND CLEANUP ====================
async def _session_cleanup_loop():
    while True:
        try:
            session_store.cleanup_expired()
            try:
                now = time.time()
                for k, e in list(key_store.keys.items()):
                    exp = e.get("expires_at")
                    if exp is not None and now > exp and not e.get("revoked"):
                        saved_accounts_store.set_offline_by_key(k)
            except Exception:
                pass
        except Exception:
            pass
        await asyncio.sleep(60)


# ==================== SERVER BOOT ====================
async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()

    app.router.add_get("/", handle_index)
    app.router.add_get("/login", handle_login_page)
    app.router.add_get("/yasin-admin", handle_admin_page)

    app.router.add_post("/api/login", handle_user_login)
    app.router.add_post("/api/logout", handle_user_logout)
    app.router.add_get("/api/whoami", handle_whoami)

    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)

    app.router.add_post("/api/admin/login", handle_admin_login)
    app.router.add_post("/api/admin/generate", handle_admin_generate)
    app.router.add_post("/api/admin/keys", handle_admin_keys)
    app.router.add_post("/api/admin/revoke", handle_admin_revoke)
    app.router.add_post("/api/admin/delete", handle_admin_delete)

    app.router.add_post("/api/admin/saved_accounts", handle_admin_saved_accounts)
    app.router.add_post("/api/admin/saved_delete", handle_admin_saved_delete)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    asyncio.create_task(_session_cleanup_loop())

    print(f"\033[92m[+] Web Dashboard running on http://localhost:{port}\033[0m")
    print(f"\033[92m[+] Login page:   http://localhost:{port}/login\033[0m")
    print(f"\033[92m[+] Admin panel:  http://localhost:{port}/admin\033[0m")