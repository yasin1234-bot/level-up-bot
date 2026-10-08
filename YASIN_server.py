# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Web Dashboard + Password Auth System
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
PASSWORDS_FILE = "passwords.json"
SESSIONS_FILE = "sessions.json"
SAVED_ACCOUNTS_FILE = "admin_saved_accounts.json"
ACCOUNTS_FILE = "accounts.json"
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


# ==================== GLOBAL ACCOUNTS FILE HELPERS ====================
def _load_global_accounts() -> List[Dict[str, Any]]:
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return list(data.values())
    except Exception:
        pass
    return []


def _save_global_accounts(accounts: List[Dict[str, Any]]):
    try:
        tmp = ACCOUNTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)
        os.replace(tmp, ACCOUNTS_FILE)
    except Exception as e:
        print(f"[-] Global accounts save error: {e}")


def _add_global_account(entry: Dict[str, Any], owner_key: str) -> bool:
    accounts = _load_global_accounts()
    entry = dict(entry)
    entry["_owner_key"] = owner_key

    auth_type = entry.get("auth_type", "guest")
    if auth_type == "guest":
        identifier_value = str(entry.get("uid", "")).strip()
    else:
        identifier_value = str(entry.get("token", "")).strip()

    is_new = True
    for i, acc in enumerate(accounts):
        if auth_type == "guest" and str(acc.get("uid", "")).strip() == identifier_value:
            accounts[i] = entry
            is_new = False
            break
        elif auth_type == "token" and str(acc.get("token", "")).strip() == identifier_value:
            accounts[i] = entry
            is_new = False
            break

    if is_new:
        accounts.append(entry)

    _save_global_accounts(accounts)
    return is_new


def _remove_global_account(identifier: str, owner_key: str = "") -> bool:
    accounts = _load_global_accounts()
    before = len(accounts)

    def match(acc):
        if owner_key and str(acc.get("_owner_key", "")) != str(owner_key):
            return False
        if str(acc.get("uid", "")).strip() == str(identifier).strip():
            return True
        if str(acc.get("token", "")).strip().startswith(str(identifier).strip()):
            return True
        return False

    accounts = [a for a in accounts if not match(a)]

    if len(accounts) != before:
        _save_global_accounts(accounts)
        return True
    return False


# ==================== PASSWORD STORE ====================
class PasswordStore:
    """Single shared admin password that everyone can use to login."""
    def __init__(self, path: str):
        self.path = path
        self.current_password: str = "YASIN2026"
        self.created_at: float = time.time()
        self.updated_at: float = time.time()
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.current_password = str(data.get("password", "YASIN2026"))
                        self.created_at = float(data.get("created_at", time.time()))
                        self.updated_at = float(data.get("updated_at", time.time()))
            except Exception:
                pass

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "password": self.current_password,
                    "created_at": self.created_at,
                    "updated_at": self.updated_at,
                }, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def verify(self, password: str) -> bool:
        return str(password) == self.current_password

    def change(self, new_password: str) -> bool:
        new_password = str(new_password).strip()
        if not new_password or len(new_password) < 3:
            return False
        self.current_password = new_password
        self.updated_at = time.time()
        self.save()
        return True

    def get_current(self) -> str:
        return self.current_password


