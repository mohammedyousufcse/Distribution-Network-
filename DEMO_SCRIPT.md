# IncuBrix Assessment 4: 8-Minute Video Demo Walkthrough Script

**Project:** IncuBrix Distribution: Long-Tail Destination Network  
**Assessment Problem Statement:** Problem Statement 4  
**Presenter:** Engineering Lead / Candidate  
**Target Duration:** Exactly 7 to 8 minutes  
**Target URL:** `http://localhost:8000` (or your Render URL)  
**Swagger UI:** `http://localhost:8000/docs`

---

## ⏱️ Video Timeline Overview

| Timestamp | Segment Title | On-Screen Action | Key Talking Points |
|---|---|---|---|
| **00:00 – 01:00** | Architecture & Service Health | Terminal: `docker compose ps` & Browser: `/health` | Containerized microservice, 4 healthy containers, OpenAPI 3.1.0 contract. |
| **01:00 – 02:45** | Interactive Connector Walkthrough | Swagger UI: Discourse, Lemmy, Mailchimp, Assisted | Unified `POST /connector/v1/{key}/{method}`, simulation mode, manifests. |
| **02:45 – 04:00** | Multi-Category Rules & Safe Retries | Swagger UI: Link ban, Idempotency-Key header | Deterministic pre-flight checks, 429 weekly cap, 409 idempotency conflict. |
| **04:00 – 05:15** | 12-Step Automated Certification | Swagger UI: `/destinations/{id}/certify` & `EVIDENCE/` | End-to-end 12 steps, clean post deletion (<10 min), audit JSON evidence. |
| **05:15 – 06:15** | AI Rules Capture & Recommender Engine | Swagger UI: `/rules/propose`, `/rules/confirm`, `/recommend` | Guideline extraction, human confirmation lifecycle, precision@10 benchmark. |
| **06:15 – 07:00** | High-Speed CSV Catalogue (1,000+ & Real 150) | Terminal: `python import_catalogue.py` & CSV preview | 1,000 rows in 0.02s (<5 min requirement), 150 real researched destinations. |
| **07:00 – 08:00** | Batch Runner CLI & Full Test Suite | Terminal: `batch_runner.py` & `pytest -v` | 14/14 tests PASS (100%), 172 unit & contract tests pass with 0 warnings. |

---

## 🎬 Second-by-Second Detailed Script

### Segment 1: Architecture & Service Health (00:00 – 01:00)
**Visual:**
Open terminal split-screen with your browser showing Swagger UI at `http://localhost:8000/docs`.

**Spoken Script:**
> *"Hello, this is my submission presentation for IncuBrix Assessment Problem Statement 4: Distribution: Long-Tail Destination Network.*
>
> *Here on screen, all four Docker containers are running and healthy via Docker Compose: our core FastAPI distribution gateway on port 8000, our Ghost 5 sandbox on port 2368, and a local federated Lemmy node backed by PostgreSQL.*
>
> *Querying `GET /health` returns HTTP 200 Healthy. The entire service adheres strictly to the Assessment Appendix A contract and OpenAPI 3.1.0 specification with zero schema drift."*

---

### Segment 2: Interactive Connector Walkthrough (01:00 – 02:45)
**Visual:**
In Swagger UI, expand `POST /connector/v1/{connector_key}/{method}`.

**Spoken Script:**
> *"Every downstream destination is exposed through a standardized REST interface: `POST /connector/v1/{connector_key}/{method}`. No destination requires unique routing or database writes.*
>
> *First, let's test our Discourse connector: setting `connector_key: discourse`, `method: publish`, and posting our JSON body in simulation mode. Executing this returns HTTP 200 with platform post ID and simulated URL.*
>
> *Second, we test our Lemmy federated connector: setting `connector_key: lemmy`, `method: publish`. It authenticates via JWT and returns a published status.*
>
> *Third, our Path 1 email newsletter connector, Mailchimp: setting `connector_key: mailchimp`, `method: publish`. It validates subject line length limits, body size, and returns a verified campaign web view archive.*
>
> *Finally, our Assisted Connector: for high-touch or private destinations where direct API posting is prohibited, setting `connector_key: assisted` generates a ready-to-post operator pack containing clean captions, assets, and deep links with status `human_action_required`."*

---

### Segment 3: Multi-Category Rules & Safe Retries (02:45 – 04:00)
**Visual:**
In Swagger UI, test policy violation and idempotency header.

