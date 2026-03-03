"""Query rewriter: natural language → keyword expansion → FTS5 queries.

Converts conversational queries into effective search terms.
No LLM required — uses stopword removal, synonym expansion, and
compound keyword detection.

Also detects "recall intent" — when users reference past work
("we figured this out", "how did we do X", "what was the command for").
"""

from __future__ import annotations

import re

# Common English stopwords that add no search value
STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "must",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
    "they", "them", "their", "this", "that", "these", "those",
    "what", "which", "who", "whom", "when", "where", "why", "how",
    "not", "no", "nor", "but", "or", "and", "so", "if", "then",
    "of", "in", "on", "at", "to", "for", "with", "by", "from",
    "up", "out", "about", "into", "through", "during", "before", "after",
    "just", "also", "very", "too", "quite", "really", "only",
    "all", "any", "some", "every", "each", "both", "few", "more",
    "did", "last", "time", "find", "show", "get", "tell",
})

# Domain-specific synonym expansion for coding sessions
SYNONYMS: dict[str, list[str]] = {
    "auth": ["authentication", "login", "JWT", "token", "session"],
    "authentication": ["auth", "login", "JWT", "token"],
    "login": ["auth", "authentication", "signin"],
    "hook": ["hooks", "PreToolUse", "PostToolUse", "SessionStart", "SessionEnd"],
    "hooks": ["hook", "PreToolUse", "PostToolUse", "SessionStart", "SessionEnd"],
    "config": ["configuration", "settings", "setup", ".env"],
    "configure": ["config", "configuration", "settings", "setup"],
    "settings": ["config", "configuration", "settings.json"],
    "error": ["errors", "bug", "fix", "broke", "broken", "fail", "failed"],
    "bug": ["error", "fix", "broke", "broken", "fail"],
    "broke": ["error", "broken", "fail", "failed", "bug"],
    "test": ["tests", "testing", "pytest", "jest", "spec"],
    "deploy": ["deployment", "CI", "CD", "pipeline", "release"],
    "database": ["db", "SQL", "SQLite", "postgres", "migration", "schema"],
    "db": ["database", "SQL", "SQLite", "schema"],
    "api": ["endpoint", "route", "REST", "webhook"],
    "webhook": ["webhook", "endpoint", "callback", "hook"],
    "escrow": ["escrow", "deposit", "funds", "hold"],
}


def extract_keywords(query: str) -> list[str]:
    """Extract meaningful keywords from a natural language query.

    Returns 3-5 keywords ordered by likely importance.
    """
    # Lowercase and split
    words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_.-]*', query.lower())

    # Remove stopwords
    meaningful = [w for w in words if w not in STOPWORDS]

    # If everything was stopwords, fall back to longest non-stopword-like words
    if not meaningful:
        meaningful = sorted(words, key=len, reverse=True)[:3]

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for w in meaningful:
        if w not in seen:
            seen.add(w)
            unique.append(w)

    # Cap at 5 keywords
    return unique[:5]


def expand_keywords(keywords: list[str]) -> list[str]:
    """Add domain-specific synonyms to keyword list.

    Returns expanded list (original keywords first, then synonyms).
    Capped at 8 total to avoid query explosion.
    """
    expanded = list(keywords)
    seen = set(k.lower() for k in keywords)

    for kw in keywords:
        for synonym in SYNONYMS.get(kw.lower(), []):
            if synonym.lower() not in seen:
                expanded.append(synonym)
                seen.add(synonym.lower())

    return expanded[:8]


def rewrite_query(query: str) -> dict:
    """Full pipeline: NL query → extracted keywords → expanded keywords.

    Returns:
        {
            "original": str,
            "keywords": list[str],       # extracted from NL
            "expanded": list[str],        # with synonyms added
            "fts_queries": list[str],     # ready for FTS5 MATCH
        }
    """
    keywords = extract_keywords(query)
    expanded = expand_keywords(keywords)

    # Build FTS5 queries — each keyword gets its own query
    # FTS5 MATCH uses double-quoted terms for exact matching
    fts_queries = [f'"{kw}"' for kw in expanded]

    return {
        "original": query,
        "keywords": keywords,
        "expanded": expanded,
        "fts_queries": fts_queries,
    }


# ── Recall Intent Detection ─────────────────────────────────────────

# Patterns that signal the user is referencing past work.
# Each pattern captures the "topic" portion after the recall phrase.
_RECALL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bwe (?:already |previously )?(?:figured|worked|solved|did|fixed|handled|implemented|set up|built|wrote|discussed) (?:this |that |it )?(?:out )?(.*)", re.I),
    re.compile(r"\bwe did this before\b[:\s]*(.*)", re.I),
    re.compile(r"\bhow did (?:we|I|you) (?:do|fix|solve|handle|implement|set up|configure|build|write) (.*)", re.I),
    re.compile(r"\bwhat was the (?:command|approach|solution|fix|way|method|pattern|code) (?:for|to|we used for) (.*)", re.I),
    re.compile(r"\bremember (?:when|how) (?:we|I|you) (.*)", re.I),
    re.compile(r"\bwe['\u2019]ve (?:done|seen|had) this (?:before)?\b[:\s]*(.*)", re.I),
    re.compile(r"\blast time (?:we|I|you) (.*)", re.I),
    re.compile(r"\bdidn['\u2019]t (?:we|I|you) (?:already )?(.*)", re.I),
    re.compile(r"\bwasn['\u2019]t there (?:a|an|some) (.*)", re.I),
]


def detect_recall_intent(text: str) -> dict | None:
    """Detect if text contains a recall-intent phrase.

    Returns:
        None if no recall intent detected.
        Otherwise: {"match": str, "topic": str, "keywords": list[str]}
        where topic is the extracted subject after the recall phrase,
        and keywords are the meaningful search terms.
    """
    text = text.strip()
    for pattern in _RECALL_PATTERNS:
        m = pattern.search(text)
        if m:
            # The captured group is the topic portion
            topic = m.group(m.lastindex or 1).strip().rstrip("?.,!")
            if not topic:
                # Pattern matched but no topic captured — use full text
                topic = text
            keywords = extract_keywords(topic)
            if not keywords:
                keywords = extract_keywords(text)
            return {
                "match": m.group(0).strip(),
                "topic": topic,
                "keywords": keywords,
            }
    return None
