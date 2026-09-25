from sqlalchemy import bindparam, create_engine, text
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


def read_sql(query, params=None, expanding_params=None):
    stmt = text(query)

    if expanding_params:
        for param_name in expanding_params:
            stmt = stmt.bindparams(
                bindparam(param_name, expanding=True)
            )

    with engine.begin() as conn:
        return pd.read_sql(
            stmt,
            conn,
            params=params,
        )
