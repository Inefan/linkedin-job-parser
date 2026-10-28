
from django.db import models



class Company(models.Model):
    name = models.CharField(max_length=255)
    linkedin_url = models.URLField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    industry = models.CharField(max_length=255, blank=True)
    website = models.URLField(max_length=500, blank=True)
    employee_count = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Job(models.Model):
    job_id = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=255)

    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jobs",
    )
    job_url = models.URLField(max_length=500, unique=True)
    location = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    employment_type = models.CharField(max_length=100, blank=True)
    seniority = models.CharField(max_length=100, blank=True)

    details_status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Очікує"),
            ("processing", "Обробляється"),
            ("done", "Завершено"),
            ("failed", "Помилка"),
        ],
        default="pending",
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} — {self.company.name if self.company else 'Невідома компанія'}"
