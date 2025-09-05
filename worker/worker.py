# worker/worker.py
import sys, os, time
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from brs.models import SessionLocal, Job
from brs.engine import run_job


def main():
    print("[worker] starting up…")
    while True:
        db = SessionLocal()
        try:
            # look for the next pending job
            job = db.query(Job).filter_by(status="pending").first()
            if job:
                print(f"[worker] found job {job.id} for user {job.user_id}")
                job.status = "running"
                db.commit()

                try:
                    run_job(job, db)
                    job.status = "done"
                except Exception as e:
                    print(f"[worker] job {job.id} failed: {e}")
                    job.status = "failed"
                    job.error = str(e)
                finally:
                    db.commit()
            else:
                time.sleep(10)  # idle wait
        finally:
            db.close()


if __name__ == "__main__":
    main()
