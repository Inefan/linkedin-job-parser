
import time

from django.core.management.base import BaseCommand
from django.db.models import Q

from jobs.models import Company
from jobs.fetcher import fetch_linkedin_company_details, RateLimitError


class Command(BaseCommand):
    help = "Fetch and save LinkedIn company details"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Maximum number of companies to process",
        )

        parser.add_argument(
            "--delay",
            type=float,
            default=5,
            help="Delay between requests in seconds",
        )

        parser.add_argument(
            "--force",
            action="store_true",
            help="Process companies even if all fields are filled",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        delay = options["delay"]
        force = options["force"]

        companies = Company.objects.exclude(linkedin_url="")

        if not force:
            companies = companies.filter(
                Q(description="")
                | Q(industry="")
                | Q(employee_count="")
                | Q(website="")
            )
        companies = companies.order_by("id")[:limit]

        total = companies.count()

        if total == 0:
            self.stdout.write(
                self.style.SUCCESS("No companies need updating.")
            )
            return

        self.stdout.write(f"Companies to process: {total}")

        updated_count = 0
        skipped_count = 0
        error_count = 0

        for index, company in enumerate(companies, start=1):
            self.stdout.write(
                f"\n[{index}/{total}] {company.name}"
            )

            try:
                data = fetch_linkedin_company_details(
                    company.linkedin_url
                )

                fields = {
                    "description": data.get("company_description", ""),
                    "industry": data.get("company_industry", ""),
                    "website": data.get("company_website", ""),
                    "employee_count": data.get(
                        "company_employee_count", ""
                    ),
                }

                changed = False

                for field, value in fields.items():
                    if value and getattr(company, field) != value:
                        setattr(company, field, value)
                        changed = True

                if changed:
                    company.save()
                    updated_count += 1
                    self.stdout.write(
                        self.style.SUCCESS("Company updated.")
                    )
                else:
                    skipped_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            "No new information found."
                        )
                    )

            except RateLimitError as error:
                error_count += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Rate limit reached: {error}"
                    )
                )
                self.stderr.write(
                    "Stopping to avoid sending more requests."
                )
                break

            except Exception as error:
                error_count += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Error: {error}"
                    )
                )

            if index < total:
                time.sleep(delay)

        self.stdout.write("\n--- Results ---")
        self.stdout.write(f"Processed: {min(index, total)}")
        self.stdout.write(
            self.style.SUCCESS(f"Updated: {updated_count}")
        )
        self.stdout.write(f"Without changes: {skipped_count}")
        self.stdout.write(
            self.style.ERROR(f"Errors: {error_count}")
        )