password_store = PasswordStore(PASSWORDS_FILE)


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

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions[token] = {
            "created_at": time.time(),
            "last_seen": time.time(),
            "password_used": password_store.current_password,
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

    def destroy_all(self):
        self.sessions = {}
        self.save()

    def cleanup_expired(self):
        # Only remove sessions older than 90 days of inactivity
        dead = []
        now = time.time()
        for tok, s in self.sessions.items():
            if now - s.get("last_seen", 0) > 60 * 60 * 24 * 90:
                dead.append(tok)
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
        self.paused_accounts: Dict[str, bool] = {}

        self.account_start_times: Dict[str, float] = {}
        self.account_pause_total: Dict[str, float] = {}
        self.account_pause_started: Dict[str, float] = {}

        self.current_maps: Dict[str, Optional[str]] = {}

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
        # ✅ Key expiry disabled — always return False
        return False

    def _ensure_uptime_entry(self, uid_str: str):
        if uid_str not in self.account_start_times:
            self.account_start_times[uid_str] = time.time()
            self.account_pause_total[uid_str] = 0.0
            self.account_pause_started[uid_str] = 0.0

    def get_uptime_seconds(self, uid_str: str) -> int:
        uid_str = str(uid_str)
        if uid_str not in self.account_start_times:
            return 0
        now = time.time()
        start = self.account_start_times[uid_str]
        paused_total = self.account_pause_total.get(uid_str, 0.0)
        pause_started = self.account_pause_started.get(uid_str, 0.0)
        if pause_started > 0:
            paused_total += (now - pause_started)
        elapsed = now - start - paused_total
        return int(max(0, elapsed))

    def set_current_map(self, uid: str, map_name: Optional[str]):
        uid_str = str(uid)
        if map_name:
            self.current_maps[uid_str] = str(map_name)
        else:
            self.current_maps.pop(uid_str, None)

    def get_current_map(self, uid: str) -> Optional[str]:
        return self.current_maps.get(str(uid))

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int, likes: int = 0):
        uid_str = str(uid)
        resolved_target = self._resolve_target_for(uid_str)

        self._ensure_uptime_entry(uid_str)

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
                "target_level": resolved_target,
                "paused": self.paused_accounts.get(uid_str, False),
                "current_map": self.current_maps.get(uid_str)
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
            acc["paused"] = self.paused_accounts.get(uid_str, False)
            acc["current_map"] = self.current_maps.get(uid_str)
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
        if alias:
            if target > 0:
                self.account_targets[str(alias)] = target
            else:
                self.account_targets.pop(str(alias), None)
        if real_account_id:
            if target > 0:
                self.account_targets[str(real_account_id)] = target
                if str(real_account_id) in self.accounts:
                    self.accounts[str(real_account_id)]["target_level"] = target
            else:
                self.account_targets.pop(str(real_account_id), None)
                if str(real_account_id) in self.accounts:
                    self.accounts[str(real_account_id)]["target_level"] = 0

    def clear_target_for_uid(self, uid: str):
        uid_str = str(uid)
        self.account_targets.pop(uid_str, None)
        if uid_str in self.accounts:
            self.accounts[uid_str]["target_level"] = 0
            if self.accounts[uid_str].get("status") == "TARGET_REACHED":
                self.accounts[uid_str]["status"] = "ONLINE"

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
            self.accounts[uid_str]["paused"] = self.paused_accounts.get(uid_str, False)
            self.accounts[uid_str]["current_map"] = self.current_maps.get(uid_str)

    def increment_match(self, uid: str):
        uid_str = str(uid)
        if self.paused_accounts.get(uid_str, False):
            return
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

    def is_paused(self, uid: str) -> bool:
        return self.paused_accounts.get(str(uid), False)

    def set_paused(self, uid: str, paused: bool):
        uid_str = str(uid)
        self._ensure_uptime_entry(uid_str)
        now = time.time()

        was_paused = self.paused_accounts.get(uid_str, False)

        if paused and not was_paused:
            self.account_pause_started[uid_str] = now
        elif not paused and was_paused:
            started = self.account_pause_started.get(uid_str, 0.0)
            if started > 0:
                self.account_pause_total[uid_str] = self.account_pause_total.get(uid_str, 0.0) + (now - started)
            self.account_pause_started[uid_str] = 0.0

        self.paused_accounts[uid_str] = paused
        if uid_str in self.accounts:
            self.accounts[uid_str]["paused"] = paused
            if paused:
                self.accounts[uid_str]["status"] = "PAUSED"
            else:
                self.accounts[uid_str]["status"] = "ONLINE"
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def clear_account_uptime(self, uid: str):
        uid_str = str(uid)
        self.account_start_times.pop(uid_str, None)
        self.account_pause_total.pop(uid_str, None)
        self.account_pause_started.pop(uid_str, None)
        self.paused_accounts.pop(uid_str, None)
        self.current_maps.pop(uid_str, None)


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


def _check_session(request: web.Request) -> bool:
    """✅ Session must exist AND password version must match.
    If admin changes the login password, all old sessions become invalid instantly."""
    tok = _get_session_token(request)
    if not tok:
        return False
    s = session_store.get(tok)
    if not s:
        return False
    # ✅ Invalidate session if the password has been changed since login
    used_pw = s.get("password_used")
    if used_pw is not None and used_pw != password_store.current_password:
        # Password changed → this session is dead
        session_store.destroy(tok)
        return False
    session_store.touch(tok)
    return True


# ==================== PAGE HANDLERS ====================
async def handle_index(request: web.Request) -> web.Response:
    if not _check_session(request):
        raise web.HTTPFound("/login")
    return web.Response(text=_read_html("index.html", "<h1>index.html missing</h1>"),
                        content_type="text/html", charset="utf-8")


async def handle_login_page(request: web.Request) -> web.Response:
    if _check_session(request):
        raise web.HTTPFound("/")
    return web.Response(text=_read_html("login.html", "<h1>login.html missing</h1>"),
                        content_type="text/html", charset="utf-8")


async def handle_admin_page(request: web.Request) -> web.Response:
    return web.Response(text=_read_html("admin.html", "<h1>admin.html missing</h1>"),
                        content_type="text/html", charset="utf-8")


