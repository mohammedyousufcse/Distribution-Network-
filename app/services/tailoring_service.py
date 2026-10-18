"""
Content Tailoring and Audience Relevance Scoring Engine.
IncuBrix Advanced Level Requirements:
1. Destination-specific content tailoring (discussion framing for forums,
   canonical URLs for articles, word-boundary truncation, hashtag styles).
2. Relevance scoring (1-5) against IncuBrix's core audience:
   AI, video, marketing, SaaS, creators, and founders.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple


INCUBRIX_AUDIENCE_PILLARS = {
    "ai": {"ai", "artificial intelligence", "ml", "machine learning", "deep learning", "llm", "neural", "prompt", "gpt"},
    "video": {"video", "multimedia", "streaming", "youtube", "media", "ctv", "audio", "podcast"},
    "marketing": {"marketing", "growth", "seo", "branding", "distribution", "social media", "content", "traffic"},
    "saas": {"saas", "software", "b2b", "cloud", "api", "microservice", "infrastructure", "devops"},
    "creators": {"creator", "creators", "creator economy", "content creator", "writer", "blogger", "newsletter", "influencer"},
    "founders": {"founder", "founders", "startup", "startups", "entrepreneur", "indie hacker", "bootstrapping", "business", "building in public"},
}


def truncate_at_word_boundary(text: str, max_chars: int, suffix: str = "...") -> str:
    """Truncate text at the nearest preceding whitespace boundary if it exceeds max_chars."""
    if not text or len(text) <= max_chars:
        return text

    allowed_length = max_chars - len(suffix)
    if allowed_length <= 0:
        return text[:max_chars]

    truncated = text[:allowed_length]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]

    return f"{truncated.rstrip()}{suffix}"


class TailoringService:
    """Service providing automatic per-destination content adaptation and audience scoring."""

    def score_relevance(self, destination: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate relevance score from 1 to 5 against IncuBrix's core audience.
        IncuBrix audience: AI, video, marketing, SaaS, creators, and founders.
        """
        text_corpus = " ".join([
            str(destination.get("name", "")),
            str(destination.get("audience", "")),
            str(destination.get("category", "")),
            " ".join(destination.get("audience_tags", []) if isinstance(destination.get("audience_tags"), list) else []),
        ]).lower()

        matched_pillars: Dict[str, List[str]] = {}
        for pillar, keywords in INCUBRIX_AUDIENCE_PILLARS.items():
            found_keywords = [kw for kw in keywords if re.search(r"\b" + re.escape(kw) + r"\b", text_corpus)]
            if found_keywords:
                matched_pillars[pillar] = found_keywords

        num_pillars = len(matched_pillars)

        if num_pillars >= 4:
            score = 5
            level_name = "Core Match"
        elif num_pillars == 3:
            score = 4
            level_name = "Strong Fit"
        elif num_pillars == 2:
            score = 3
            level_name = "Moderate Alignment"
        elif num_pillars == 1:
            score = 2
            level_name = "Tangential Relevance"
        else:
            score = 1
            level_name = "General Audience"

        pillars_str = ", ".join(matched_pillars.keys()).upper() if matched_pillars else "GENERAL"
        reason = f"{level_name}: Aligned with IncuBrix {pillars_str} segments."

        return {
            "destination_id": destination.get("id"),
            "relevance_score": score,
            "relevance_level": level_name,
            "relevance_reason": reason,
            "matched_pillars": matched_pillars,
        }

    def tailor_content(
        self,
        content: Dict[str, Any],
        destination: Dict[str, Any],
        canonical_base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Tailor title, body text, tags, and formatting to the target destination.
        - Forums (Discourse, Lemmy): Discussion-first framing with prompt questions.
        - Articles (Dev.to, Ghost, Hashnode): Structured Markdown with canonical URL.
        - Truncation: Enforces word-boundary limits without chopping words.
        - Hashtags: Normalized per platform conventions.
        """
        connector_key = str(destination.get("connector_key", "")).lower()
        surface = str(destination.get("surface", "post")).lower()
        format_limits = destination.get("format_limits", {})

        raw_title = str(content.get("title", "")).strip()
        raw_text = str(content.get("text", "")).strip()
        tags = list(content.get("tags") or content.get("metadata", {}).get("tags", []))
        canonical_url = content.get("canonical_url") or (f"{canonical_base_url.rstrip('/')}/post" if canonical_base_url else None)

        tailored_title = raw_title
        tailored_text = raw_text
        tailoring_applied: List[str] = []

        # 1. Forum Tailoring (Discourse, Lemmy, Reddit, Moderated boards)
        if surface in ("topic", "community_post", "forum_post", "moderated_forum") or connector_key in ("discourse", "lemmy"):
            # Discussion-first framing
            if not any(tailored_text.endswith(q) for q in ("?", "?\n")):
                tailored_text = f"{tailored_text}\n\nWhat are your thoughts on this? Have you faced similar challenges in your workflows?"
                tailoring_applied.append("Added discussion-first community hook prompt")

            # Remove leading hashtag symbols for cleaner forum titles
            if tailored_title.startswith("#"):
                tailored_title = tailored_title.lstrip("# ").strip()
                tailoring_applied.append("Stripped markdown headers from forum title")

        # 2. Long-Form Publishing (Dev.to, Ghost, Hashnode)
        elif surface in ("article", "post", "page") or connector_key in ("devto", "ghost", "hashnode"):
            # Ensure article has a strong title
            if not tailored_title and "\n" in tailored_text:
                first_line, rest = tailored_text.split("\n", 1)
                tailored_title = first_line.lstrip("# ").strip()
                tailored_text = rest.strip()
                tailoring_applied.append("Extracted first line as article title")

            # Append canonical citation if provided
            if canonical_url and "canonical" not in tailored_text.lower():
                tailored_text = f"{tailored_text}\n\n---\n*Originally published at [{canonical_url}]({canonical_url})*"
                tailoring_applied.append(f"Appended canonical backlink to {canonical_url}")

        # 3. Word-Boundary Truncation
        max_body_len = format_limits.get("max_body_length") or format_limits.get("max_text_length") or destination.get("policy", {}).get("max_length")
        if max_body_len and len(tailored_text) > max_body_len:
            tailored_text = truncate_at_word_boundary(tailored_text, max_body_len)
            tailoring_applied.append(f"Truncated body at word boundary to {max_body_len} chars")

        max_title_len = format_limits.get("max_title_length", 255)
        if tailored_title and len(tailored_title) > max_title_len:
            tailored_title = truncate_at_word_boundary(tailored_title, max_title_len)
            tailoring_applied.append(f"Truncated title at word boundary to {max_title_len} chars")

        # 4. Hashtag Normalization
        if connector_key in ("devto", "hashnode"):
            # Clean tags without '#' symbol, lowercase, max 4
            clean_tags = [re.sub(r"[^a-zA-Z0-9]", "", t).lower() for t in tags][:4]
            tags = clean_tags
            tailoring_applied.append(f"Normalized tags for {connector_key}: {tags}")

        return {
            "destination_id": destination.get("id"),
            "connector_key": connector_key,
            "surface": surface,
            "title": tailored_title,
            "text": tailored_text,
            "tags": tags,
            "canonical_url": canonical_url,
            "tailoring_applied": tailoring_applied,
        }


tailoring_service = TailoringService()
