"""
Online academic paper search tool

Supports multiple academic data sources:
- arXiv (free, no API key required)
- Semantic Scholar (free, no API key required, rate limited)
- CrossRef (free, covers IEEE/ACM/Elsevier and other publishers)

Search strategy:
  1. Concurrently query arXiv + Semantic Scholar + CrossRef
  2. Merge results, deduplicate and sort by relevance/citation count
  3. Return a unified format paper list
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

logger = logging.getLogger(__name__)

# ── Request timeout (seconds) ──
REQUEST_TIMEOUT = 10

# Lazy-load requests to avoid hard dependency at startup
try:
    import requests as _requests

    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False
    logger.warning("requests library not installed; online paper search will be skipped. Install via: pip install requests")


def _get(url: str, params: dict | None = None, headers: dict | None = None) -> dict | None:
    """Unified HTTP GET with timeout and error handling"""
    if not _HAS_REQUESTS:
        return None
    try:
        resp = _requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json() if "json" in resp.headers.get("Content-Type", "") else {"_text": resp.text}
    except Exception as exc:
        logger.debug("HTTP request failed [%s]: %s", url, exc)
        return None


# ════════════════ arXiv ════════════════

_ARXIV_NS = "http://www.w3.org/2005/Atom"


def _search_arxiv(query: str, max_results: int = 10) -> list[dict]:
    """
    Search papers via arXiv Atom API.

    Docs: https://arxiv.org/help/api/user-manual
    """
    url = "https://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    try:
        if not _HAS_REQUESTS:
            return []
        resp = _requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception as exc:
        logger.debug("arXiv search failed: %s", exc)
        return []

    ns = {"atom": _ARXIV_NS, "arxiv": "http://arxiv.org/schemas/atom"}
    papers: list[dict] = []
    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        summary_el = entry.find("atom:summary", ns)
        published_el = entry.find("atom:published", ns)
        id_el = entry.find("atom:id", ns)
        authors = [
            a.find("atom:name", ns).text
            for a in entry.findall("atom:author", ns)
            if a.find("atom:name", ns) is not None
        ]
        categories = [
            c.attrib.get("term", "")
            for c in entry.findall("atom:category", ns)
        ]

        title = (title_el.text or "").strip().replace("\n", " ")
        abstract = (summary_el.text or "").strip().replace("\n", " ")
        year = (published_el.text or "")[:4]
        arxiv_id = (id_el.text or "").split("/abs/")[-1] if id_el is not None else ""

        papers.append({
            "title": title,
            "abstract": abstract,
            "abstract_snippet": abstract[:300],
            "authors": authors[:5],
            "year": year,
            "source": "arXiv",
            "arxiv_id": arxiv_id,
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "categories": categories,
            "citation_count": None,
        })
    logger.info("arXiv search '%s' returned %d papers", query, len(papers))
    return papers


# ════════════════ Semantic Scholar ════════════════

_SS_API = "https://api.semanticscholar.org/graph/v1/paper/search"
_SS_FIELDS = "title,abstract,authors,year,externalIds,citationCount,fieldsOfStudy,openAccessPdf"


def _search_semantic_scholar(query: str, max_results: int = 10) -> list[dict]:
    """
    Search papers via Semantic Scholar Graph API.

    Docs: https://api.semanticscholar.org/api-docs/graph
    No API Key required, but rate limited (~100 req/5min)
    """
    params = {
        "query": query,
        "limit": min(max_results, 100),
        "fields": _SS_FIELDS,
    }
    data = _get(_SS_API, params=params)
    if not data or "data" not in data:
        return []

    papers: list[dict] = []
    for item in data.get("data", []):
        ext_ids = item.get("externalIds") or {}
        arxiv_id = ext_ids.get("ArXiv", "")
        doi = ext_ids.get("DOI", "")
        title = item.get("title", "")
        abstract = item.get("abstract") or ""
        authors_ = [a.get("name", "") for a in (item.get("authors") or [])[:5]]
        year = str(item.get("year") or "")
        citation_count = item.get("citationCount")
        pdf_info = item.get("openAccessPdf") or {}
        pdf_url = pdf_info.get("url", "")

        url = (
            f"https://arxiv.org/abs/{arxiv_id}"
            if arxiv_id
            else (f"https://doi.org/{doi}" if doi else "")
        )

        papers.append({
            "title": title,
            "abstract": abstract,
            "abstract_snippet": abstract[:300],
            "authors": authors_,
            "year": year,
            "source": "Semantic Scholar",
            "arxiv_id": arxiv_id,
            "doi": doi,
            "url": url,
            "pdf_url": pdf_url,
            "citation_count": citation_count,
            "fields": item.get("fieldsOfStudy") or [],
        })
    logger.info("Semantic Scholar search '%s' returned %d papers", query, len(papers))
    return papers


# ════════════════ CrossRef (IEEE/ACM/Elsevier) ════════════════

_CR_API = "https://api.crossref.org/works"
_CR_HEADERS = {"User-Agent": "AutoWiSPA/1.0 (mailto:research@autowispa.ai)"}

# IEEE's CrossRef member ID
_IEEE_MEMBER_ID = "263"


def _parse_crossref_items(items: list, source_label: str = "CrossRef") -> list[dict]:
    """Shared parser for CrossRef work items."""
    import re as _re
    papers: list[dict] = []
    for item in items:
        title_list = item.get("title") or []
        title = title_list[0] if title_list else ""
        if not title:
            continue

        abstract = item.get("abstract") or ""
        abstract = _re.sub(r"<[^>]+>", "", abstract).strip()

        author_list = item.get("author") or []
        authors_ = [
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in author_list[:5]
        ]
        pub_date = item.get("published") or {}
        date_parts = (pub_date.get("date-parts") or [[]])[0]
        year = str(date_parts[0]) if date_parts else ""
        doi = item.get("DOI", "")
        container = (item.get("container-title") or [""])[0]
        citation_count = item.get("is-referenced-by-count")

        label = source_label
        if source_label == "CrossRef" and container:
            label = f"CrossRef({container[:30]})"
        elif source_label == "IEEE" and container:
            label = f"IEEE({container[:30]})"

        papers.append({
            "title": title,
            "abstract": abstract,
            "abstract_snippet": abstract[:300],
            "authors": authors_,
            "year": year,
            "source": label,
            "doi": doi,
            "url": f"https://doi.org/{doi}" if doi else "",
            "citation_count": citation_count,
        })
    return papers


def _search_ieee_crossref(query: str, max_results: int = 10) -> list[dict]:
    """
    Search IEEE papers via CrossRef REST API filtered by IEEE member ID (263).

    This returns only IEEE-published papers (IEEE Transactions, IEEE Access, etc.)
    without requiring an IEEE Xplore API key.
    """
    params = {
        "query": query,
        "rows": min(max_results, 50),
        "select": "title,abstract,author,published,DOI,container-title,is-referenced-by-count",
        "sort": "relevance",
        "filter": f"member:{_IEEE_MEMBER_ID}",
    }
    data = _get(_CR_API, params=params, headers=_CR_HEADERS)
    if not data or "message" not in data:
        return []

    items = data.get("message", {}).get("items", [])
    papers = _parse_crossref_items(items, source_label="IEEE")
    logger.info("IEEE(CrossRef) search '%s' returned %d papers", query, len(papers))
    return papers


def _search_crossref(query: str, max_results: int = 10) -> list[dict]:
    """
    Search papers via CrossRef REST API (covers IEEE, ACM, Elsevier, etc.).

    Docs: https://api.crossref.org/swagger-ui/index.html
    """
    params = {
        "query": query,
        "rows": min(max_results, 50),
        "select": "title,abstract,author,published,DOI,container-title,is-referenced-by-count",
        "sort": "relevance",
        "filter": "type:journal-article,type:proceedings-article",
    }
    data = _get(_CR_API, params=params, headers=_CR_HEADERS)
    if not data or "message" not in data:
        return []

    items = data.get("message", {}).get("items", [])
    papers = _parse_crossref_items(items, source_label="CrossRef")
    logger.info("CrossRef search '%s' returned %d papers", query, len(papers))
    return papers


# ════════════════ Aggregated Search ════════════════

def _dedup(papers: list[dict]) -> list[dict]:
    """Deduplicate by title (case-insensitive, ignoring spaces)"""
    seen: set[str] = set()
    result: list[dict] = []
    for p in papers:
        key = p.get("title", "").lower().replace(" ", "")[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(p)
    return result


def _relevance_score(paper: dict, query_keywords: list[str]) -> float:
    """Simple relevance scoring for sorting"""
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    kw_score = sum(2.0 if kw in paper.get("title", "").lower() else (1.0 if kw in text else 0.0)
                   for kw in query_keywords)
    citation_bonus = min((paper.get("citation_count") or 0) / 200.0, 2.0)
    return kw_score + citation_bonus


def search_papers_online(
    query: str,
    max_results: int = 5,
    sources: Optional[list[str]] = None,
) -> list[dict]:
    """
    Concurrently query multiple academic data sources, returning a deduplicated and sorted paper list.

    Args:
        query:       Search query string
        max_results: Maximum papers returned (default 5)
        sources:     Enabled data sources, default ['ieee_crossref', 'semantic_scholar', 'crossref', 'arxiv']

    Returns:
        List[dict], each dict contains:
            title, abstract, abstract_snippet, authors, year,
            source, url, citation_count, arxiv_id(optional), doi(optional)
    """
    if not _HAS_REQUESTS:
        logger.warning("requests not installed; skipping online search")
        return []

    if sources is None:
        sources = ["ieee_crossref", "semantic_scholar", "crossref", "arxiv"]

    per_source = max(max_results, 10)

    source_funcs = {
        "ieee_crossref": lambda: _search_ieee_crossref(query, per_source),
        "arxiv": lambda: _search_arxiv(query, per_source),
        "semantic_scholar": lambda: _search_semantic_scholar(query, per_source),
        "crossref": lambda: _search_crossref(query, per_source),
    }

    all_papers: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        futures = {
            executor.submit(source_funcs[src]): src
            for src in sources
            if src in source_funcs
        }
        try:
            for future in as_completed(futures, timeout=REQUEST_TIMEOUT + 5):
                src = futures[future]
                try:
                    results = future.result()
                    all_papers.extend(results)
                except Exception as exc:
                    logger.warning("Data source %s search failed: %s", src, exc)
        except TimeoutError:
            timed_out = [futures[f] for f in futures if not f.done()]
            logger.warning("Paper search timed out; skipping sources: %s", timed_out)
            for f in futures:
                f.cancel()

    # Deduplicate
    all_papers = _dedup(all_papers)

    # Sort by relevance + citations
    query_keywords = [kw.lower() for kw in query.split() if len(kw) > 2]
    all_papers.sort(key=lambda p: _relevance_score(p, query_keywords), reverse=True)

    return all_papers[:max_results]
