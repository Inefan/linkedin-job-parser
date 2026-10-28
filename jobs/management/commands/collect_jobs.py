
import time

from django.core.management.base import BaseCommand

from jobs.fetcher import fetch_linkedin_jobs
from jobs.parser import save_jobs


class Command(BaseCommand):
    help = "Collect public LinkedIn job listings"

    def add_arguments(self, parser):
        parser.add_argument("--query", type=str, required=True)
        parser.add_argument("--country", type=str, required=True)
        parser.add_argument("--start", type=int, default=0)
        parser.add_argument("--pages", type=int, default=1)

    def handle(self, *args, **options):
        query = options["query"]
        country = options["country"]
        start = options["start"]
        pages = options["pages"]

        if pages < 1:
            self.stderr.write("Кількість сторінок має бути не меншою за 1.")
            return

        total_received = 0
        total_created = 0

        for page in range(pages):
            current_start = start + page * 10

            self.stdout.write(
                f"Сторінка {page + 1}/{pages} | Start: {current_start}"
            )

            try:
                data = fetch_linkedin_jobs(
                    query=query,
                    country=country,
                    start=current_start,
                )
            except Exception as error:
                self.stderr.write(f"Помилка отримання даних: {error}")
                break

            if not data:
                self.stdout.write("Вакансій більше не знайдено.")
                break

            created = save_jobs(data)

            total_received += len(data)
            total_created += created

            self.stdout.write(
                f"Отримано: {len(data)} | Створено: {created}"
            )

            if page < pages - 1:
                time.sleep(2)

        self.stdout.write(
            self.style.SUCCESS(
                f"Завершено. Отримано: {total_received} | "
                f"Створено: {total_created}"
            )
        )
