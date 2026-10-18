"""
AI Rules Capture & Human Confirmation Service.
IncuBrix Advanced Level Requirement:
Reads a community's rules page/text, proposes its posting rules via rule extraction heuristics,
and requires explicit human confirmation before the rules are active.
"""

from typing import Any, Dict, List, Optional
import re
import uuid
import time


class RulesCaptureService:
    """Extracts, proposes, and manages human confirmation of destination posting rules."""

    _STORE: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def propose_rules(
        cls,
        community_name: str,
        rules_text: str,
        rules_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyzes community guidelines text and proposes posting rules."""
        text_lower = rules_text.lower()
        reasons: List[str] = []

        # 1. Self-promotion analysis
        allow_self_promotion = True
        if re.search(r"\b(no self[- ]promotion|no promo|no spam|no advertising|self[- ]promotion (is )?forbidden|no commercial)\b", text_lower):
            allow_self_promotion = False
            reasons.append("Detected strict ban on self-promotion or advertising.")

        # 2. Link policy analysis
        allow_links = True
        if re.search(r"\b(no (external )?links|links (are )?forbidden|no link drops|link shorteners (are )?banned|text[- ]only)\b", text_lower):
            allow_links = False
            reasons.append("Detected prohibition on external links or link dropping.")

        # 3. Frequency cap analysis
        weekly_limit = 5  # default baseline
        week_match = re.search(r"(\d+)\s*(?:post|submission|article)s?\s*(?:per|\/|every)\s*week", text_lower)
        day_match = re.search(r"(\d+)\s*(?:post|submission|article)s?\s*(?:per|\/|every)\s*day", text_lower)
        if week_match:
            weekly_limit = int(week_match.group(1))
            reasons.append(f"Explicit weekly rate constraint detected: max {weekly_limit} posts/week.")
        elif day_match:
            daily = int(day_match.group(1))
            weekly_limit = daily * 7
            reasons.append(f"Daily post limit of {daily} detected (converted to {weekly_limit}/week).")
        elif "one post per week" in text_lower or "1 post a week" in text_lower:
            weekly_limit = 1
            reasons.append("Single weekly submission rule detected.")

        # 4. AI content disclosure analysis
        require_ai_disclosure = False
        if re.search(r"\b(ai[- ]generated|ai content|generative ai|llm|disclose ai|ai disclosure)\b", text_lower):
            require_ai_disclosure = True
            reasons.append("Guidelines require explicit disclosure or tagging for AI-generated text.")

        # 5. Character and title limits
        title_limit = 255
        title_match = re.search(r"title\s*(?:under|limit|max(?:imum)?)\s*(\d+)", text_lower)
        if title_match:
            title_limit = int(title_match.group(1))
            reasons.append(f"Specific title length constraint identified: {title_limit} characters.")

        proposal_id = f"rule_prop_{uuid.uuid4().hex[:10]}"
        confidence = min(0.98, 0.70 + (len(reasons) * 0.07))

        proposal = {
            "proposal_id": proposal_id,
            "community_name": community_name,
            "rules_url": rules_url or "https://community.example.com/guidelines",
            "extracted_at": time.time(),
            "status": "pending_human_confirmation",
            "confidence_score": round(confidence, 2),
            "reasoning": "; ".join(reasons) if reasons else "Default standard community guidelines inferred.",
            "proposed_rules": {
                "weekly_limit": weekly_limit,
                "allow_links": allow_links,
                "allow_self_promotion": allow_self_promotion,
                "require_ai_disclosure": require_ai_disclosure,
                "title_max_chars": title_limit,
            },
        }

        cls._STORE[proposal_id] = proposal
        return proposal

    @classmethod
    def confirm_rules(
        cls,
        proposal_id: str,
        confirmed_by: str,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """A person reviews and confirms (or modifies) the proposed rules."""
        proposal = cls._STORE.get(proposal_id)
        if not proposal:
            raise KeyError(f"Rule proposal '{proposal_id}' not found.")

        final_rules = dict(proposal["proposed_rules"])
        if overrides:
            final_rules.update(overrides)

        proposal["status"] = "confirmed"
        proposal["confirmed_by"] = confirmed_by
        proposal["confirmed_at"] = time.time()
        proposal["active_rules"] = final_rules
        cls._STORE[proposal_id] = proposal

        return {
            "proposal_id": proposal_id,
            "community_name": proposal["community_name"],
            "status": "confirmed",
            "confirmed_by": confirmed_by,
            "active_rules": final_rules,
            "message": "Posting rules confirmed and activated for destination.",
        }

    @classmethod
    def get_proposal(cls, proposal_id: str) -> Optional[Dict[str, Any]]:
        """Fetch proposal details by ID."""
        return cls._STORE.get(proposal_id)
