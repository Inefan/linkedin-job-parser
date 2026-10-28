

import re
from html import unescape

import requests


def fetch_json(url):
    response = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "LinkedInJobsParser/1.0"},
    )
    response.raise_for_status()
    return response.json()


def fetch_posts():
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
    """Видаляє HTML-теги та зайві пробіли."""
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def fetch_linkedin_jobs(query, country="United States", start=0):
    """Отримує базову інформацію про вакансії з результатів пошуку."""
    url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    params = {
        "keywords": query,
        "location": country,
        "start": start,
    }

    response = requests.get(
        url,
        params=params,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()

    html = response.text
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
                "job_url": unescape(
                    url_match.group(1)
                ).split("?")[0],
                "published_at": (
                    date_match.group(1)
                    if date_match
                    else None
                ),
            }
        )

    return jobs


def fetch_linkedin_job_details(job_url):
    """Отримує доступні деталі окремої вакансії."""
    response = requests.get(
        job_url,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
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

    return {
        "description": description,
    }
