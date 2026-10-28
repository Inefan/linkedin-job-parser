
import json
from datetime import date, datetime, time

from django.db import IntegrityError, transaction
from django.utils import timezone

from jobs.fetcher import fetch_json
from jobs.models import Company, Job


BATCH_SIZE = 500


def parse_published_at(value):
    """Перетворює дату публікації на datetime."""
    if not value:
        return None

    try:
        if isinstance(value, datetime):
            parsed_datetime = value
        elif isinstance(value, date):
            parsed_datetime = datetime.combine(value, time.min)
        else:
            parsed_date = date.fromisoformat(str(value)[:10])
            parsed_datetime = datetime.combine(parsed_date, time.min)

        if timezone.is_naive(parsed_datetime):
            return timezone.make_aware(parsed_datetime)

        return parsed_datetime

    except (ValueError, TypeError):
        return None


def _prepare_jobs(data):
    """Перевіряє вхідні записи та прибирає дублікати."""
    by_url = {}

    for item in data:
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        company_name = item.get("company")
        job_url = item.get("job_url")

        if not all(isinstance(value, str) for value in (
            title, company_name, job_url
        )):
            continue

        title = title.strip()
        company_name = company_name.strip()
        job_url = job_url.strip()

        if not title or not company_name or not job_url:
            continue

        job_id = str(
            item.get("job_id") or job_url.rstrip("/").split("/")[-1]
        ).strip()

        if not job_id:
            continue

        values = {
            "job_id": job_id,
            "title": title,
            "job_url": job_url,
            "company_name": company_name,
        }

        for field in (
            "location",
            "description",
            "employment_type",
            "seniority",
        ):
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                values[field] = value.strip()

        published_at = parse_published_at(item.get("published_at"))
        if published_at:
            values["published_at"] = published_at

        # Для однакового URL залишаємо останній запис.
        by_url[job_url] = values

    # Один job_id не може належати різним URL.
    by_id = {}
    prepared = []

    for values in by_url.values():
        job_id = values["job_id"]

        if job_id in by_id:
            if by_id[job_id] != values["job_url"]:
                continue
        else:
            by_id[job_id] = values["job_url"]

        prepared.append(values)

    return prepared


def _save_one(values, company):
    """
    Резервне збереження одного запису.
    Повертає True, якщо створено нову вакансію.
    """
    defaults = {
        "title": values["title"],
        "company": company,
    }

    for field in (
        "location",
        "description",
        "employment_type",
        "seniority",
        "published_at",
    ):
        if field in values:
            defaults[field] = values[field]

    try:
        with transaction.atomic():
            job, created = Job.objects.update_or_create(
                job_url=values["job_url"],
                defaults={
                    **defaults,
                    "job_id": values["job_id"],
                },
            )
            return created

    except IntegrityError:
        # URL або ID могли бути додані іншим процесом.
        # Якщо URL вже існує, оновлюємо його лише тоді,
        # коли ID збігається.
        with transaction.atomic():
            job = Job.objects.filter(
                job_url=values["job_url"]
            ).first()

            if job is None or job.job_id != values["job_id"]:
                return False

            for field, value in defaults.items():
                setattr(job, field, value)

            job.save()
            return False


