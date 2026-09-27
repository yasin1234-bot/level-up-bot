# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Professional Web Dashboard & Real-Time EXP Tracker
Embedded Async Web Server (aiohttp)
MULTI-USER ISOLATED VERSION + ADMIN PANEL
"""

import asyncio
import json
import os
import time
import hashlib
import secrets
from typing import Dict, List, Any, Optional, Set
from aiohttp import web

# ==================== BASE DIRECTORY ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, "users.json")
USER_DATA_DIR = os.path.join(BASE_DIR, "user_data")
ADMIN_ACCOUNTS_FILE = os.path.join(BASE_DIR, "admin_accounts.json")

os.makedirs(USER_DATA_DIR, exist_ok=True)

ADMIN_PASSWORD = "YASIN-6767"


# ==================== PER-USER BOT STATE ====================
class BotState:
    """Each user gets their own isolated BotState instance."""
    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        # 🔥 Login failure tracking
        self.login_failures: Dict[str, int] = {}
        self.blocked_accounts: Set[str] = set()  # UIDs/tokens that failed 3 times

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "uid": uid
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int,
                         likes: int = 0, target_level: int = 100):
        uid_str = str(uid)
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
                "target_level": target_level,
                "completed": False,
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
            if target_level and not acc.get("completed", False):
                acc["target_level"] = target_level
        self.recalc_totals()

    def set_target_level(self, uid: str, target_level: int):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["target_level"] = target_level
            self.accounts[uid_str]["completed"] = False

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
            if diff > 0:
                self.log(f"Account {acc['nickname']} ({uid_str}) gained +{diff} EXP! Total Gained: +{acc['gained_exp']}", "success", uid_str)
            self.recalc_totals()

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def mark_completed(self, uid: str):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = "COMPLETED"
            self.accounts[uid_str]["completed"] = True
            self.accounts[uid_str]["active_matches"] = 0
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def is_target_reached(self, uid: str) -> bool:
        uid_str = str(uid)
        acc = self.accounts.get(uid_str)
        if not acc:
            return False
        return int(acc.get("level", 1)) >= int(acc.get("target_level", 100))

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] += 1
            self.accounts[uid_str]["last_match_time"] = time.strftime("%H:%M:%S")
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
            self.log(f"Account {self.accounts[uid_str]['nickname']} finished Match #{self.accounts[uid_str]['matches_played']}", "info", uid_str)

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())


# ==================== USER MANAGER (ISOLATION CORE) ====================
class UserManager:
    def __init__(self):
        self._states: Dict[str, BotState] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _email_key(email: str) -> str:
        return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _user_accounts_file(user_id: str) -> str:
        return os.path.join(USER_DATA_DIR, f"{user_id}_accounts.json")

    @staticmethod
    def _user_deleted_file(user_id: str) -> str:
        """🔥 Persistent deleted/blocked accounts per user."""
        return os.path.join(USER_DATA_DIR, f"{user_id}_deleted.json")

    def get_state(self, user_id: str) -> BotState:
        if user_id not in self._states:
            self._states[user_id] = BotState(user_id=user_id)
        return self._states[user_id]

    def get_user_id_from_request(self, request: web.Request) -> Optional[str]:
        cookie = request.cookies.get("auth_session")
        if not cookie:
            return None
        try:
            user_id, _ = cookie.split(":", 1)
            if user_id and os.path.exists(os.path.join(USER_DATA_DIR, f"{user_id}_profile.json")):
                return user_id
        except Exception:
            pass
        return None

    def load_user_accounts(self, user_id: str) -> List[Dict[str, Any]]:
        path = self._user_accounts_file(user_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception:
                pass
        return []

    def save_user_accounts(self, user_id: str, accounts: List[Dict[str, Any]]):
        path = self._user_accounts_file(user_id)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2)
        os.replace(tmp, path)

    # 🔥 DELETED ACCOUNTS PERSISTENCE
    def load_deleted_accounts(self, user_id: str) -> Dict[str, Any]:
        """Load persistent deleted/blocked list for a user."""
        path = self._user_deleted_file(user_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                pass
        return {"uids": [], "tokens": [], "blocked": []}

    def save_deleted_accounts(self, user_id: str, data: Dict[str, Any]):
        path = self._user_deleted_file(user_id)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)

    def mark_account_deleted(self, user_id: str, uid: str = "", token: str = ""):
        """Mark account as deleted persistently so it never restarts."""
        data = self.load_deleted_accounts(user_id)
        if uid and uid not in data["uids"]:
            data["uids"].append(uid)
        if token and token not in data["tokens"]:
            data["tokens"].append(token)
        self.save_deleted_accounts(user_id, data)

    def is_account_deleted(self, user_id: str, uid: str = "", token: str = "") -> bool:
        """Check if account was deleted by this user."""
        data = self.load_deleted_accounts(user_id)
        if uid and uid in data["uids"]:
            return True
        if token and token in data["tokens"]:
            return True
        return False

    def mark_account_blocked(self, user_id: str, identifier: str):
        """🔥 Mark account as blocked after 3 login failures."""
        data = self.load_deleted_accounts(user_id)
        if identifier not in data["blocked"]:
            data["blocked"].append(identifier)
        self.save_deleted_accounts(user_id, data)
        # Also add to state's blocked set
        state = self.get_state(user_id)
        state.blocked_accounts.add(identifier)

    def is_account_blocked(self, user_id: str, identifier: str) -> bool:
        """Check if account is blocked due to repeated login failures."""
        data = self.load_deleted_accounts(user_id)
        return identifier in data.get("blocked", [])

    @staticmethod
    def _user_profile_file(user_id: str) -> str:
        return os.path.join(USER_DATA_DIR, f"{user_id}_profile.json")

    def save_user_profile(self, user_id: str, email: str):
        profile = {"user_id": user_id, "email": email, "created_at": time.time()}
        with open(self._user_profile_file(user_id), "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)

    def find_user_by_credential(self, uid: str = "", token: str = "") -> Optional[str]:
        """Find which user has this uid or token."""
        for user_id in self._states.keys():
            accs = self.load_user_accounts(user_id)
            for a in accs:
                if uid and str(a.get("uid")) == uid:
                    return user_id
                if token and a.get("token") == token:
                    return user_id
        return None


user_manager = UserManager()


# ==================== ADMIN STORAGE ====================
def _load_admin_accounts() -> List[Dict[str, Any]]:
    if os.path.exists(ADMIN_ACCOUNTS_FILE):
        try:
            with open(ADMIN_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []


def _save_admin_accounts(accounts: List[Dict[str, Any]]):
    tmp = ADMIN_ACCOUNTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2)
    os.replace(tmp, ADMIN_ACCOUNTS_FILE)


def _admin_generate_id() -> str:
    return secrets.token_hex(8)


def _admin_find_guest(uid: str, password: str) -> Optional[Dict[str, Any]]:
    for a in _load_admin_accounts():
        if (a.get("type") == "guest"
                and str(a.get("uid")) == str(uid)
                and str(a.get("password")) == str(password)):
            return a
    return None


def _admin_find_token(token: str) -> Optional[Dict[str, Any]]:
    for a in _load_admin_accounts():
        if a.get("type") == "token" and str(a.get("token")) == str(token):
            return a
    return None


def _admin_add_guest(uid: str, password: str, nickname: str = "", owner: str = "") -> Dict[str, Any]:
    existing = _admin_find_guest(uid, password)
    if existing:
        if nickname and not existing.get("nickname"):
            existing["nickname"] = nickname
        if owner:
            existing["last_owner"] = owner
        _save_admin_accounts(_load_admin_accounts())
        return existing

    entry = {
        "id": _admin_generate_id(),
        "type": "guest",
        "uid": str(uid),
        "password": str(password),
        "nickname": nickname or f"UID {uid}",
        "created_at": time.time(),
        "first_owner": owner,
        "last_owner": owner,
    }
    accounts = _load_admin_accounts()
    accounts.append(entry)
    _save_admin_accounts(accounts)
    return entry


def _admin_add_token(token: str, nickname: str = "", owner: str = "") -> Dict[str, Any]:
    existing = _admin_find_token(token)
    if existing:
        if nickname and not existing.get("nickname"):
            existing["nickname"] = nickname
        if owner:
            existing["last_owner"] = owner
        _save_admin_accounts(_load_admin_accounts())
        return existing

    entry = {
        "id": _admin_generate_id(),
        "type": "token",
        "token": str(token),
        "nickname": nickname or f"Token {str(token)[:10]}",
        "created_at": time.time(),
        "first_owner": owner,
        "last_owner": owner,
    }
    accounts = _load_admin_accounts()
    accounts.append(entry)
    _save_admin_accounts(accounts)
    return entry


# ==================== AUTH HELPERS ====================
def _load_users() -> Dict[str, str]:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def _save_users(users: Dict[str, str]):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)


def _check_admin_auth(request: web.Request) -> bool:
    pwd = request.headers.get("X-Admin-Password", "")
    return pwd == ADMIN_PASSWORD


# ==================== TEMPLATE PATHS ====================
TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "index.html")
LOGIN_TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "login.html")
ADMIN_TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "admin.html")


# ==================== AUTH MIDDLEWARE ====================
@web.middleware
async def auth_middleware(request: web.Request, handler):
    path = request.path
    public_paths = {"/login", "/api/login", "/admin"}

    if path in public_paths:
        return await handler(request)

    if path.startswith("/api/admin/"):
        if not _check_admin_auth(request):
            return web.json_response({"status": "error", "error": "Admin unauthorized"}, status=401)
        return await handler(request)

    user_id = user_manager.get_user_id_from_request(request)
    if not user_id:
        if path.startswith("/api/"):
            return web.json_response({"status": "error", "error": "Unauthorized"}, status=401)
        return web.HTTPFound("/login")

    request["user_id"] = user_id
    return await handler(request)


# ==================== HTTP HANDLERS ====================

async def handle_login_page(request: web.Request) -> web.Response:
    if user_manager.get_user_id_from_request(request):
        return web.HTTPFound("/")
    if os.path.exists(LOGIN_TEMPLATE_PATH):
        with open(LOGIN_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "<h1>templates/login.html not found!</h1>"
    return web.Response(text=content, content_type="text/html", charset="utf-8")


async def handle_admin_page(request: web.Request) -> web.Response:
    if os.path.exists(ADMIN_TEMPLATE_PATH):
        with open(ADMIN_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "<h1>templates/admin.html not found!</h1>"
    return web.Response(text=content, content_type="text/html", charset="utf-8")


async def handle_api_login(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", "")).strip()

        if not email or not password:
            return web.json_response({"status": "error", "error": "Email and password required!"})

        users = _load_users()

        if email in users:
            if users[email] != password:
                return web.json_response({"status": "error", "error": "This email is already registered! Wrong password."})
        else:
            users[email] = password
            _save_users(users)

        user_id = UserManager._email_key(email)
        user_manager.save_user_profile(user_id, email)
        user_manager.get_state(user_id)

        session_token = secrets.token_urlsafe(24)
        cookie_value = f"{user_id}:{session_token}"

        response = web.json_response({"status": "ok"})
        response.set_cookie(
            "auth_session",
            cookie_value,
            max_age=86400 * 7,
            httponly=True,
            samesite="Lax",
        )
        return response
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_index(request: web.Request) -> web.Response:
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "<h1>templates/index.html not found!</h1>"
    return web.Response(text=content, content_type="text/html", charset="utf-8")


async def handle_logout(request: web.Request) -> web.Response:
    response = web.HTTPFound("/login")
    response.del_cookie("auth_session")
    return response


async def handle_get_stats(request: web.Request) -> web.Response:
    user_id = request["user_id"]
    state = user_manager.get_state(user_id)

    accounts_data = list(state.accounts.values())
    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)
    return web.json_response({
        "total_accounts": len(state.accounts),
        "total_matches": state.total_matches,
        "total_gained_exp": state.total_gained_exp,
        "accounts": accounts_data,
        "logs": state.logs[-60:],
        "uptime": int(time.time() - state.start_time)
    })


async def handle_add_account(request: web.Request) -> web.Response:
    """
    User-side add account.
    🔥 FIXED: 
    - If account was deleted by this user, it can be re-added (deleted list cleared).
    - If account is blocked (3 login failures), cannot be added.
    - 🔥 CRITICAL: Admin panel entry is NOT created here. Only created after SUCCESSFUL login.
    """
    try:
        user_id = request["user_id"]
        state = user_manager.get_state(user_id)
        data = await request.json()

        try:
            target_level = int(data.get("target_level", 100))
        except (ValueError, TypeError):
            target_level = 100
        if target_level < 3:
            target_level = 3
        if target_level > 100:
            target_level = 100

        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password are required"})

            # 🔥 Check if blocked (3 login failures)
            if user_manager.is_account_blocked(user_id, f"uid_{uid}"):
                return web.json_response({
                    "status": "error",
                    "error": "This UID is blocked due to 3 consecutive login failures. Cannot re-add."
                })

            # 🔥 If previously deleted by this user, remove from deleted list (allow re-add)
            deleted_data = user_manager.load_deleted_accounts(user_id)
            if uid in deleted_data["uids"]:
                deleted_data["uids"].remove(uid)
                user_manager.save_deleted_accounts(user_id, deleted_data)

            # 🔥 REMOVED: _admin_add_guest() call here — admin entry is created only after successful login
            # The login process (account_loop_guest) will call _admin_add_guest after success.

            existing = user_manager.load_user_accounts(user_id)
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
            existing.append({
                "uid": uid,
                "password": pwd,
                "target_level": target_level
                # admin_id will be added after successful login
            })
            user_manager.save_user_accounts(user_id, existing)

            state.set_target_level(uid, target_level)
            # Reset login failure counter
            state.login_failures.pop(f"uid_{uid}", None)

        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token is required"})

            # 🔥 Check if blocked (3 login failures)
            if user_manager.is_account_blocked(user_id, f"tok_{token[:20]}"):
                return web.json_response({
                    "status": "error",
                    "error": "This token is blocked due to 3 consecutive login failures. Cannot re-add."
                })

            # 🔥 If previously deleted by this user, remove from deleted list (allow re-add)
            deleted_data = user_manager.load_deleted_accounts(user_id)
            if token in deleted_data["tokens"]:
                deleted_data["tokens"].remove(token)
                user_manager.save_deleted_accounts(user_id, deleted_data)

            # 🔥 REMOVED: _admin_add_token() call here — admin entry is created only after successful login

            existing = user_manager.load_user_accounts(user_id)
            existing = [acc for acc in existing if acc.get("token") != token]
            existing.append({
                "token": token,
                "target_level": target_level
                # admin_id will be added after successful login
            })
            user_manager.save_user_accounts(user_id, existing)

            state.set_target_level(token[:10], target_level)
            state.login_failures.pop(f"tok_{token[:20]}", None)
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        state.log(
            f"New account added (Target Lv {target_level}): {data.get('uid') or 'Token'}",
            "success"
        )

        if "on_account_added" in state.refresh_callbacks:
            payload = dict(data)
            payload["target_level"] = target_level
            payload["__user_id__"] = user_id
            asyncio.create_task(state.refresh_callbacks["on_account_added"](payload))

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    """
    🔥 FIXED DELETE: 
    - Immediately cancels ALL workers (TCP + UDP + informational + exp)
    - Persistently marks account as deleted
    - Removes from user's accounts.json
    - Ensures account NEVER restarts even after file stop/start
    """
    try:
        user_id = request["user_id"]
        state = user_manager.get_state(user_id)

        data = await request.json()
        uid = str(data.get("uid")).strip() if data.get("uid") else ""
        token = str(data.get("token")).strip() if data.get("token") else ""

        # If only uid given, check if it's a token-based account (uid == token[:10])
        if uid and not token:
            existing = user_manager.load_user_accounts(user_id)
            for acc in existing:
                if acc.get("token") and acc["token"][:10] == uid:
                    token = acc["token"]
                    uid = ""
                    break

        # 🔥 PERSISTENTLY mark as deleted
        user_manager.mark_account_deleted(user_id, uid=uid, token=token)

        # Remove from user's accounts file
        existing = user_manager.load_user_accounts(user_id)
        if uid:
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
        if token:
            existing = [acc for acc in existing if acc.get("token") != token]
        user_manager.save_user_accounts(user_id, existing)

        cancelled_count = 0

        # 🔥 Cancel ALL matching workers
        keys_to_try = []
        if uid:
            keys_to_try.append(uid)
        if token:
            keys_to_try.append(token[:10])

        for key in keys_to_try:
            if key in state.account_workers:
                task = state.account_workers.pop(key)
                if not task.done():
                    task.cancel()
                    cancelled_count += 1
                    try:
                        await asyncio.wait_for(task, timeout=2.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                        pass

        # 🔥 Remove credentials for uid
        if uid:
            cred = state.account_credentials.pop(uid, None)
            if cred:
                aliases = [k for k, v in list(state.account_credentials.items()) if v is cred]
                for alias in aliases:
                    state.account_credentials.pop(alias, None)
                    if alias in state.account_workers:
                        t = state.account_workers.pop(alias)
                        if not t.done():
                            t.cancel()
                            cancelled_count += 1
                            try:
                                await asyncio.wait_for(t, timeout=2.0)
                            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                                pass

        # 🔥 Remove credentials for token
        if token:
            cred_key = f"tok_{token[:20]}"
            cred = state.account_credentials.pop(cred_key, None)
            if cred:
                aliases = [k for k, v in list(state.account_credentials.items()) if v is cred]
                for alias in aliases:
                    state.account_credentials.pop(alias, None)
                    if alias in state.account_workers:
                        t = state.account_workers.pop(alias)
                        if not t.done():
                            t.cancel()
                            cancelled_count += 1
                            try:
                                await asyncio.wait_for(t, timeout=2.0)
                            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                                pass

        # Remove from state.accounts view
        for key in list(state.accounts.keys()):
            if uid and key == uid:
                del state.accounts[key]
            elif token and key == token[:10]:
                del state.accounts[key]

        # Also remove any other workers whose account_id matches
        for wkey in list(state.account_workers.keys()):
            task = state.account_workers[wkey]
            if task.done():
                state.account_workers.pop(wkey, None)

        label = uid if uid else (token[:10] if token else "unknown")
        state.log(f"Account {label} removed from dashboard. Worker cancelled: {cancelled_count}", "warning", uid or None)
        return web.json_response({"status": "ok", "cancelled": cancelled_count > 0})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        user_id = request["user_id"]
        state = user_manager.get_state(user_id)
        data = await request.json()
        uid = str(data.get("uid")).strip()
        if "on_refresh_account" in state.refresh_callbacks:
            asyncio.create_task(state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_reset_dashboard(request: web.Request) -> web.Response:
    try:
        user_id = request["user_id"]
        state = user_manager.get_state(user_id)

        state.logs.clear()

        try:
            from main import _match_counters, _match_counter_lock
            async with _match_counter_lock:
                for acc_id in list(state.accounts.keys()):
                    _match_counters[acc_id] = 0
        except Exception:
            pass

        for acc_id in state.accounts:
            state.accounts[acc_id]["matches_played"] = 0

        state.total_matches = 0
        state.log("🔄 Dashboard reset — logs cleared, counters reset. Accounts still running.", "info")

        return web.json_response({
            "status": "ok",
            "message": "Dashboard reset successful. Accounts are still running."
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


# ==================== ADMIN API HANDLERS ====================

async def handle_admin_list(request: web.Request) -> web.Response:
    accounts = _load_admin_accounts()
    return web.json_response({"status": "ok", "entries": accounts})


async def handle_admin_add(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        entry_type = str(data.get("type", "")).strip().lower()
        nickname = str(data.get("nickname", "")).strip()

        if entry_type == "guest":
            uid = str(data.get("uid", "")).strip()
            password = str(data.get("password", "")).strip()

            if not uid or not password:
                return web.json_response({"status": "error", "error": "UID and Password are required"})

            if _admin_find_guest(uid, password):
                return web.json_response({
                    "status": "error",
                    "error": "This UID + Password already exists in the admin panel!"
                })

            entry = _admin_add_guest(uid, password, nickname=nickname, owner="admin")
            return web.json_response({"status": "ok", "id": entry["id"]})

        elif entry_type == "token":
            token = str(data.get("token", "")).strip()

            if not token:
                return web.json_response({"status": "error", "error": "Access token is required"})

            if _admin_find_token(token):
                return web.json_response({
                    "status": "error",
                    "error": "This Access Token already exists in the admin panel!"
                })

            entry = _admin_add_token(token, nickname=nickname, owner="admin")
            return web.json_response({"status": "ok", "id": entry["id"]})

        else:
            return web.json_response({"status": "error", "error": "Invalid entry type"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_admin_delete(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        entry_id = str(data.get("id", "")).strip()
        if not entry_id:
            return web.json_response({"status": "error", "error": "Missing entry id"})

        accounts = _load_admin_accounts()
        target = None
        for a in accounts:
            if a.get("id") == entry_id:
                target = a
                break

        if not target:
            return web.json_response({"status": "error", "error": "Entry not found"})

        uid = str(target.get("uid", "")).strip() if target.get("type") == "guest" else ""
        token = str(target.get("token", "")).strip() if target.get("type") == "token" else ""

        accounts = [a for a in accounts if a.get("id") != entry_id]
        _save_admin_accounts(accounts)

        for user_id in list(user_manager._states.keys()):
            state = user_manager.get_state(user_id)
            user_accounts = user_manager.load_user_accounts(user_id)
            new_list = []
            changed = False
            for acc in user_accounts:
                if uid and str(acc.get("uid")) == uid:
                    changed = True
                    continue
                if token and acc.get("token") == token:
                    changed = True
                    continue
                new_list.append(acc)
            if changed:
                user_manager.save_user_accounts(user_id, new_list)
                # Also mark as deleted for this user
                user_manager.mark_account_deleted(user_id, uid=uid, token=token)

            keys_to_try = []
            if uid:
                keys_to_try.append(uid)
            if token:
                keys_to_try.append(token[:10])

            for key in keys_to_try:
                if key in state.account_workers:
                    t = state.account_workers.pop(key)
                    if not t.done():
                        t.cancel()
                        try:
                            await asyncio.wait_for(t, timeout=2.0)
                        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                            pass

            for k in list(state.accounts.keys()):
                if uid and k == uid:
                    del state.accounts[k]
                elif token and k == token[:10]:
                    del state.accounts[k]

            if uid and uid in state.account_credentials:
                cred = state.account_credentials.pop(uid, None)
                aliases = [k for k, v in list(state.account_credentials.items()) if v is cred]
                for alias in aliases:
                    state.account_credentials.pop(alias, None)
                    if alias in state.account_workers:
                        t = state.account_workers.pop(alias)
                        if not t.done():
                            t.cancel()
            if token:
                cred_key = f"tok_{token[:20]}"
                if cred_key in state.account_credentials:
                    cred = state.account_credentials.pop(cred_key, None)
                    aliases = [k for k, v in list(state.account_credentials.items()) if v is cred]
                    for alias in aliases:
                        state.account_credentials.pop(alias, None)
                        if alias in state.account_workers:
                            t = state.account_workers.pop(alias)
                            if not t.done():
                                t.cancel()

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


# ==================== STARTUP ====================

async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/login", handle_login_page)
    app.router.add_post("/api/login", handle_api_login)
    app.router.add_get("/logout", handle_logout)
    app.router.add_get("/yasin-admin", handle_admin_page)
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)
    app.router.add_post("/api/reset", handle_reset_dashboard)
    app.router.add_get("/api/admin/list", handle_admin_list)
    app.router.add_post("/api/admin/add", handle_admin_add)
    app.router.add_post("/api/admin/delete", handle_admin_delete)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"\033[92m[+] Web Dashboard running on http://localhost:{port}\033[0m")
    print(f"\033[92m[+] Admin Panel running on http://localhost:{port}/admin\033[0m")