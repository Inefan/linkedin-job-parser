import time

from django.core.management.base import BaseCommand

from jobs.fetcher import fetch_linkedin_jobs
from jobs.parser import save_jobs


class Command(BaseCommand):
    help = "Collect public LinkedIn job listings"

    def add_arguments(self, parser):
        parser.add_argument(
            "--query",
            type=str,
            required=True,
            help="Search keywords",
        )
        parser.add_argument(
            "--country",
            type=str,
            default="United States",
            help="Search location",
        )
        parser.add_argument(
            "--start",
            type=int,
            default=0,
            help="Starting result offset",
        )
        parser.add_argument(
            "--pages",
            type=int,
            default=10,
            help="Maximum pages to request",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=2.0,
            help="Delay between requests in seconds",
        )

    def handle(self, *args, **options):
        query = options["query"].strip()
        country = options["country"].strip()
        start = options["start"]
        pages = options["pages"]
        delay = options["delay"]

        if not query:
            self.stderr.write("Пошуковий запит не може бути порожнім.")
            return

        if start < 0 or pages < 1 or delay < 0:
            self.stderr.write(
                "start має бути >= 0, pages >= 1, delay >= 0."
            )
            return

        total_received = 0
        total_created = 0
        total_unique_received = set()

        for page in range(pages):
            current_start = start + page * 10

            self.stdout.write(
                f"Сторінка {page + 1}/{pages} | "
                f"Start: {current_start} | "
                f"Запит: {query} | Локація: {country}"
            )

            try:
                data = fetch_linkedin_jobs(
                    query=query,
                    country=country,
                    start=current_start,
                )
            except Exception as error:
                self.stderr.write(
                    self.style.ERROR(
                        f"Помилка отримання сторінки: {error}"
                    )
                )
                break

            if not data:
                self.stdout.write(
                    "Результатів немає. Завершую цей пошук."
                )
                break

            created = save_jobs(data)

            total_received += len(data)

            for job in data:
                job_id = job.get("job_id")
                if job_id:
                    total_unique_received.add(str(job_id))

            total_created += created

            self.stdout.write(
                f"Отримано: {len(data)} | "
                f"Унікальних ID за запуск: "
                f"{len(total_unique_received)} | "
                f"Нових у БД: {created}"
            )

            if page < pages - 1:
                time.sleep(delay)

        self.stdout.write(
            self.style.SUCCESS(
                "\nЗбір завершено.\n"
                f"Отримано записів: {total_received}\n"
                f"Унікальних ID за запуск: "
                f"{len(total_unique_received)}\n"
                f"Нових вакансій у БД: {total_created}"
            )
        )