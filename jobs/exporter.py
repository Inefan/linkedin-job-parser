
import csv

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from jobs.models import Job


def get_jobs_data():
    jobs = Job.objects.select_related("company").order_by("id")

    for job in jobs.iterator(chunk_size=1000):
        yield [
            job.title,
            job.company.name if job.company else "",
            job.job_url,
            job.location,
            job.description,
            job.employment_type,
            job.seniority,
            job.details_status,
            job.attempts,
            job.published_at,
            job.created_at,
        ]


HEADERS = [
    "Title",
    "Company",
    "URL",
    "Location",
    "Description",
    "Employment type",
    "Seniority",
    "Details status",
    "Attempts",
    "Published at",
    "Created at",
]


def export_jobs(file_path):
    count = 0

    with open(file_path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(HEADERS)

        for row in get_jobs_data():
            writer.writerow(row)
            count += 1

    return count


def export_jobs_excel(file_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Jobs"

    sheet.append(HEADERS)

    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(
            fill_type="solid",
            fgColor="1F4E78",
        )

    count = 0

    for row in get_jobs_data():
        sheet.append(row)
        count += 1

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    for column_index, column_cells in enumerate(
        sheet.columns, start=1
    ):
        max_length = max(
            len(str(cell.value or ""))
            for cell in list(column_cells)[:200]
        )
        sheet.column_dimensions[
            get_column_letter(column_index)
        ].width = min(max(max_length + 2, 12), 45)

    workbook.save(file_path)
    return count
