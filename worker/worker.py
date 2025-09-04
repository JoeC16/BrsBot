import asyncio, traceback
from datetime import datetime
from sqlalchemy import select
from brs.models import SessionLocal, Job
from brs.security import decrypt
from brs.engine import run_swapper_job
from brs.config import POLL_SECONDS

RUNNING = {}  # job_id -> asyncio.Task

def job_to_cfg(j: Job) -> dict:
    return {
        "club_slug": j.club_slug,
        "course_id": j.course_id,
        "username": decrypt(j.member_username_enc),
        "password": decrypt(j.member_password_enc),
        "target_date": j.target_date,
        "earliest": j.earliest,
        "latest": j.latest,
        "current_time": j.current_time,
        "player_ids": j.player_ids(),
        "required_seats": j.required_seats,
        "accept_at_least": j.accept_at_least,
        "poll_seconds": j.poll_seconds,
        "max_minutes": j.max_minutes,
    }

async def run_one(job_id: int):
    db = SessionLocal()
    try:
        j = db.get(Job, job_id)
        if not j: return
        cfg = job_to_cfg(j)
        def log(s): print(f"[job {job_id}] {s}")
        log("starting")
        j.status = "running"; db.commit()

        result = await run_swapper_job(cfg, log=log)
        log(f"finished: {result}")
        j.status = result.get("status", "failed")
        j.finished_at = datetime.utcnow()
        j.last_log = str(result)
        db.commit()
    except Exception as e:
        print(f"[job {job_id}] crashed: {e}\n{traceback.format_exc()}")
        try:
            j = db.get(Job, job_id)
            if j:
                j.status = "failed"
                j.finished_at = datetime.utcnow()
                j.last_log = f"crash: {e}"
                db.commit()
        except: pass
    finally:
        db.close()
        RUNNING.pop(job_id, None)

async def scheduler_loop():
    while True:
        db = SessionLocal()
        try:
            jobs = db.scalars(select(Job).where(Job.status.in_(("active","running")))).all()
        finally:
            db.close()

        # start jobs not already running
        for j in jobs:
            if j.id not in RUNNING:
                RUNNING[j.id] = asyncio.create_task(run_one(j.id))

        # cleanup finished tasks
        done = [jid for jid, t in RUNNING.items() if t.done()]
        for jid in done:
            RUNNING.pop(jid, None)

        await asyncio.sleep(POLL_SECONDS)

def main():
    print("[worker] booting…")
    asyncio.run(scheduler_loop())

if __name__ == "__main__":
    main()
