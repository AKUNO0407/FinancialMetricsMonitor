from __future__ import annotations

import hashlib
import logging
import os
import re

import requests
import trafilatura
from sqlalchemy import text
from bs4 import BeautifulSoup

from etl.db import get_engine



logger = logging.getLogger(__name__)

FETCH_LIMIT = int(
    os.environ.get("ARTICLE_FETCH_LIMIT", "200")
)

MAX_ARTICLE_CHARS = int(
    os.environ.get("MAX_ARTICLE_CHARS", "30000")
)

REQUEST_TIMEOUT = int(
    os.environ.get("ARTICLE_FETCH_TIMEOUT", "20")
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    )
}


def _clean_text(text_content: str) -> str:
    if not text_content:
        return ""

    text_content = re.sub(
        r"\s+",
        " ",
        text_content,
    )

    return text_content.strip()


def _fetch_article(
    url: str,
    fallback_title: str | None = None,
) -> dict[str, str | None]:

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()
    html = response.text
    soup = BeautifulSoup(html, "html.parser")

    # --------------------------------------------------------
    # Extract title
    # Priority:
    # 1. og:title
    # 2. twitter:title
    # 3. <title>
    # 4. news_raw.headline fallback
    # --------------------------------------------------------

    title = None
    meta = soup.find(
        "meta",
        attrs={"property": "og:title"},
    )

    if meta and meta.get("content"):
        title = meta["content"].strip()

    if not title:
        meta = soup.find(
            "meta",
            attrs={"name": "twitter:title"},
        )
        if meta and meta.get("content"):
            title = meta["content"].strip()

    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(
                " ",
                strip=True,
            )

    if not title:
        title = fallback_title

    # --------------------------------------------------------
    # Extract author
    # Author is optional.
    # NULL is acceptable if unavailable.
    # --------------------------------------------------------

    author = None
    meta = soup.find(
        "meta",
        attrs={"name": "author"},
    )
    if meta and meta.get("content"):
        author = meta["content"].strip()
    if not author:
        meta = soup.find(
            "meta",
            attrs={"property": "article:author"},
        )
        if meta and meta.get("content"):
            author = meta["content"].strip()

    # --------------------------------------------------------
    # Extract article body
    # --------------------------------------------------------

    extracted = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        include_links=False,
        favor_precision=True,
    )

    if not extracted:
        raise ValueError(
            "Could not extract article content"
        )

    content = _clean_text(extracted)

    if not content:
        raise ValueError(
            "Article content is empty"
        )

    return {
        "title": title,
        "author": author,
        "article_text": content[:MAX_ARTICLE_CHARS],
    }



def _content_hash(content: str) -> str:
    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


def fetch_missing_articles(
    limit: int = FETCH_LIMIT,
) -> dict[str, int]:

    engine = get_engine()

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    nr.article_id,
                    nr.article_url,
                    nr.headline
                FROM news_raw nr
                LEFT JOIN news_articles na
                    ON nr.article_id = na.article_id
                WHERE (
                        na.article_id IS NULL
                        OR na.fetch_status IN ('FAILED')
                    )
                  AND cardinality(
                      nr.matched_tickers
                  ) > 0
                ORDER BY nr.published_date DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()

    success = 0
    failed = 0

    for row in rows:

        article_id = row["article_id"]
        article_url = row["article_url"]

        try:
            article_data = _fetch_article(
                article_url,
                fallback_title=row["headline"],
            )

            article_text = article_data["article_text"]
            article_title = article_data["title"]
            article_author = article_data["author"]

            content_hash = _content_hash(
                article_text
            )

            word_count = len(
                article_text.split()
            )

            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO news_articles (
                            article_id,
                            title,
                            author,
                            article_text,
                            content_fetched_at,
                            fetch_status,
                            content_hash,
                            word_count,
                            error_message
                        )
                        VALUES (
                            :article_id,
                            :title,
                            :author,
                            :article_text,
                            now(),
                            'SUCCESS',
                            :content_hash,
                            :word_count,
                            NULL
                        )
                        ON CONFLICT (article_id)
                        DO UPDATE SET
                            article_text = EXCLUDED.article_text,
                            title = EXCLUDED.title,
                            author = EXCLUDED.author,
                            content_fetched_at = now(),
                            fetch_status = 'SUCCESS',
                            content_hash = EXCLUDED.content_hash,
                            word_count = EXCLUDED.word_count,
                            error_message = NULL
                        """
                    ),
                    {
                        "article_id": article_id,
                        "title": article_title,
                        "author": article_author,
                        "article_text": article_text,
                        "content_hash": content_hash,
                        "word_count": word_count,
                    },
                )

            success += 1

        except requests.HTTPError as exc:

            status_code = (
                exc.response.status_code
                if exc.response is not None
                else None
            )

            fetch_status = (
                "BLOCKED"
                if status_code in {401, 403, 429}
                else "FAILED"
            )

            logger.warning(
                "Article fetch failed: %s status=%s",
                article_url,
                status_code,
            )

            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO news_articles (
                            article_id,
                            content_fetched_at,
                            fetch_status,
                            error_message
                        )
                        VALUES (
                            :article_id,
                            now(),
                            :fetch_status,
                            :error_message
                        )
                        ON CONFLICT (article_id)
                        DO UPDATE SET
                            content_fetched_at = now(),
                            fetch_status =
                                EXCLUDED.fetch_status,
                            error_message =
                                EXCLUDED.error_message
                        """
                    ),
                    {
                        "article_id": article_id,
                        "fetch_status": fetch_status,
                        "error_message": str(exc)[:1000],
                    },
                )

            failed += 1

        except Exception as exc:

            logger.warning(
                "Article extraction failed: %s: %s",
                article_url,
                exc,
            )

            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO news_articles (
                            article_id,
                            title,
                            content_fetched_at,
                            fetch_status,
                            error_message
                        )
                        VALUES (
                            :article_id,
                            :title,
                            now(),
                            'FAILED',
                            :error_message
                        )
                        ON CONFLICT (article_id)
                        DO UPDATE SET
                            content_fetched_at = now(),
                            title = EXCLUDED.title,
                            fetch_status = 'FAILED',
                            error_message = EXCLUDED.error_message
                        """
                    ),
                    {
                        "article_id": article_id,   
                        "title": article_title,
                        "fetch_status": fetch_status,
                        "error_message": str(exc)[:1000],
                    },
                )

            failed += 1

    logger.info(
        "Article fetch completed: success=%s failed=%s",
        success,
        failed,
    )

    return {
        "success": success,
        "failed": failed,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO
    )

    fetch_missing_articles()