from etl.notify import send_failure_email


def main():
    pipeline_run_id = "TEST-PIPELINE-2026-09-08"

    failed_jobs = [
        "test_job_1",
        "test_job_2",
    ]

    error_body = f"""
FinancialMetricsMonitor ETL pipeline completed with failures.

Pipeline run:
{pipeline_run_id}

Failed job(s):
{chr(10).join(f"- {job}" for job in failed_jobs)}

The pipeline continued running independent jobs.

This is an integration test only.
No ETL job was executed and no database data was modified.
"""

    send_failure_email(
        subject="[TEST] FinancialMetricsMonitor Pipeline Failure Alert",
        body=error_body,
    )

    print("Integration test alert email sent.")


if __name__ == "__main__":
    main()