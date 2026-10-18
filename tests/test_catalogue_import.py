"""Unit and integration tests for CSV Catalogue Import and de-duplication."""

import asyncio
import pytest
from app.services.catalogue_import_service import catalogue_import_service, normalize_url


def test_normalize_url():
    assert normalize_url("https://Meta.Discourse.Org/ ") == "https://meta.discourse.org"
    assert normalize_url("http://Lemmy.World///") == "http://lemmy.world"
    assert normalize_url("dev.to/api") == "https://dev.to/api"


def test_catalogue_import_validation_and_deduplication():
    csv_sample = """name,url,platform_key,surface,category,audience_tags,language,geo,est_audience,rules_url,frequency_cap,self_promo_allowed,link_policy,disclosure_required,automation_allowed,connector_key,relevance_score,relevance_reason,level,last_certified_at
Discourse Tech,https://meta.discourse.org,discourse,topic,technology,ai;saas,en,global,50000,https://meta.discourse.org/rules,7,true,allowed,false,true,discourse,5,High AI affinity,L3,2026-10-17
Discourse Tech Duplicate,https://meta.discourse.org/,discourse,topic,technology,ai;saas,en,global,50000,https://meta.discourse.org/rules,7,true,allowed,false,true,discourse,5,High AI affinity,L3,2026-10-17
Invalid Row Missing Name,,lemmy,community_post,tech,saas,en,global,1000,http://rules,7,true,allowed,false,true,lemmy,3,Reason,L3,2026-10-17
Lemmy Programming,https://programming.dev,lemmy,community_post,engineering,devs,en,global,20000,https://programming.dev/rules,5,false,allowed,true,true,lemmy,4,Devs,L3,2026-10-17
"""
    report = asyncio.run(catalogue_import_service.import_csv_content(csv_sample, mock_reachability=True))

    assert report["total_rows_processed"] == 4
    assert report["imported_count"] == 2
    assert report["duplicate_count"] == 1
    assert report["invalid_count"] == 1
    assert len(report["errors"]) == 2  # 1 duplicate + 1 invalid row
    assert report["valid_destinations"][0]["name"] == "Discourse Tech"
    assert report["valid_destinations"][1]["name"] == "Lemmy Programming"
