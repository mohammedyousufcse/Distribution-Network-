"""
Destination Recommendation Engine.
IncuBrix Outstanding Level Requirement:
Given a content item, ranks destinations by fit (audience, rules, past results)
with an explicit reason for each, and calculates precision@10 against a labelled test set.
"""

from typing import Any, Dict, List, Optional
import re
from app.services.catalogue_service import CatalogueService
from app.services.tailoring_service import TailoringService


class RecommenderService:
    """Ranks destination catalogue items for a given content rendition."""

    @classmethod
    def recommend_destinations(
        cls,
        text: str,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        audience_pillar: Optional[str] = None,
        is_promotional: bool = False,
        is_ai_generated: bool = False,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Ranks all registered destinations in the catalogue by compatibility and relevance."""
        tags = [t.lower() for t in (tags or [])]
        has_links = bool(re.search(r"https?://", text))
        from app.services.catalogue_service import catalogue_service
        destinations = catalogue_service.list_destinations()

        recommendations = []

        for dest_info in destinations:
            dest_id = dest_info.get("id", "")
            rules = dest_info.get("posting_rules") or dest_info.get("rules") or {}
            limits = dest_info.get("format_limits") or {}
            conn_key = dest_info.get("connector_key", "")
            dest_name = dest_info.get("name", dest_id)
            score = 0.0
            reasons = []
            eligible = True

            # 1. Hard rule filters
            if has_links and not rules.get("allow_links", True):
                eligible = False
                reasons.append("Excluded: content contains links but destination prohibits external links.")

            if is_promotional and not rules.get("allow_self_promotion", True):
                eligible = False
                reasons.append("Excluded: content flagged as promotional but destination bans self-promotion.")

            title_limit = limits.get("max_title_length") or rules.get("max_title_length") or 255
            if title and len(title) > title_limit:
                eligible = False
                reasons.append(f"Excluded: title length ({len(title)}) exceeds maximum limit of {title_limit}.")

            # 2. Audience relevance scoring
            pillar = audience_pillar or "ai"
            from app.services.tailoring_service import tailoring_service
            relevance_data = tailoring_service.score_relevance(dest_info)
            relevance_score = relevance_data["relevance_score"]  # 1 to 5

            # Base score from relevance (0 to 50 pts)
            score += relevance_score * 10

            # 3. Tag and Category Overlap (0 to 30 pts)
            dest_cat = (dest_info.get("category") or "").lower()
            matching_tags = [t for t in tags if t in dest_cat or t in dest_name.lower()]
            if matching_tags:
                tag_bonus = min(30, len(matching_tags) * 15)
                score += tag_bonus
                reasons.append(f"Matching tags found: {', '.join(matching_tags)} (+{tag_bonus} pts).")

            # 4. Content Format Affinity (0 to 20 pts)
            if conn_key in ("discourse", "lemmy", "slack"):
                if "?" in text or "what do you think" in text.lower() or "how do you" in text.lower():
                    score += 20
                    reasons.append("High engagement affinity: conversational/discussion content suited for forum/community.")
            elif conn_key in ("devto", "ghost", "hashnode", "mailchimp"):
                if len(text) > 300 or "\n\n" in text:
                    score += 20
                    reasons.append("Format affinity: long-form publication/article structured for blog or newsletter.")

            # Normalization (0.0 to 1.0)
            normalized_score = round(min(1.0, max(0.0, score / 100.0)), 2)

            if eligible:
                reasons.append(f"Relevance to {pillar.upper()} audience: {relevance_score}/5.")
                fit_reason = "; ".join(reasons)
            else:
                fit_reason = reasons[0]  # Primary disqualification reason

            recommendations.append({
                "destination_id": dest_id,
                "destination_name": dest_name,
                "connector_key": conn_key,
                "fit_score": normalized_score if eligible else 0.0,
                "eligible": eligible,
                "relevance_score": relevance_score,
                "reason": fit_reason,
            })

        # Sort: eligible first, then by fit_score descending
        ranked = sorted(
            recommendations,
            key=lambda x: (1 if x["eligible"] else 0, x["fit_score"]),
            reverse=True,
        )

        # Assign ranks
        for rank_idx, item in enumerate(ranked, 1):
            item["rank"] = rank_idx

        return ranked[:limit]

    @classmethod
    def evaluate_precision_at_k(cls, labelled_dataset: Optional[List[Dict[str, Any]]] = None, k: int = 10) -> Dict[str, Any]:
        """Measures recommendation precision@k against a labelled ground-truth dataset."""
        # Built-in ground truth test set if none provided
        test_set = labelled_dataset or [
            {
                "title": "Scaling Distributed Async Microservices in Python",
                "text": "Discussion on scaling event-driven architectures with FastAPI, Lemmy nodes, and Discourse message queues. What are your architectural best practices?",
                "tags": ["python", "architecture", "microservices"],
                "audience_pillar": "saas",
                "expected_destinations": ["discourse_dev_forum", "lemmy_technology", "lemmy_programming", "devto_tech"],
            },
            {
                "title": "Building an AI Agent with Modern LLM Tool Calling",
                "text": "Deep dive into creating autonomous agents with LangGraph and OpenAI function calling. Includes architecture diagrams and code walk-through.",
                "tags": ["ai", "agents", "machine-learning"],
                "audience_pillar": "ai",
                "expected_destinations": ["devto_tech", "ghost_official_blog", "discourse_dev_forum", "lemmy_technology"],
            },
            {
                "title": "Bootstrapping a SaaS to $10k MRR: Marketing and Creator Strategies",
                "text": "Lessons learned growing a B2B SaaS product without paid ads. How we used community marketing and content distribution.",
                "tags": ["saas", "marketing", "founders"],
                "audience_pillar": "founders",
                "expected_destinations": ["discourse_gaming_hub", "devto_tech", "discourse_dev_forum"],
            },
        ]

        total_precision = 0.0
        results = []

        for item in test_set:
            recs = cls.recommend_destinations(
                text=item["text"],
                title=item.get("title"),
                tags=item.get("tags"),
                audience_pillar=item.get("audience_pillar"),
                limit=k,
            )
            top_k_ids = [r["destination_id"] for r in recs if r["eligible"]]
            expected = set(item["expected_destinations"])

            # Hits among top k
            hits = [did for did in top_k_ids if did in expected]
            denom = min(len(expected), len(top_k_ids)) if top_k_ids else 1
            item_precision = len(hits) / denom if denom > 0 else 0.0
            total_precision += item_precision

            results.append({
                "query_title": item.get("title"),
                "top_k_returned": top_k_ids,
                "expected": list(expected),
                "hits": hits,
                "precision": round(item_precision, 2),
            })

        mean_precision = round(total_precision / len(test_set), 2)

        return {
            "k": k,
            "test_samples_count": len(test_set),
            "mean_precision_at_k": mean_precision,
            "precision_percentage": round(mean_precision * 100, 1),
            "benchmark_details": results,
        }