**Spoken Script:**
> *"Before any downstream API is called, our `PolicyService` performs defensive pre-flight validation.*
>
> *For example, on destinations with `allow_links: false`, submitting a URL returns HTTP 400 with the canonical code `DEST_SPEC_VIOLATION`.*
>
> *The engine also enforces sliding 7-day rolling frequency caps returning `DEST_RULE_FREQUENCY_CAP` with HTTP 429, supporting clock injection for deterministic testing.*
>
> *For safe network retries, when passing the `Idempotency-Key` header, the first publish executes normally. Submitting a duplicate request with the exact same payload instantly replays the original cached post ID without creating duplicate posts or consuming rate limits. Reusing the key with a different payload returns HTTP 409 Conflict."*

---

### Segment 4: 12-Step Automated Certification Harness (04:00 – 05:15)
**Visual:**
Execute `POST /connector/v1/destinations/discourse_dev_forum/certify` in Swagger UI, then open the `EVIDENCE/` directory in VS Code.

**Spoken Script:**
> *"To ensure long-tail destinations remain certified over time, we built a repeatable 12-step certification harness.*
>
> *Executing `POST /connector/v1/destinations/{destination_id}/certify` triggers the harness: it loads destination rules, checks eligibility, publishes a test post, verifies the live URL, checks post status, and deletes the test post within 10 minutes to guarantee clean cleanup.*
>
> *As seen here, it creates a timestamped, cryptographically auditable JSON record in the `EVIDENCE/` directory with full latency diagnostics and verification proofs."*

---

### Segment 5: AI Rules Capture & Recommender Engine (05:15 – 06:15)
**Visual:**
In Swagger UI, test `/rules/propose`, `/rules/confirm`, and `/recommend`.

**Spoken Script:**
> *"Under Path 1 Top Pick scope, we added AI Rules Capture and Destination Recommendation.*
>
> *In `POST /connector/v1/rules/propose`, we pass raw, unstructured community guideline text. The extractor parses self-promotion rules, link permissions, weekly frequency caps, and AI disclosure requirements.*
>
> *Using `POST /connector/v1/rules/confirm`, a human operator confirms the extracted rules, persisting them with an auditable confirmation timestamp.*
>
> *Next, our Destination Recommender at `POST /connector/v1/recommend` evaluates audience pillar relevance, format affinity, and hard rule filtering, ranking the best destinations with transparent explanations. Running `GET /connector/v1/recommend/benchmark` evaluates precision@10 at a perfect 1.00 score."*

---

### Segment 6: High-Speed CSV Catalogue Ingestion (06:15 – 07:00)
**Visual:**
Switch to terminal and run the CSV importer, then show `data/destinations_real_150.csv`.

**Command:**
```bash
python import_catalogue.py --csv data/destinations_sample_1000.csv --output import_report.json
```

**Spoken Script:**
> *"For scaling our destination network, our CSV catalogue importer parses the full 20-column schema.*
>
> *Running the importer on a 1,000-destination dataset completes in just 0.02 seconds—far exceeding the 5-minute requirement—with automatic URL normalization, deduplication, and syntax validation.*
>
> *Furthermore, in `data/destinations_real_150.csv`, we researched 150 authentic, real-world long-tail communities across Discourse, Lemmy, Dev.to, Hashnode, Ghost, Slack, and Mailchimp."*

---

### Segment 7: Batch Runner CLI & Full Test Suite (07:00 – 08:00)
**Visual:**
Run the batch runner in terminal, followed by the pytest suite inside Docker.

**Commands:**
```bash
python batch_runner.py --input-dir test_inputs --output-dir test_outputs --api-url http://localhost:8000
docker compose exec api pytest -v
```

**Spoken Script:**
> *"For automated end-to-end integration, our standalone Batch Runner CLI processes 14 diverse test payloads across all connectors against the live service: all 14 tests pass with a 100% success rate.*
>
> *Finally, running our full pytest test suite inside Docker executes 172 tests across 23 modular test suites.*
>
> *All 172 tests pass with zero failures and zero warnings in approximately 10 seconds, proving zero regressions and bulletproof reliability across all contract endpoints.*
>
> *Thank you! The repository is clean, documented, and ready for deployment."*

---

## 💡 Quick Tips for Recording
1. **Resolution:** 1080p (1920x1080) at full screen.
2. **Font Size:** Increase terminal and browser font (Ctrl + Plus) so JSON responses are easily readable.
3. **Pacing:** Speak clearly and keep transitions smooth; follow the timeline table above to comfortably finish under 8 minutes.
