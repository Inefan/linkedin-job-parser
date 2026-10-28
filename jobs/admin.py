
import csv
from io import BytesIO
from datetime import datetime
from django.contrib import admin
from django.http import HttpResponse
from openpyxl import Workbook

from .models import Company, Job


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


def export_jobs_csv_action(modeladmin, request, queryset):
    response = HttpResponse(
        content_type="text/csv; charset=utf-8"
    )
    response["Content-Disposition"] = 'attachment; filename="jobs.csv"'
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow(HEADERS)

    for job in queryset.select_related("company").iterator(chunk_size=1000):
        writer.writerow([
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
        ])

    return response

def excel_datetime(value):
    if value is None:
        return None

    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.replace(tzinfo=None)

    return value

def export_jobs_excel_action(modeladmin, request, queryset):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Jobs"
    sheet.append(HEADERS)

    for job in queryset.select_related("company").iterator(chunk_size=1000):
        sheet.append([
            job.title,
            job.company.name if job.company else "",
            job.job_url,
            job.location,
            job.description,
            job.employment_type,
            job.seniority,
            job.details_status,
            job.attempts,
            excel_datetime(job.published_at),
            excel_datetime(job.created_at),
        ])

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    output = BytesIO()
    workbook.save(output)

    response = HttpResponse(
        output.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    )
    response["Content-Disposition"] = 'attachment; filename="jobs.xlsx"'
    return response


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "industry",
        "website",
        "created_at",
    )
    search_fields = ("name", "industry", "website")
    list_filter = ("industry",)
    ordering = ("name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    actions = [
        export_jobs_csv_action,
        export_jobs_excel_action,
    ]

    list_display = (
        "id",
        "title",
        "company",
        "location",
        "details_status",
        "attempts",
        "published_at",
        "updated_at",
    )
    list_filter = (
        "details_status",
        "employment_type",
        "seniority",
        "published_at",
    )
    search_fields = (
        "title",
        "company__name",
        "location",
        "job_id",
        "job_url",
    )
    ordering = ("-updated_at",)
    list_per_page = 50
    list_select_related = ("company",)

    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (
            "Основна інформація",
            {
                "fields": (
                    "job_id",
                    "title",
                    "company",
                    "job_url",
                    "location",
                    "published_at",
                )
            },
        ),
        (
            "Деталі вакансії",
            {
                "fields": (
                    "description",
                    "employment_type",
                    "seniority",
                )
            },
        ),
        (
            "Обробка",
            {
                "fields": (
                    "details_status",
                    "attempts",
                    "last_error",
                )
            },
        ),
        (
            "Дати",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
