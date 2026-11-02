
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape

import requests
from bs4 import BeautifulSoup


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
    if not value:
        return ""

    soup = BeautifulSoup(str(value), "html.parser")

    for element in soup(["script", "style"]):
        element.decompose()

    return re.sub(
        r"\s+",
        " ",
        unescape(soup.get_text(" ", strip=True)),
    ).strip()


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
    """Отримує сторінку пошуку вакансій із повторними спробами."""
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
            if attempt == MAX_RETRIES - 1:
                raise RateLimitError(
                    "LinkedIn повертає HTTP 429 після кількох спроб. "
                    "Повтори пізніше або використовуй джерело "
                    "з дозволеним API-доступом."
                )

            time.sleep(_retry_delay(response, attempt))
            continue

        response.raise_for_status()
        return response.text

    raise RateLimitError("Не вдалося отримати сторінку LinkedIn.")


def fetch_linkedin_jobs(query, country="United States", start=0):
    """Отримує список вакансій із публічної сторінки пошуку LinkedIn."""
    url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    params = {
        "keywords": query,
        "location": country,
        "start": start,
    }

    html = _get_linkedin_page(url, params)
    soup = BeautifulSoup(html, "html.parser")

    jobs = []

    for card in soup.select("li"):
        link = card.select_one("a.base-card__full-link")

        if not link:
            continue

        job_url = link.get("href", "").split("?")[0]
        match = re.search(r"/view/(?:.*?-)?(\d+)/?$", job_url)

        if not match:
            continue

        job_id = match.group(1)

        title_element = card.select_one(".base-search-card__title")
        company_element = card.select_one(".base-search-card__subtitle")
        location_element = card.select_one(".job-search-card__location")
        date_element = card.select_one("time")

        jobs.append({
            "job_id": job_id,
            "title": clean_html(
                title_element.get_text(" ") if title_element else ""
            ),
            "company": clean_html(
                company_element.get_text(" ") if company_element else ""
            ),
            "location": clean_html(
                location_element.get_text(" ") if location_element else ""
            ),
            "job_url": job_url,
            "published_at": date_element.get("datetime") if date_element else None,
        })

    return jobs


