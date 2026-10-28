
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from jobs.fetcher import fetch_linkedin_job_details
from jobs.models import Job


class Command(BaseCommand):
    help = "Отримує деталі вже збережених вакансій"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Максимальна кількість вакансій за один запуск",
        )
        parser.add_argument(
            "--max-attempts",
            type=int,
            default=3,
            help="Максимальна кількість спроб для однієї вакансії",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=2,
            help="Пауза між запитами в секундах",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        max_attempts = options["max_attempts"]
        delay = options["delay"]

        if limit < 1 or max_attempts < 1 or delay < 0:
            self.stderr.write(
                self.style.ERROR(
                    "limit і max-attempts мають бути більшими за 0, "
                    "delay не може бути від'ємним."
                )
            )
            return

        # Повертаємо завислі вакансії в чергу.
        # Враховуємо тільки записи, які не оновлювалися понад 30 хвилин.
        stale_before = timezone.now() - timedelta(minutes=30)

        recovered = Job.objects.filter(
            job_url__contains="linkedin.com/jobs/view/",
            details_status="processing",
            updated_at__lt=stale_before,
        ).update(
            details_status="failed",
            last_error=(
                "Обробку перервано: статус processing "
                "не оновлювався понад 30 хвилин."
            ),
        )

        if recovered:
            self.stdout.write(
                f"Відновлено завислих вакансій: {recovered}"
            )

        jobs = list(
            Job.objects.filter(
                job_url__contains="linkedin.com/jobs/view/",
                details_status__in=["pending", "failed"],
                attempts__lt=max_attempts,
            )
            .order_by("id")[:limit]
        )

        if not jobs:
            self.stdout.write("Немає вакансій для обробки.")
            return

        succeeded = 0
        failed = 0
        skipped = 0

        for index, job in enumerate(jobs, start=1):
            self.stdout.write(f"[{index}/{len(jobs)}] {job.title}")

            # Атомарно захоплюємо вакансію перед HTTP-запитом.
            with transaction.atomic():
                current = (
                    Job.objects.select_for_update()
                    .get(pk=job.pk)
                )

                if (
                    current.details_status not in ["pending", "failed"]
                    or current.attempts >= max_attempts
                ):
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
                details = fetch_linkedin_job_details(job.job_url)
                description = details.get("description", "").strip()

                if not description:
                    raise ValueError(
                        "Опис вакансії не знайдено на сторінці."
                    )

                Job.objects.filter(pk=job.pk).update(
                    description=description,
                    details_status="done",
                    last_error="",
                )

                succeeded += 1
                self.stdout.write(
                    self.style.SUCCESS("Деталі збережено.")
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
                f"оброблено: {succeeded + failed}."
            )
        )
