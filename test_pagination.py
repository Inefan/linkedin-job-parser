import time
import django

django.setup()

from jobs.fetcher import fetch_linkedin_jobs

all_ids = set()
total = 0

for start in range(0, 1000, 10):
    try:
        jobs = fetch_linkedin_jobs(
            query="Python Developer",
            country="United States",
            start=start,
        )

        ids = {job["job_id"] for job in jobs}
        new_ids = ids - all_ids

        total += len(jobs)
        all_ids.update(ids)

        print(
            f"Start={start} | "
            f"Отримано={len(jobs)} | "
            f"Нових ID={len(new_ids)}"
        )

    except Exception as error:
        print(f"Помилка на start={start}: {error}")

    time.sleep(2)

print(f"Усього результатів: {total}")
print(f"Унікальних вакансій: {len(all_ids)}")
