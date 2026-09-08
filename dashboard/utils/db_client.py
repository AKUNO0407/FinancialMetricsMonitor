from sqlalchemy import create_engine, text
import pandas as pd
import os

from dotenv import load_dotenv


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not configured."
    )

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


def read_sql(
    query: str,
    params: dict | None = None,
) -> pd.DataFrame:

    with engine.begin() as conn:

        return pd.read_sql(
            text(query),
            conn,
            params=params,
        )