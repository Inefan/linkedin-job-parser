import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape

import requests


USER_AGENT = "Mozilla/5.0 (compatible; JobResearchParser/1.0)"
MAX_RETRIES = 3


class RateLimitError(Exception):
    """Джерело обмежило частоту запитів."""


def fetch_json(url):
    response = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return response.json()


def fetch_posts():
    """Застаріле тестове джерело. Не використовувати для реальних вакансій."""
    data = fetch_json("https://jsonplaceholder.typicode.com/posts")

    return [
        {
            "title": item["title"],
            "company": f"Test Company {item['userId']}",
            "job_url": f"https://example.com/posts/{item['id']}",
        }
        for item in data
    ]


def clean_html(value):
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _retry_delay(response, attempt):
    """Визначає паузу за Retry-After, якщо її передав сервер."""
    retry_after = response.headers.get("Retry-After")

    if retry_after:
        try:
            return max(0, float(retry_after))
        except ValueError:
            try:
                retry_date = parsedate_to_datetime(retry_after)
                if retry_date.tzinfo is None:
                    retry_date = retry_date.replace(tzinfo=timezone.utc)
                return max(
                    0,
                    (retry_date - datetime.now(timezone.utc)).total_seconds(),
                )
            except (TypeError, ValueError, OverflowError):
                pass

    return min(30 * (2 ** attempt), 300)


def _get_linkedin_page(url, params):
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=20,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        except requests.RequestException:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(min(5 * (2 ** attempt), 30))
            continue

        if response.status_code == 429:
            delay = _retry_delay(response, attempt)

            if attempt == MAX_RETRIES - 1:
                raise RateLimitError(
                    "LinkedIn повертає HTTP 429 після кількох спроб. "
                    "Зупини збір і повтори пізніше або використовуй "
                    "джерело з дозволеним API-доступом."
                )

            # Не повторюємо запит негайно — дотримуємося Retry-After.
            time.sleep(delay)
            continue

        if response.status_code in (401, 403):
            response.raise_for_status()

        response.raise_for_status()
        return response.text

    raise RateLimitError("Не вдалося отримати сторінку LinkedIn.")


def fetch_linkedin_jobs(query, country="United States", start=0):
    """Отримує вакансії з публічних результатів пошуку LinkedIn."""
    url = (
        "https://www.linkedin.com/jobs-guest/"
        "jobs/api/seeMoreJobPostings/search"
    )

    params = {
        "keywords": query,
        "location": country,
        "start": start,
    }

    html = _get_linkedin_page(url, params)

    cards = re.split(
        r'data-entity-urn="urn:li:jobPosting:',
        html,
    )[1:]

    jobs = []

    for card in cards:
        job_id_match = re.match(r'(\d+)"', card)

        title_match = re.search(
            r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>(.*?)</h3>',
            card,
            re.S,
        )

        company_match = re.search(
            r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>',
            card,
            re.S,
        )

        location_match = re.search(
            r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>(.*?)</span>',
            card,
            re.S,
        )

        url_match = re.search(
            r'<a[^>]*class="[^"]*base-card__full-link[^"]*"[^>]*href="([^"]+)"',
            card,
            re.S,
        )

        date_match = re.search(
            r'<time[^>]*datetime="([^"]+)"',
            card,
        )

        if not all(
            [job_id_match, title_match, company_match, url_match]
        ):
            continue

        jobs.append(
            {
                "job_id": job_id_match.group(1),
                "title": clean_html(title_match.group(1)),
                "company": clean_html(company_match.group(1)),
                "location": (
                    clean_html(location_match.group(1))
                    if location_match
                    else ""
                ),
                "job_url": unescape(url_match.group(1)).split("?")[0],
                "published_at": (
                    date_match.group(1) if date_match else None
                ),
            }
        )

    return jobs


def fetch_linkedin_job_details(job_url):
    """Отримує доступні деталі окремої вакансії."""
    response = requests.get(
        job_url,
        timeout=20,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()

    html = response.text

    description_match = re.search(
        r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
        html,
        re.S,
    )

    description = (
        clean_html(description_match.group(1))
        if description_match
        else ""
    )

    return {"description": description}
