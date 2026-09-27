# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Professional Web Dashboard & Real-Time EXP Tracker
Embedded Async Web Server (aiohttp)
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional
from aiohttp import web

# Global bot state shared between Main.py and Web Dashboard
class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}

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
            # Update target level if provided and account not yet completed
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
        """Check if current level >= target level"""
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


bot_state = BotState()


# ==================== HTTP HANDLERS ====================

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")
ACCOUNTS_FILE = "accounts.json"


async def handle_index(request: web.Request) -> web.Response:
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "<h1>templates/index.html not found!</h1>"
    return web.Response(text=content, content_type="text/html", charset="utf-8")


async def handle_get_stats(request: web.Request) -> web.Response:
    accounts_data = list(bot_state.accounts.values())
    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)
    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "total_gained_exp": bot_state.total_gained_exp,
        "accounts": accounts_data,
        "logs": bot_state.logs[-60:],
        "uptime": int(time.time() - bot_state.start_time)
    })


async def handle_add_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        existing = []
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        # Validate target level
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
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
            existing.append({"uid": uid, "password": pwd, "target_level": target_level})
            bot_state.set_target_level(uid, target_level)
        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token is required"})
            existing = [acc for acc in existing if acc.get("token") != token]
            existing.append({"token": token, "target_level": target_level})
            # For token accounts, the key is token prefix (matches main.py worker key)
            bot_state.set_target_level(token[:10], target_level)
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        bot_state.log(
            f"New account added (Target Lv {target_level}): {data.get('uid') or 'Token'}",
            "success"
        )

        # Trigger dynamic worker launch
        if "on_account_added" in bot_state.refresh_callbacks:
            payload = dict(data)
            payload["target_level"] = target_level
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](payload))

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        token = data.get("token")
        token = str(token).strip() if token else ""

        # Remove from accounts.json
        existing = []
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)

        if uid:
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
        if token:
            existing = [acc for acc in existing if acc.get("token") != token]

        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        # Cancel worker by UID
        cancelled = False
        keys_to_try = []
        if uid:
            keys_to_try.append(uid)
        if token:
            keys_to_try.append(token[:10])

        for key in keys_to_try:
            if key in bot_state.account_workers:
                task = bot_state.account_workers.pop(key)
                if not task.done():
                    task.cancel()
                    cancelled = True

        # Also cancel by scanning credentials mapping
        if uid and uid in bot_state.account_credentials:
            cred = bot_state.account_credentials.pop(uid, None)
            # Remove all alias entries for same credential object
            aliases = [k for k, v in list(bot_state.account_credentials.items()) if v is cred]
            for alias in aliases:
                bot_state.account_credentials.pop(alias, None)
                if alias in bot_state.account_workers:
                    t = bot_state.account_workers.pop(alias)
                    if not t.done():
                        t.cancel()
                        cancelled = True

        if token:
            cred_key = f"tok_{token[:20]}"
            if cred_key in bot_state.account_credentials:
                cred = bot_state.account_credentials.pop(cred_key, None)
                aliases = [k for k, v in list(bot_state.account_credentials.items()) if v is cred]
                for alias in aliases:
                    bot_state.account_credentials.pop(alias, None)
                    if alias in bot_state.account_workers:
                        t = bot_state.account_workers.pop(alias)
                        if not t.done():
                            t.cancel()
                            cancelled = True

        # Remove account from bot_state.accounts view
        for key in list(bot_state.accounts.keys()):
            if uid and key == uid:
                del bot_state.accounts[key]
                cancelled = True
            elif token and key == token[:10]:
                del bot_state.accounts[key]
                cancelled = True

        bot_state.log(f"Account {uid or token[:10]} removed from rotation. Worker stopped.", "warning", uid or None)
        return web.json_response({"status": "ok", "cancelled": cancelled})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"\033[92m[+] Web Dashboard running on http://localhost:{port}\033[0m")