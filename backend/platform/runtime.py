import asyncio
import contextlib
import logging
import os
import time

logger = logging.getLogger("tracy.worker")


class SingleWorkerLock:
    """OS-managed lock is released even after a crash; prevents unsafe startup recovery."""

    def __init__(self, path):
        self.path, self.file = path, None

    def acquire(self):
        self.file = open(str(self.path) + ".runtime.lock", "a+b")
        self.file.seek(0)
        if os.fstat(self.file.fileno()).st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise RuntimeError(
                "Another Tracy worker is using this database. Run exactly one worker."
            ) from exc

    def release(self):
        if self.file:
            self.file.close()
            self.file = None


class Reconciler:
    def __init__(self, db, actions, interval):
        self.db, self.actions, self.interval = db, actions, interval
        self.task = None
        self.stopping = False
        self.last_tick_at = None
        self.last_error_at = None

    async def tick(self):
        now = int(time.time())
        with self.db.connect() as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    """SELECT action_id FROM actions WHERE status='PENDING'
                      AND next_check_at<=? ORDER BY next_check_at,created_at LIMIT 20""",
                    (now,),
                )
            ]
        for action_id in ids:
            try:
                await self.actions.reconcile(action_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.last_error_at = int(time.time())
                with self.db.connect(write=True) as conn:
                    conn.execute(
                        "UPDATE actions SET next_check_at=? WHERE action_id=? AND receipt_id IS NULL",
                        (now + 60, action_id),
                    )
                logger.exception("Reconciliation failed for %s", action_id)
        if getattr(self, "control", None):
            await self.control.tick()
        if getattr(self, "marketplace", None):
            await self.marketplace.tick()
        self.last_tick_at = int(time.time())

    async def run(self):
        while not self.stopping:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.last_error_at = int(time.time())
                logger.exception("Reconciliation loop failed")
            if not self.stopping:
                await asyncio.sleep(self.interval)

    def start(self):
        self.task = asyncio.create_task(self.run(), name="tracy-reconciler")

    async def stop(self):
        self.stopping = True
        if self.task:
            # Allow a dispatched transfer to settle before shutdown; crash recovery covers timeouts.
            try:
                await asyncio.wait_for(
                    asyncio.shield(self.task), timeout=0.1 if not getattr(self, "marketplace", None) else 30
                )
            except asyncio.TimeoutError:
                self.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.task
