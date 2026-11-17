"""Durable, user-scoped receipts for iOS background result downloads."""
from __future__ import annotations

import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from aiohttp import web

from .filesystem import resolve


def receipt_key(token):
    try:
        token = str(uuid.UUID(token))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Invalid share receipt")
    return hashlib.sha256(token.encode()).hexdigest()


class ShareRuns:
    def __init__(self, database: Path):
        self.database = database

    def connect(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS runs (
            owner TEXT, receipt TEXT, output TEXT, job TEXT, state TEXT, file TEXT,
            created REAL, PRIMARY KEY(owner, receipt))""")
        return db

    async def submit(self, owner, request, queue):
        body = await request.json()
        if "prompt_id" in body:
            raise ValueError("Shared jobs use a server-assigned prompt ID.")
        key = receipt_key(body.get("nodeui_receipt"))
        output = body.get("nodeui_output")
        if not isinstance(output, str) or body.get("prompt", {}).get(output, {}).get("class_type") != "NodeUIReturnImage":
            raise ValueError("Choose a workflow with a connected Return Image to NodeUI node.")
        # Persist before invoking ComfyUI. A lost HTTP response must never queue twice.
        with closing(self.connect()) as db:
            created = db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,NULL,'submitting',NULL,?)",
                                 (owner, key, output, time.time())).rowcount
            if not created:
                row = db.execute("SELECT job,state FROM runs WHERE owner=? AND receipt=?", (owner, key)).fetchone()
                if row["job"]:
                    return web.json_response({"prompt_id": row["job"]})
                if row["state"] == "rejected":
                    db.execute("UPDATE runs SET state='submitting',output=? WHERE owner=? AND receipt=?", (output, owner, key))
                else:
                    raise web.HTTPConflict(text="This submission was already attempted. Check execution history.")
            response = await queue(request)
            payload = json.loads(response.body)
            job = payload.get("prompt_id")
            db.execute("UPDATE runs SET job=?,state=? WHERE owner=? AND receipt=?",
                       (job, "queued" if job else "rejected", owner, key))
            if job and output in (payload.get("node_errors") or {}):
                db.execute("UPDATE runs SET state='failed' WHERE owner=? AND receipt=?", (owner, key))
            return response

    async def result(self, owner, token, queue, output_root, wait_seconds=1500):
        key = receipt_key(token)
        deadline = time.monotonic() + wait_seconds
        with closing(self.connect()) as db:
            while True:
                row = db.execute("SELECT * FROM runs WHERE owner=? AND receipt=?", (owner, key)).fetchone()
                if not row:
                    raise web.HTTPNotFound(text="This share receipt does not exist on this server.")
                if row["state"] in {"failed", "rejected"}:
                    raise web.HTTPUnprocessableEntity(text="This shared workflow failed. Check execution history.")
                if row["state"] == "submitting" and time.time() - row["created"] > 300:
                    raise web.HTTPGone(text="Submission could not be confirmed. Check execution history before starting another run.")
                filename = row["file"]
                if not filename and row["job"]:
                    history = queue.get_history(prompt_id=row["job"]).get(row["job"])
                    if history:
                        status = history.get("status") or {}
                        images = (history.get("outputs", {}).get(row["output"]) or {}).get("images") or []
                        if status.get("status_str") != "success" or not images or images[0].get("type") != "output":
                            db.execute("UPDATE runs SET state='failed' WHERE owner=? AND receipt=?", (owner, key))
                            raise web.HTTPUnprocessableEntity(text="The run did not return an image.")
                        first = images[0]
                        filename = "/".join(part for part in (first.get("subfolder"), first["filename"]) if part)
                        resolve(output_root, filename)
                        db.execute("UPDATE runs SET file=? WHERE owner=? AND receipt=?", (filename, owner, key))
                    else:
                        running, pending = queue.get_current_queue_volatile() if hasattr(queue, "get_current_queue_volatile") else queue.get_current_queue()
                        if not any(item[1] == row["job"] for item in (*running, *pending)):
                            # A worker can finish between the first history read and the queue snapshot.
                            if queue.get_history(prompt_id=row["job"]).get(row["job"]):
                                continue
                            raise web.HTTPGone(text="The run was cancelled or is no longer in ComfyUI history.")
                if filename:
                    return web.FileResponse(resolve(output_root, filename),
                                            headers={"Content-Type": "image/png", "Cache-Control": "private, no-store"})
                if time.monotonic() >= deadline:
                    return web.Response(status=202, headers={"Retry-After": "10"})
                await asyncio.sleep(1)
