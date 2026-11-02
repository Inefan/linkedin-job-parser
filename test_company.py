
import os
import re
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import requests
from jobs.models import Company

company = Company.objects.get(name="LTM")

response = requests.get(
    company.linkedin_url,
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=20,
)

print("Status:", response.status_code)
print("HTML length:", len(response.text))

for keyword in ["website", "companyWebsite", "companyUrl", "externalUrl"]:
    matches = list(re.finditer(keyword, response.text, re.IGNORECASE))

    print(f"\n--- {keyword}: {len(matches)} matches ---")

    for match in matches[:3]:
        start = max(0, match.start() - 200)
        end = min(len(response.text), match.end() + 300)
        print(response.text[start:end])
        print("-" * 50)
