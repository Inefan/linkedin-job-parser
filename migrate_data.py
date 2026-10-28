import json
from django.core import serializers
from django.db import transaction, connections

from jobs.models import Company, Job

# Читаємо дані зі старої SQLite-бази
with transaction.atomic(using="sqlite_old"):
    companies = list(
        Company.objects.using("sqlite_old").all()
    )
    jobs = list(
        Job.objects.using("sqlite_old").all()
    )

# Переносимо компанії, зберігаючи їхні ID
with transaction.atomic(using="default"):
    for company in companies:
        Company.objects.using("default").update_or_create(
            id=company.id,
            defaults={
                "name": company.name,
                "linkedin_url": company.linkedin_url,
                "description": company.description,
                "industry": company.industry,
                "website": company.website,
                "employee_count": company.employee_count,
                "created_at": company.created_at,
                "updated_at": company.updated_at,
            },
        )

    # Переносимо вакансії, зберігаючи їхні ID та зв'язки
    for job in jobs:
        Job.objects.using("default").update_or_create(
            id=job.id,
            defaults={
                "job_id": job.job_id,
                "title": job.title,
                "company_id": job.company_id,
                "job_url": job.job_url,
                "location": job.location,
                "description": job.description,
                "employment_type": job.employment_type,
                "seniority": job.seniority,
                "details_status": job.details_status,
                "attempts": job.attempts,
                "last_error": job.last_error,
                "published_at": job.published_at,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
            },
        )

print(f"Перенесено компаній: {len(companies)}")
print(f"Перенесено вакансій: {len(jobs)}")