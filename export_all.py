import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from jobs.exporter import export_all_excel

jobs_count, companies_count = export_all_excel(
    "linkedin_jobs_export.xlsx"
)

print(f"Вакансій: {jobs_count}")
print(f"Компаній: {companies_count}")
print("Файл: linkedin_jobs_export.xlsx")