# ==================== USER AUTH HANDLERS ====================
async def handle_user_login(request: web.Request) -> web.Response:
    try:
        content_type = (request.headers.get("Content-Type", "") or "").lower()
        is_form = "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type

        if is_form:
            post = await request.post()
            password = str(post.get("password", "")).strip()
        else:
            try:
                data = await request.json()
            except Exception:
                data = {}
            password = str(data.get("password", "")).strip()

        if not password:
            if is_form:
                raise web.HTTPFound("/login?error=Password+required")
            return web.json_response({"status": "error", "error": "Password required"})

        if not password_store.verify(password):
            if is_form:
                raise web.HTTPFound("/login?error=Invalid+password")
            return web.json_response({"status": "error", "error": "Invalid password"})

        # ✅ Create session — no binding to specific password string, no single-session limit
        token = session_store.create()

        if is_form:
            resp = web.HTTPFound("/?login=success")
            resp.set_cookie(COOKIE_NAME, token,
                            max_age=SESSION_MAX_AGE,
                            httponly=True, samesite="Lax")
            raise resp

        resp = web.json_response({"status": "ok"})
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
        session_store.destroy(tok)
    resp = web.json_response({"status": "ok"})
    resp.del_cookie(COOKIE_NAME)
    return resp


async def handle_whoami(request: web.Request) -> web.Response:
    if not _check_session(request):
        return web.json_response({"status": "unauthorized"}, status=401)
    return web.json_response({
        "status": "ok",
        "password_version": password_store.updated_at,
    })


# ==================== DASHBOARD DATA HANDLERS ====================
async def handle_get_stats(request: web.Request) -> web.Response:
    if not _check_session(request):
        return web.json_response({"status": "unauthorized"}, status=401)

    owned_accounts = []
    for uid, acc in bot_state.accounts.items():
        acc_copy = dict(acc)
        acc_copy["uptime_seconds"] = bot_state.get_uptime_seconds(uid)
        acc_copy["current_map"] = bot_state.get_current_map(uid)
        owned_accounts.append(acc_copy)
    owned_accounts.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)

    total_matches = sum(a.get("matches_played", 0) for a in owned_accounts)
    total_gained = sum(a.get("gained_exp", 0) for a in owned_accounts)

    return web.json_response({
        "total_accounts": len(owned_accounts),
        "total_matches": total_matches,
        "total_gained_exp": total_gained,
        "accounts": owned_accounts,
        "logs": bot_state.logs[-80:],
        "uptime": int(time.time() - bot_state.start_time),
    })


