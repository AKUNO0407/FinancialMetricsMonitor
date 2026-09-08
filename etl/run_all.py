# etl/run_all.py

from __future__ import annotations

import logging
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from etl.db import get_engine


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)

engine = get_engine()


JOBS = [
    ("watchlist_manual", "etl.watchlist_manual"),
    ("prices", "etl.prices"),
    ("company_metadata", "etl.company_metadata"),
    ("earnings_calendar", "etl.earnings_calendar"),
    ("macro_calendar", "etl.macro_calendar"),
    ("news_scraper", "etl.news_scraper"),
    ("news_article_fetcher", "etl.news_article_fetcher"),
    ("news_summary", "etl.news_summary"),
]


def _utcnow():
    return datetime.now(timezone.utc)


def _start_job_run(
    pipeline_run_id: UUID,
    job_name: str,
) -> int:
    """
    Create a job_runs record for one ETL job.
    """

    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO job_runs (
                    pipeline_run_id,
                    job_name,
                    started_at,
                    status
                )
                VALUES (
                    :pipeline_run_id,
                    :job_name,
                    :started_at,
                    'RUNNING'
                )
                RETURNING job_run_id
                """
            ),
            {
                "pipeline_run_id": pipeline_run_id,
                "job_name": job_name,
                "started_at": _utcnow(),
            },
        )

        return int(result.scalar_one())


def _finish_job_run(
    job_run_id: int,
    status: str,
    error_message: str | None = None,
):
    """
    Update the existing job_runs record.
    """

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE job_runs
                SET
                    finished_at = :finished_at,
                    status = :status,
                    error_message = :error_message
                WHERE job_run_id = :job_run_id
                """
            ),
            {
                "job_run_id": job_run_id,
                "finished_at": _utcnow(),
                "status": status,
                "error_message": error_message,
            },
        )


def _run_job(
    pipeline_run_id: UUID,
    job_name: str,
    module_name: str,
) -> bool:

    logger.info(
        "Starting job: %s",
        job_name,
    )

    job_run_id = _start_job_run(
        pipeline_run_id=pipeline_run_id,
        job_name=job_name,
    )

    logger.info(
        "pipeline_run_id=%s | job_run_id=%s | %s",
        pipeline_run_id,
        job_run_id,
        job_name,
    )

    try:

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                module_name,
            ],
            check=False,
        )

        if result.returncode != 0:

            error_message = (
                f"{job_name} exited with "
                f"return code {result.returncode}"
            )

            _finish_job_run(
                job_run_id=job_run_id,
                status="FAILED",
                error_message=error_message,
            )

            logger.error(
                "FAILED: %s",
                job_name,
            )

            return False

        _finish_job_run(
            job_run_id=job_run_id,
            status="SUCCESS",
        )

        logger.info(
            "SUCCESS: %s",
            job_name,
        )

        return True

    except Exception as exc:

        error_message = (
            f"{type(exc).__name__}: {exc}"
        )

        _finish_job_run(
            job_run_id=job_run_id,
            status="FAILED",
            error_message=error_message,
        )

        logger.exception(
            "FAILED: %s",
            job_name,
        )

        return False


def main():

    pipeline_run_id = uuid.uuid4()

    logger.info(
        "========================================"
    )

    logger.info(
        "Starting FinancialMetricsMonitor ETL"
    )

    logger.info(
        "pipeline_run_id=%s",
        pipeline_run_id,
    )

    logger.info(
        "========================================"
    )

    failed_jobs = []

    for job_name, module_name in JOBS:

        success = _run_job(
            pipeline_run_id=pipeline_run_id,
            job_name=job_name,
            module_name=module_name,
        )

        if not success:

            failed_jobs.append(job_name)

            # IMPORTANT:
            # Do NOT fail fast.
            #
            # A failure in one ticker/job should not prevent
            # independent ETL jobs from running.
            logger.warning(
                "Job failed but pipeline will continue: %s",
                job_name,
            )

    logger.info(
        "========================================"
    )

    if failed_jobs:

        logger.error(
            "ETL pipeline completed with failures."
        )

        logger.error(
            "pipeline_run_id=%s",
            pipeline_run_id,
        )

        logger.error(
            "Failed jobs: %s",
            ", ".join(failed_jobs),
        )

        # Send failure notification.
        try:

            from etl.notify import send_failure_email

            error_body = f"""
FinancialMetricsMonitor ETL pipeline completed with failures.

Pipeline run:
{pipeline_run_id}

Failed job(s):
{chr(10).join(f"- {job}" for job in failed_jobs)}

The pipeline continued running independent jobs.

Please check the job_runs table and ETL logs.
"""

            send_failure_email(
                subject=(
                    "[ALERT] FinancialMetricsMonitor "
                    "ETL Pipeline Completed With Failures"
                ),
                body=error_body,
            )

            logger.info(
                "Failure alert email sent."
            )

        except Exception:

            logger.exception(
                "Failed to send failure alert email."
            )

        return 1

    logger.info(
        "ETL pipeline completed successfully."
    )

    logger.info(
        "pipeline_run_id=%s",
        pipeline_run_id,
    )

    logger.info(
        "========================================"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())