"""Script to generate a verified 1,000-row destination catalogue CSV for benchmarking."""

import csv
import random
from pathlib import Path

PLATFORMS = [
    ("Discourse", "discourse", "discourse", "https://forum.{topic}.org", "topic", "L3"),
    ("Lemmy", "lemmy", "lemmy", "https://lemmy.{topic}.io", "community_post", "L3"),
    ("Dev.to", "devto", "devto", "https://dev.to/{topic}", "article", "L3"),
    ("Ghost", "ghost", "ghost", "https://blog.{topic}.com", "post", "L3"),
    ("Partner Webhook", "webhook", "webhook", "https://syndicate.{topic}.net/webhook", "partner_feed", "L2"),
    ("Hacker News / Manual", "assisted", "assisted", "https://news.ycombinator.com/submit", "moderated_forum", "L1"),
    ("Hashnode", "hashnode", "hashnode", "https://{topic}.hashnode.dev", "article", "L3"),
    ("Slack Community", "slack", "slack", "https://{topic}.slack.com", "channel_post", "L2"),
]

TOPICS = [
    "ai", "saas", "founders", "marketing", "video", "python", "fastapi", "react",
    "cloud", "devops", "startups", "indiehackers", "machinelearning", "growth",
    "automation", "opensource", "webdev", "robotics", "analytics", "product"
]

CATEGORIES = ["technology", "business", "engineering", "creator_economy", "artificial_intelligence"]

AUDIENCE_TAGS = [
    "ai;founders;saas", "developers;opensource", "marketers;video_creators",
    "engineers;devops", "startups;indie_hackers", "writers;bloggers"
]

def generate_csv(file_path: Path, count: int = 1000) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "name", "url", "platform_key", "surface", "category", "audience_tags",
        "language", "geo", "est_audience", "rules_url", "frequency_cap",
        "self_promo_allowed", "link_policy", "disclosure_required", "automation_allowed",
        "connector_key", "relevance_score", "relevance_reason", "level", "last_certified_at"
    ]

    rows = []
    for i in range(1, count + 1):
        plat_name, plat_key, conn_key, url_tmpl, surface, level = random.choice(PLATFORMS)
        topic = f"{random.choice(TOPICS)}_{i}"
        url = url_tmpl.format(topic=topic)

        # Inject some deliberate duplicates and invalid rows to test error reporting (approx 2% of rows)
        if i % 50 == 0:
            # Duplicate entry
            name = f"Duplicate Hub {topic}"
            url = rows[-1][1] if rows else url
            plat_key = rows[-1][2] if rows else plat_key
        elif i % 100 == 0:
            # Invalid entry (missing name or invalid score)
            name = ""
            rel_score = 9
        else:
            name = f"{plat_name} {topic.replace('_', ' ').title()} Community"
            rel_score = random.randint(3, 5)

        relevance_reason = f"High affinity with IncuBrix {topic.split('_')[0]} creator audience"
        est_audience = random.randint(1000, 250000)
        freq_cap = random.randint(1, 14)
        self_promo = "true" if random.random() > 0.3 else "false"
        links = "allowed" if random.random() > 0.2 else "disallowed"
        disclosure = "true" if random.random() > 0.5 else "false"

        rows.append([
            name, url, plat_key, surface, random.choice(CATEGORIES), random.choice(AUDIENCE_TAGS),
            "en", "global", est_audience, f"{url}/rules", freq_cap,
            self_promo, links, disclosure, "true" if level != "L1" else "false",
            conn_key, rel_score, relevance_reason, level, "2026-10-17"
        ])

    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    print(f"Generated {count} destination rows in {file_path}")

if __name__ == "__main__":
    generate_csv(Path("data/destinations_sample_1000.csv"), 1000)