async def handle_add_account(request: web.Request) -> web.Response:
    if not _check_session(request):
        return web.json_response({"status": "error", "error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
        target_level = int(data.get("target_level", 0) or 0)

        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password are required"})

            try:
                bot_state.register_target(uid, None, 0)
                bot_state.clear_account_uptime(uid)
            except Exception:
                pass

            _add_global_account({
                "uid": uid,
                "password": pwd,
                "target_level": target_level,
                "auth_type": "guest",
            }, owner_key="")

            bot_state.register_target(uid, None, target_level)
            bot_state.set_paused(uid, False)
            bot_state.log(f"New account added: {uid} (Target Level: {target_level})",
                          "success", uid)

            payload_for_callback = dict(data)

            if "on_account_added" in bot_state.refresh_callbacks:
                asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](payload_for_callback))

        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token is required"})

            alias = f"tok_{token[:10]}"
            try:
                bot_state.register_target(alias, None, 0)
                bot_state.clear_account_uptime(alias)
            except Exception:
                pass

            _add_global_account({
                "token": token,
                "target_level": target_level,
                "auth_type": "token",
            }, owner_key="")

            bot_state.register_target(alias, None, target_level)
            bot_state.set_paused(alias, False)
            bot_state.log(f"New account added via token (Target Level: {target_level})",
                          "success", None)

            payload_for_callback = dict(data)

            if "on_account_added" in bot_state.refresh_callbacks:
                asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](payload_for_callback))
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    if not _check_session(request):
        return web.json_response({"status": "error", "error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()

        _remove_global_account(uid)

        if uid in bot_state.accounts:
            del bot_state.accounts[uid]

        if uid in bot_state.account_targets:
            del bot_state.account_targets[uid]

        try:
            bot_state.clear_account_uptime(uid)
        except Exception:
            pass

        cred = bot_state.account_credentials.get(uid)
        if cred:
            auth_uid = cred.get("auth_uid")
            if auth_uid and str(auth_uid) in bot_state.account_targets:
                del bot_state.account_targets[str(auth_uid)]
            if auth_uid:
                try:
                    bot_state.clear_account_uptime(str(auth_uid))
                except Exception:
                    pass
            auth_token = cred.get("auth_token")
            if auth_token:
                alias = f"tok_{auth_token[:10]}"
                if alias in bot_state.account_targets:
                    del bot_state.account_targets[alias]
                try:
                    bot_state.clear_account_uptime(alias)
                    bot_state.clear_account_uptime(f"tok_{auth_token[:20]}")
                except Exception:
                    pass
            real_id = str(cred.get("account_id"))
            if real_id in bot_state.account_targets:
                del bot_state.account_targets[real_id]
            try:
                bot_state.clear_account_uptime(real_id)
            except Exception:
                pass
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

        bot_state.log(f"Account {uid} removed. Bot stopped.", "warning", uid)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    if not _check_session(request):
        return web.json_response({"status": "error", "error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_pause_account(request: web.Request) -> web.Response:
    if not _check_session(request):
        return web.json_response({"status": "error", "error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()

        bot_state.set_paused(uid, True)
        bot_state.log(f"Account {uid} paused by user. Bot online but not playing matches.",
                      "warning", uid)

        if "on_account_paused" in bot_state.refresh_callbacks:
            try:
                await bot_state.refresh_callbacks["on_account_paused"](uid)
            except Exception:
                pass

        return web.json_response({"status": "ok", "paused": True})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_resume_account(request: web.Request) -> web.Response:
    if not _check_session(request):
        return web.json_response({"status": "error", "error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()

        bot_state.set_paused(uid, False)
        bot_state.log(f"Account {uid} resumed by user. Bot will start playing matches.",
                      "success", uid)

        if "on_account_resumed" in bot_state.refresh_callbacks:
            try:
                await bot_state.refresh_callbacks["on_account_resumed"](uid)
            except Exception:
                pass

        return web.json_response({"status": "ok", "paused": False})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


# ==================== ADMIN HANDLERS ====================
def _check_master(data: Dict[str, Any]) -> bool:
    return str(data.get("master_password", "")) == MASTER_PASSWORD


async def handle_admin_login(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        if _check_master(data):
            return web.json_response({"status": "ok"})
        return web.json_response({"status": "error", "error": "Wrong password"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_admin_get_password(request: web.Request) -> web.Response:
    """Get current shared login password."""
    try:
        data = await request.json()
        if not _check_master(data):
            return web.json_response({"status": "error", "error": "Unauthorized"})
        return web.json_response({
            "status": "ok",
            "password": password_store.get_current(),
            "updated_at": password_store.updated_at,
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_admin_change_password(request: web.Request) -> web.Response:
    """Change shared login password.
    ✅ All existing user sessions are destroyed instantly → everyone must re-login with new password.
    ✅ Old password stops working immediately."""
    try:
        data = await request.json()
        if not _check_master(data):
            return web.json_response({"status": "error", "error": "Unauthorized"})
        new_password = str(data.get("new_password", "")).strip()
        if not new_password or len(new_password) < 3:
            return web.json_response({"status": "error", "error": "Password must be at least 3 characters"})

        old_pw = password_store.get_current()
        if new_password == old_pw:
            return web.json_response({"status": "error", "error": "New password is same as old password"})

        ok = password_store.change(new_password)
        if not ok:
            return web.json_response({"status": "error", "error": "Failed to change password"})

        # ✅ Force logout every logged-in user
        session_store.destroy_all()

        return web.json_response({
            "status": "ok",
            "password": password_store.get_current(),
            "updated_at": password_store.updated_at,
            "sessions_destroyed": True,
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_admin_logout_all(request: web.Request) -> web.Response:
    """Force all users to re-login (destroy every active session)."""
    try:
        data = await request.json()
        if not _check_master(data):
            return web.json_response({"status": "error", "error": "Unauthorized"})
        session_store.destroy_all()
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
        except Exception:
            pass
        await asyncio.sleep(300)


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
    app.router.add_post("/api/account/pause", handle_pause_account)
    app.router.add_post("/api/account/resume", handle_resume_account)

    app.router.add_post("/api/admin/login", handle_admin_login)
    app.router.add_post("/api/admin/get_password", handle_admin_get_password)
    app.router.add_post("/api/admin/change_password", handle_admin_change_password)
    app.router.add_post("/api/admin/logout_all", handle_admin_logout_all)

    app.router.add_post("/api/admin/saved_accounts", handle_admin_saved_accounts)
    app.router.add_post("/api/admin/saved_delete", handle_admin_saved_delete)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    asyncio.create_task(_session_cleanup_loop())

    print(f"\033[92m[+] Web Dashboard running on http://localhost:{port}\033[0m")
    print(f"\033[92m[+] Login page:   http://localhost:{port}/login\033[0m")
    print(f"\033[92m[+] Admin panel:  http://localhost:{port}/yasin-admin\033[0m")