def save_jobs(data):
    """
    Пакетно створює та оновлює вакансії.
    Повертає кількість створених вакансій.
    """
    if not isinstance(data, list):
        raise ValueError("Очікувався список вакансій.")

    prepared = _prepare_jobs(data)

    if not prepared:
        return 0

    created_count = 0

    # Обробляємо пакети, щоб не завантажувати всю базу
    # та всі вхідні записи в один великий запит.
    for offset in range(0, len(prepared), BATCH_SIZE):
        batch = prepared[offset:offset + BATCH_SIZE]

        with transaction.atomic():
            company_names = {
                item["company_name"] for item in batch
            }

            companies = {
                company.name: company
                for company in Company.objects.filter(
                    name__in=company_names
                )
            }

            missing_names = company_names - set(companies)

            if missing_names:
                # Створення компаній із захистом від паралельного
                # додавання компанії з таким самим ім'ям.
                for name in missing_names:
                    try:
                        with transaction.atomic():
                            company, _ = Company.objects.get_or_create(
                                name=name
                            )
                            companies[name] = company
                    except IntegrityError:
                        company = Company.objects.filter(
                            name=name
                        ).first()
                        if company:
                            companies[name] = company

            urls = [item["job_url"] for item in batch]
            job_ids = [item["job_id"] for item in batch]

            existing_by_url = {
                job.job_url: job
                for job in Job.objects.filter(job_url__in=urls)
            }

            existing_by_id = {
                job.job_id: job
                for job in Job.objects.filter(job_id__in=job_ids)
            }

            to_update = {}
            to_create = []
            fallback = []

            for values in batch:
                company = companies.get(values["company_name"])

                if company is None:
                    continue

                url_match = existing_by_url.get(values["job_url"])
                id_match = existing_by_id.get(values["job_id"])

                # URL та ID не повинні вказувати на різні вакансії.
                if (
                    url_match
                    and id_match
                    and url_match.pk != id_match.pk
                ):
                    continue

                existing = url_match or id_match

                if existing:
                    # Не перепризначаємо URL або ID іншій вакансії.
                    if (
                        existing.job_url != values["job_url"]
                        or existing.job_id != values["job_id"]
                    ):
                        continue

                    existing.title = values["title"]
                    existing.company = company

                    for field in (
                        "location",
                        "description",
                        "employment_type",
                        "seniority",
                        "published_at",
                    ):
                        if field in values:
                            setattr(existing, field, values[field])

                    to_update[existing.pk] = existing

                else:
                    to_create.append(
                        Job(
                            job_id=values["job_id"],
                            title=values["title"],
                            job_url=values["job_url"],
                            company=company,
                            location=values.get("location", ""),
                            description=values.get("description", ""),
                            employment_type=values.get(
                                "employment_type", ""
                            ),
                            seniority=values.get("seniority", ""),
                            published_at=values.get("published_at"),
                        )
                    )

            update_fields = [
                "title",
                "company",
                "location",
                "description",
                "employment_type",
                "seniority",
                "published_at",
                "updated_at",
            ]

            updated_jobs = list(to_update.values())

            for start in range(0, len(updated_jobs), BATCH_SIZE):
                Job.objects.bulk_update(
                    updated_jobs[start:start + BATCH_SIZE],
                    update_fields,
                    batch_size=BATCH_SIZE,
                )

            # Створення без ignore_conflicts дає змогу точно
            # порахувати вставлені рядки, якщо пакет успішний.
            if to_create:
                try:
                    with transaction.atomic():
                        Job.objects.bulk_create(
                            to_create,
                            batch_size=BATCH_SIZE,
                        )
                    created_count += len(to_create)

                except IntegrityError:
                    # Конфлікт унікальності міг виникнути через
                    # паралельний процес. Зберігаємо записи
                    # по одному, щоб визначити результат кожного.
                    fallback = [
                        {
                            "job_id": job.job_id,
                            "job_url": job.job_url,
                            "title": job.title,
                            "company_name": job.company.name,
                            "location": job.location,
                            "description": job.description,
                            "employment_type": job.employment_type,
                            "seniority": job.seniority,
                            **(
                                {"published_at": job.published_at}
                                if job.published_at
                                else {}
                            ),
                        }
                        for job in to_create
                    ]

        # Резервні операції поза основною транзакцією пакета.
        for values in fallback:
            company = Company.objects.filter(
                name=values["company_name"]
            ).first()

            if company is not None and _save_one(values, company):
                created_count += 1

    return created_count


def parse_jobs(file_path):
    """Завантажує вакансії з JSON-файлу."""
    with open(file_path, "r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("Очікувався список вакансій у JSON")

    return save_jobs(data)


def fetch_and_save(url, items_key=None):
    """Отримує вакансії з API та зберігає їх."""
    data = fetch_json(url)

    if items_key:
        if not isinstance(data, dict):
            raise ValueError("Очікувався JSON-об'єкт із вакансіями")
        data = data.get(items_key)

    if not isinstance(data, list):
        raise ValueError("Очікувався список вакансій у JSON")

    return save_jobs(data)
