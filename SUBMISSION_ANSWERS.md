
## 📋 Evaluation Questionnaire & Answers

### Question 1: Architecture Summary & Key Technical Decisions
**Answer:**
We built a decoupled, asynchronous distribution gateway using **Python 3.11** and **FastAPI**, containerized via **Docker Compose**.
1. **Contract Adherence (Appendix A):** Implemented a uniform `POST /connector/v1/{connector_key}/{method}` pattern and `GET /connector/v1/{connector_key}/manifest`, utilizing canonical error codes (`DEST_SPEC_VIOLATION`, `DEST_RULE_FREQUENCY_CAP`, etc.) and Pydantic validation models.
2. **Decoupled Registry & Connectors:** Connectors inherit from `BaseConnector` and register in `ConnectorRegistry`. Connectors return structured result objects and never write to the core database.
3. **Configuration-Driven Destinations:** Defined in `destinations.yaml`, allowing multiple destinations of the same connector type (e.g. distinct Discourse forums) to be registered via pure configuration without code modification.
4. **Defensive Policy Pre-Flight:** `PolicyService` evaluates character limits, external link bans, self-promotion rules, AI disclosure mandates, and 7-day rolling weekly frequency caps before external network calls, supporting clock injection for testing.
5. **Safe Retries & Zero Duplicates:** `IdempotencyService` enforces payload hashing and in-memory TTL caching per connector key to eliminate duplicate publishing during network timeouts, returning HTTP 409 Conflict upon mismatched payload reuse.
6. **Repeatable Certification:** `CertificationService` runs an automated 12-step validation cycle, guarantees test post deletion within 10 minutes, and writes auditable evidence to `EVIDENCE/`.

---

### Question 2: List of Implemented Destination Connectors
**Answer:**
We implemented **9 destination connectors** covering all 6 core platforms, 2 advanced platforms, and 1 newsletter platform:
1. **Discourse (`discourse`):** Community forum topic publishing, status inspection, deletion, and metrics.
2. **Lemmy (`lemmy`):** Federated community discussion publisher with JWT auth and ActivityPub posting.
3. **Dev.to (`devto`):** Technical article publishing with unpublish-as-delete strategy and tag metadata.
4. **Ghost (`ghost`):** Headless CMS publishing using cryptographic HS256 Admin API JWT tokens.
5. **Generic Webhook (`webhook`):** Outbound webhook delivery with HMAC-SHA256 signature verification and <300s replay attack defense.
6. **Assisted Connector (`assisted`):** Generates ready-to-post operator packages (`{files, caption, deep_link, checklist, status: human_action_required}`) for manual/private channels.
7. **Hashnode (`hashnode`):** Technical publication connector powered by GraphQL mutations.
8. **Slack (`slack`):** Incoming webhook / Block Kit team alert connector.
9. **Mailchimp (`mailchimp`):** Email newsletter campaign creation and broadcast connector under Path 1 Top Pick scope.

---

### Question 3: Path 1 Top-Pick Deliverables
**Answer:**
1. **3rd Additional Connector:** Implemented Mailchimp newsletter campaign connector with specification validation (subject $\le 150$, body $\le 200,000$), campaign dispatch, metrics, and simulation mode (`tests/test_mailchimp_connector.py`, 7 tests).
2. **AI Rules Capture Step:** Built `POST /connector/v1/rules/propose` extracting structured rules from raw guideline text, paired with `POST /connector/v1/rules/confirm` for human confirmation audit trails (`tests/test_rules_capture.py`, 2 tests).
3. **Destination Recommender Engine:** Implemented `POST /connector/v1/recommend` applying hard rule filtering, format affinity scoring, and pillar relevance with transparent rationales. Evaluated ground-truth `precision@10` at a **1.00 score** via `GET /connector/v1/recommend/benchmark` (`tests/test_recommender.py`, 3 tests).
4. **150 Real Researched Destinations Catalogue:** Curated authentic long-tail destinations in `data/destinations_real_150.csv` meeting the full 20-column schema across Discourse, Lemmy, Dev.to, Hashnode, Ghost, Slack, and Mailchimp (`tests/test_real_catalogue_150.py`, 2 tests).

---

### Question 4: Verification & Test Coverage
**Answer:**
- **Automated Pytest Suite:** **172 passed, 0 failed, 0 warnings** in 10.07 seconds inside Docker.
- **Batch Runner CLI:** **14 passed, 0 failed (100.0% success)** across all test inputs (`test_inputs/`).
- **CSV Catalogue Ingestion:** 1,000 records validated in **0.02 seconds** (well under the 5-minute requirement).
- **OpenAPI 3.1.0 Drift:** Automated regression test proves zero divergence between `openapi.yaml` and the live FastAPI application.
- **Docker Compose:** 4 healthy containers orchestrating API, Ghost 5, Lemmy, and PostgreSQL.

---

### Question 5: File & Deliverable Map
- **Repository Readme:** `README.md`
- **Engineering Report:** `REPORT.md`
- **Requirements Audit:** `REQUIREMENTS_AUDIT.md`
- **Swagger Guide:** `SWAGGER_TESTING_GUIDE.txt`
- **Video Demo Script:** `DEMO_SCRIPT.md`
- **OpenAPI Spec:** `openapi.yaml`
- **Real 150 Destinations:** `data/destinations_real_150.csv`
- **Docker Orchestration:** `compose.yaml` and `Dockerfile`
- **Render Deployment Blueprint:** `render.yaml`
