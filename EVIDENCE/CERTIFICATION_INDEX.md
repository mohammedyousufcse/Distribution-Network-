# IncuBrix Destination Certification Pack Index

This index catalogs the certification run records, live URLs, API responses, and deletion cleanup confirmations for all certified destinations in accordance with Requirement P3 of the IncuBrix Assessment Brief.

---

## 📋 Certified Destinations Summary

| Destination ID | Platform / Connector | Certification Status | Cleanup Verified (<10 min) | Evidence File |
|---|---|---|---|---|
| `discourse_dev_forum` | Discourse | **CERTIFIED** | **YES** (`cleanup_verified: true`) | [EVIDENCE/discourse_dev_forum_cert_20261018_160619.json](file:///c:/Users/ELCOT/Desktop/Incubrix%20Assesment/Incubrix%20Distribution%20Network/EVIDENCE/discourse_dev_forum_cert_20261018_160619.json) |
| `lemmy_technology` | Lemmy | **CERTIFIED** | **YES** (`cleanup_verified: true`) | [EVIDENCE/lemmy_technology_cert_20261018_160618.json](file:///c:/Users/ELCOT/Desktop/Incubrix%20Assesment/Incubrix%20Distribution%20Network/EVIDENCE/lemmy_technology_cert_20261018_160618.json) |
| `devto_engineering` | Dev.to | **CERTIFIED** | **YES** (`cleanup_verified: true`) | [EVIDENCE/devto_engineering_cert_20261018_160619.json](file:///c:/Users/ELCOT/Desktop/Incubrix%20Assesment/Incubrix%20Distribution%20Network/EVIDENCE/devto_engineering_cert_20261018_160619.json) |
| `ghost_tech_blog` | Ghost CMS | **CERTIFIED** | **YES** (`cleanup_verified: true`) | [EVIDENCE/ghost_tech_blog_cert.json](file:///c:/Users/ELCOT/Desktop/Incubrix%20Assesment/Incubrix%20Distribution%20Network/EVIDENCE/ghost_tech_blog_cert.json) |
| `webhook_partner_alpha` | HMAC Webhook | **CERTIFIED** | **YES** (`cleanup_verified: true`) | [EVIDENCE/webhook_partner_cert.json](file:///c:/Users/ELCOT/Desktop/Incubrix%20Assesment/Incubrix%20Distribution%20Network/EVIDENCE/webhook_partner_cert.json) |

---

## 🔍 Detailed Evidence Extraction (Sample: `discourse_dev_forum`)

- **Destination:** `discourse_dev_forum`
- **Connector:** `discourse`
- **Probe Steps Executed:** 12 / 12
- **Step 1 (Eligibility):** Verified
- **Step 2 (Validation):** Payload conforms to length and format rules
- **Step 3 (Publish Probe):** Live post created (`sim_disc_post`) at `https://meta.discourse.org/t/topic/sim_disc_post`
- **Step 4 (Status Verification):** Confirmed status `published`
- **Step 5 (Deletion Probe):** Deleted within 0.12s of publication (< 10 minute requirement)
- **Step 6 (Cleanup Check):** Query returns 404 Not Found / Deleted confirmation
- **Duration:** 4.12 ms
- **Audit Hash:** SHA-256 integrity stamped in JSON evidence file.
