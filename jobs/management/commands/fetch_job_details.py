
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from jobs.fetcher import (
    fetch_linkedin_job_details,
    fetch_linkedin_company_details,
)
from jobs.models import Job


class Command(BaseCommand):
    help = "Отримує та оновлює деталі вакансій і компаній"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--max-attempts", type=int, default=3)
        parser.add_argument("--delay", type=float, default=2)
        parser.add_argument(
            "--retry-done",
            action="store_true",
            help="Повторно обробляти done-вакансії з незаповненими деталями",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        max_attempts = options["max_attempts"]
        delay = options["delay"]
        retry_done = options["retry_done"]

        if limit < 1 or max_attempts < 1 or delay < 0:
            self.stderr.write(
                self.style.ERROR("Некоректні параметри запуску.")
            )
            return

        stale_before = timezone.now() - timedelta(minutes=30)

        recovered = Job.objects.filter(
            job_url__contains="linkedin.com/jobs/view/",
            details_status="processing",
            updated_at__lt=stale_before,
        ).update(
            details_status="failed",
            last_error="Обробку перервано: завислий статус processing.",
        )

        if recovered:
            self.stdout.write(
                f"Відновлено завислих вакансій: {recovered}"
            )

        statuses = ["pending", "failed"]

        if retry_done:
            statuses.append("done")

        queryset = Job.objects.filter(
            job_url__contains="linkedin.com/jobs/view/",
            details_status__in=statuses,
        ).select_related("company")

        if retry_done:
            queryset = queryset.filter(
                employment_type=""
            ) | queryset.filter(
                seniority=""
            )
        else:
            queryset = queryset.filter(
                attempts__lt=max_attempts
            )

        jobs = list(queryset.order_by("id").distinct()[:limit])

        if not jobs:
            self.stdout.write("Немає вакансій для обробки.")
            return

        succeeded = 0
        failed = 0
        skipped = 0
        companies_updated = 0
        companies_processed = set()

        for index, job in enumerate(jobs, start=1):
            self.stdout.write(
                f"[{index}/{len(jobs)}] {job.title}"
            )

            with transaction.atomic():
                current = Job.objects.select_for_update().get(pk=job.pk)

                allowed_statuses = (
                    ["pending", "failed", "done"]
                    if retry_done
                    else ["pending", "failed"]
                )

                if current.details_status not in allowed_statuses:
                    skipped += 1
                    continue

                if not retry_done and current.attempts >= max_attempts:
                    skipped += 1
                    continue

                current.attempts += 1
                current.details_status = "processing"
                current.last_error = ""

                current.save(
                    update_fields=[
                        "attempts",
                        "details_status",
                        "last_error",
                        "updated_at",
                    ]
                )

            try:
                # 1. Отримуємо деталі вакансії.
                details = fetch_linkedin_job_details(job.job_url)

                description = (
                    details.get("description") or ""
                ).strip()

                employment_type = (
                    details.get("employment_type") or ""
                ).strip()

                seniority = (
                    details.get("seniority") or ""
                ).strip()

                if not description and not job.description:
                    raise ValueError("Опис вакансії не знайдено.")

                # 2. Зберігаємо деталі вакансії та дані з JSON-LD.
                with transaction.atomic():
                    current = Job.objects.select_for_update().get(
                        pk=job.pk
                    )

                    if description:
                        current.description = description

                    if employment_type:
                        current.employment_type = employment_type

                    if seniority:
                        current.seniority = seniority

                    current.details_status = "done"
                    current.last_error = ""

                    current.save(
                        update_fields=[
                            "description",
                            "employment_type",
                            "seniority",
                            "details_status",
                            "last_error",
                            "updated_at",
                        ]
                    )

                    company = current.company

                    if company:
                        company_data = {
                            "description": "company_description",
                            "industry": "company_industry",
                            "website": "company_website",
                            "linkedin_url": "company_linkedin_url",
                        }

                        changed_fields = []

                        for model_field, detail_field in company_data.items():
                            value = details.get(detail_field) or ""

                            if isinstance(value, str):
                                value = value.strip()

                            if value and getattr(company, model_field) != value:
                                setattr(company, model_field, value)
                                changed_fields.append(model_field)

                        if changed_fields:
                            company.save(
                                update_fields=changed_fields + ["updated_at"]
                            )

                # 3. Отримуємо додаткові дані зі сторінки компанії.
                if company and company.pk not in companies_processed:
                    companies_processed.add(company.pk)

                    # Оновлюємо об'єкт, щоб отримати актуальний LinkedIn URL.
                    company.refresh_from_db()

                    missing_company_data = (
                        not company.description
                        or not company.industry
                        or not company.website
                        or not company.employee_count
                    )

                    if company.linkedin_url and missing_company_data:
                        try:
                            company_details = fetch_linkedin_company_details(
                                company.linkedin_url
                            )

                            company_fields = {
                                "description": "company_description",
                                "industry": "company_industry",
                                "website": "company_website",
                                "employee_count": "company_employee_count",
                            }

                            changed_fields = []

                            for model_field, detail_field in company_fields.items():
                                value = company_details.get(detail_field) or ""

                                if isinstance(value, str):
                                    value = value.strip()

                                if value and getattr(company, model_field) != value:
                                    setattr(company, model_field, value)
                                    changed_fields.append(model_field)

                            if changed_fields:
                                company.save(
                                    update_fields=changed_fields + ["updated_at"]
                                )

                                companies_updated += 1

                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"Дані компанії оновлено: {company.name}"
                                    )
                                )

                        except Exception as company_error:
                            self.stderr.write(
                                self.style.WARNING(
                                    f"Не вдалося отримати дані компанії "
                                    f"{company.name}: {company_error}"
                                )
                            )

                succeeded += 1

                self.stdout.write(
                    self.style.SUCCESS("Деталі вакансії збережено.")
                )

            except Exception as error:
                Job.objects.filter(pk=job.pk).update(
                    details_status="failed",
                    last_error=str(error)[:2000],
                )

                failed += 1

                self.stderr.write(
                    self.style.ERROR(f"Помилка: {error}")
                )

            if index < len(jobs) and delay:
                time.sleep(delay)

        self.stdout.write(
            self.style.SUCCESS(
                f"Завершено. Успішно: {succeeded}; "
                f"помилок: {failed}; пропущено: {skipped}; "
                f"компаній оновлено: {companies_updated}."
            )
        )