def _extract_jsonld_objects(soup):
    """Повертає об'єкти JSON-LD зі сторінки."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue

        if isinstance(data, list):
            objects = data
        elif isinstance(data, dict):
            graph = data.get("@graph")
            objects = graph if isinstance(graph, list) else [data]
        else:
            continue

        for item in objects:
            if not isinstance(item, dict):
                continue

            item_type = item.get("@type", [])

            if isinstance(item_type, str):
                item_type = [item_type]

            if "JobPosting" in item_type:
                yield item


def _extract_company(company):
    """Витягує доступні дані компанії."""
    result = {
        "company_description": "",
        "company_industry": "",
        "company_website": "",
        "company_linkedin_url": "",
    }

    if not isinstance(company, dict):
        return result

    result["company_description"] = clean_html(
        company.get("description", "")
    )

    industry = company.get("industry", "")

    if isinstance(industry, list):
        industry = ", ".join(map(str, industry))

    result["company_industry"] = clean_html(industry)

    website = company.get("url", "")
    result["company_website"] = (
        website if isinstance(website, str) else ""
    )

    same_as = company.get("sameAs", "")

    if isinstance(same_as, list):
        same_as = next(
            (
                url for url in same_as
                if isinstance(url, str) and "linkedin.com" in url
            ),
            "",
        )

    result["company_linkedin_url"] = (
        same_as if isinstance(same_as, str) else ""
    )

    return result


def fetch_linkedin_job_details(job_url):
    """Отримує доступні деталі окремої вакансії."""
    response = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                job_url,
                timeout=20,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )

            if response.status_code == 429:
                if attempt == MAX_RETRIES - 1:
                    raise RateLimitError(
                        "LinkedIn повертає HTTP 429. "
                        "Зупинено повторні запити."
                    )

                time.sleep(_retry_delay(response, attempt))
                continue

            response.raise_for_status()
            break

        except requests.RequestException:
            if attempt == MAX_RETRIES - 1:
                raise

            time.sleep(min(5 * (2 ** attempt), 30))

    else:
        raise RateLimitError("Не вдалося отримати сторінку вакансії.")

    soup = BeautifulSoup(response.text, "html.parser")

    result = {
        "description": "",
        "employment_type": "",
        "seniority": "",
        "company_description": "",
        "company_industry": "",
        "company_website": "",
        "company_linkedin_url": "",
    }

    for item in _extract_jsonld_objects(soup):
        description = item.get("description", "")

        if description:
            result["description"] = clean_html(description)

        employment_type = item.get("employmentType", "")

        if isinstance(employment_type, list):
            employment_type = ", ".join(map(str, employment_type))

        result["employment_type"] = str(employment_type or "")

        seniority = item.get("experienceRequirements", "")

        if isinstance(seniority, dict):
            seniority = seniority.get("description", "")

        if isinstance(seniority, list):
            seniority = ", ".join(
                str(
                    value.get("description", value)
                    if isinstance(value, dict)
                    else value
                )
                for value in seniority
            )

        result["seniority"] = clean_html(seniority)

        result.update(
            _extract_company(item.get("hiringOrganization", {}))
        )

        if result["description"]:
            break

    if not result["description"]:
        element = soup.select_one(".show-more-less-html__markup")

        if element:
            result["description"] = clean_html(
                element.get_text(" ", strip=True)
            )
    # Додатково отримуємо Seniority з HTML-блоку LinkedIn.
    if not result["seniority"]:
        criteria = soup.select(
            ".description__job-criteria-item"
        )

        for item in criteria:
            label = item.select_one(
                ".description__job-criteria-subheader"
            )

            value = item.select_one(
                ".description__job-criteria-text"
            )

            if not label or not value:
                continue

            label_text = clean_html(label.get_text(" ", strip=True)).lower()
            value_text = clean_html(value.get_text(" ", strip=True))

            if label_text in ("seniority level", "рівень посади"):
                result["seniority"] = value_text
                break

    return result



def fetch_linkedin_company_details(company_url):
    """
    Отримує доступну публічну інформацію зі сторінки компанії LinkedIn.
    """

    result = {
        "company_description": "",
        "company_industry": "",
        "company_website": "",
        "company_linkedin_url": company_url or "",
        "company_employee_count": "",
    }

    if not company_url:
        return result

    if not re.match(
        r"^https?://(www\.)?linkedin\.com/company/",
        company_url,
        re.IGNORECASE,
    ):
        return result

    response = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                company_url,
                timeout=20,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )

            if response.status_code == 429:
                if attempt == MAX_RETRIES - 1:
                    raise RateLimitError(
                        "LinkedIn обмежив частоту запитів (HTTP 429)."
                    )

                time.sleep(_retry_delay(response, attempt))
                continue

            response.raise_for_status()
            break

        except requests.RequestException:
            if attempt == MAX_RETRIES - 1:
                raise

            time.sleep(min(5 * (2 ** attempt), 30))

    if response is None:
        return result

    soup = BeautifulSoup(response.text, "html.parser")

    # Допоміжна функція для очищення значень.
    def clean_value(value):
        if not value:
            return ""

        return clean_html(unescape(str(value)))

    # 1. Опис із метатегів.
    description_tag = (
        soup.find("meta", property="og:description")
        or soup.find("meta", attrs={"name": "description"})
    )

    if description_tag:
        result["company_description"] = clean_value(
            description_tag.get("content", "")
        )

    # 2. Допоміжний пошук полів у HTML-блоці About.
    # LinkedIn часто використовує структуру dt/dd:
    # dt = назва поля, dd = його значення.
    for dt in soup.find_all("dt"):
        label = clean_value(dt.get_text(" ", strip=True)).lower()

        dd = dt.find_next_sibling("dd")

        if not dd:
            continue

        value = clean_value(dd.get_text(" ", strip=True))

        if not value:
            continue

        if label in ("industry", "індустрія", "галузь"):
            if not result["company_industry"]:
                result["company_industry"] = value

        
        elif label in ("website", "вебсайт", "веб-сайт"):
            if not result["company_website"]:
                link = dd.find("a", href=True)

                if link:
                    href = link["href"].strip()

            # LinkedIn redirect URL
                    if "linkedin.com/redir/redirect" in href:
                        from urllib.parse import urlparse, parse_qs

                        parsed_url = urlparse(href)
                        params = parse_qs(parsed_url.query)
                        website = params.get("url", [""])[0]
                    else:
                        website = href

                    website = unescape(website).strip()

                    if (
                        website.startswith(("http://", "https://"))
                        and "linkedin.com" not in urlparse(website).netloc.lower()
                    ):
                        result["company_website"] = website

    # 3. Додатковий пошук офіційного сайту серед усіх посилань.
    if not result["company_website"]:
        for link in soup.find_all("a", href=True):
            website = link["href"].strip()

            if (
                website.startswith(("http://", "https://"))
                and "linkedin.com" not in website.lower()
                and "lnkd.in" not in website.lower()
            ):
                text = clean_value(
                    link.get_text(" ", strip=True)
                ).lower()

                if any(
                    word in text
                    for word in ("website", "visit website", "official site")
                ):
                    result["company_website"] = website
                    break
                
    # 3. Обробка JSON-LD, включно з @graph.
    def extract_objects(data):
        if isinstance(data, list):
            for item in data:
                yield from extract_objects(item)

        elif isinstance(data, dict):
            yield data

            graph = data.get("@graph")

            if isinstance(graph, (list, dict)):
                yield from extract_objects(graph)

    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue

        for item in extract_objects(data):
            item_type = item.get("@type", [])

            if isinstance(item_type, str):
                item_type = [item_type]

            if not any(
                value in ("Organization", "Corporation", "LocalBusiness")
                for value in item_type
            ):
                continue

            # Опис.
            if not result["company_description"]:
                result["company_description"] = clean_value(
                    item.get("description", "")
                )

            # Індустрія.
            if not result["company_industry"]:
                industry = item.get("industry", "")

                if isinstance(industry, list):
                    industry = ", ".join(map(str, industry))

                result["company_industry"] = clean_value(industry)

            # Офіційний сайт.
            if not result["company_website"]:
                website = item.get("url", "")

                if isinstance(website, dict):
                    website = website.get("url", "")

                if (
                    isinstance(website, str)
                    and website.startswith("http")
                    and "linkedin.com" not in website.lower()
                ):
                    result["company_website"] = website

            # Кількість працівників.
            if not result["company_employee_count"]:
                employees = item.get("numberOfEmployees", "")

                if isinstance(employees, dict):
                    employees = employees.get("value", "")

                if employees:
                    result["company_employee_count"] = str(employees)

    return result
