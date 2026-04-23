"""
Knowledge Retriever Agent — Knowledge Retrieval
Retrieve relevant papers from online academic sources (IEEE/arXiv/Semantic Scholar/CrossRef)
and synthesize design insights via LLM.
"""

from __future__ import annotations
import logging
from typing import Optional
from utils.llm_client import LLMClient
from utils.paper_search import search_papers_online

logger = logging.getLogger(__name__)


class KnowledgeRetrieverAgent:
    """
    Knowledge Retriever Agent

    Retrieval strategy:
    1. Online academic search — IEEE / arXiv / Semantic Scholar / CrossRef (primary)
    2. LLM synthesis analysis — structured design insights from retrieved papers
    """

    # Default enabled online search sources (IEEE preferred, via CrossRef member filter)
    DEFAULT_ONLINE_SOURCES = ["ieee_crossref", "semantic_scholar", "crossref", "arxiv"]

    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        online_sources: Optional[list[str]] = None,
        config: Optional[dict] = None,
    ):
        self.llm = llm or LLMClient()
        self.online_sources = online_sources or self.DEFAULT_ONLINE_SOURCES
        self.config = config or {}

    def _max_tokens(self, node_name: str, fallback: Optional[int] = None) -> Optional[int]:
        resolver = getattr(self.llm, "get_max_tokens", None)
        if callable(resolver):
            value = resolver(node_name, fallback)
            return value if isinstance(value, int) or value is None else fallback
        return fallback

    def retrieve(
        self,
        task_spec: dict,
        top_k_papers: int = 5,
        top_k_algorithms: int = 5,
        top_k_templates: int = 3,
    ) -> dict:
        """
        Retrieve relevant papers online and synthesize design insights.

        Strategy:
        1. Extract 3-5 focused keyword groups from the task via LLM
        2. Combine all keyword groups into one query → single search → deduplicate
        3. LLM-filter for relevance, keep top_k_papers
        4. Synthesize design insights + extract relevant algorithm names

        Returns:
            {
                "relevant_algorithms": [...],
                "relevant_papers": [...],
                "design_insights": "...",
                "paper_search_query": "...",
            }
        """
        # 1. Extract multiple keyword groups
        keyword_groups = self._extract_keyword_groups(task_spec)
        logger.info("Extracted %d keyword groups: %s", len(keyword_groups), keyword_groups)

        # 2. Combined search: merge all keyword groups into one query for efficiency
        combined_query = " ".join(keyword_groups)
        logger.info("Combined search query: %s", combined_query)
        all_papers = search_papers_online(
            query=combined_query,
            max_results=max(top_k_papers * 3, 15),
            sources=self.online_sources,
        )
        logger.info("Combined search returned %d papers", len(all_papers))

        # 3. Deduplicate by title
        all_papers = self._dedup_papers(all_papers)
        logger.info("After dedup: %d candidate papers", len(all_papers))

        # 4. LLM relevance filter — keep only papers truly related to the task
        papers = self._filter_relevant_papers(task_spec, all_papers, top_k=top_k_papers)
        logger.info("After relevance filter: %d papers", len(papers))

        # 5. LLM synthesis analysis
        insights = self._synthesize_insights(task_spec, papers)

        # 6. Extract relevant algorithm names from papers + insights
        algorithms = self._extract_relevant_algorithms(task_spec, papers, insights)

        return {
            "relevant_algorithms": algorithms,
            "relevant_papers": papers,
            "design_insights": insights,
            "paper_search_query": combined_query,
        }

    @staticmethod
    def _as_text(value: object, default: str = "") -> str:
        """Normalize any field to a plain string."""
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, (list, tuple, set)):
            parts = [str(item).strip() for item in value if item not in (None, "")]
            return ", ".join(parts)
        return str(value).strip()

    def _extract_keyword_groups(self, task_spec: dict) -> list[str]:
        """Use LLM to extract 3-5 focused keyword groups for multi-query retrieval.

        Each keyword group is a short phrase (3-6 words) targeting a different
        aspect of the problem: algorithm family, system model, technique, etc.
        """
        category = self._as_text(task_spec.get("task_category"), "wireless task")
        description = self._as_text(task_spec.get("task_description"), "")
        system_model = task_spec.get("system_model") or {}
        waveform = self._as_text(system_model.get("waveform"), "")
        channel_model = self._as_text(system_model.get("channel_model"), "")
        antenna_config = self._as_text(system_model.get("antenna_config"), "")
        metric = self._as_text(
            (task_spec.get("performance_targets") or {}).get("primary_metric"), ""
        )
        approach = self._as_text((task_spec.get("design_preferences") or {}).get("approach"), "")

        prompt = (
            "You are an expert in wireless signal processing research. "
            "Extract exactly 3-5 focused keyword groups for searching academic papers.\n\n"
            "Each keyword group should be a short phrase (3-6 words) targeting a DIFFERENT aspect:\n"
            "- One for the core algorithm/technique (e.g., 'MUSIC algorithm DOA estimation')\n"
            "- One for the system model (e.g., 'uniform linear array mutual coupling')\n"
            "- One for the specific challenge (e.g., 'DOA estimation correlated noise low SNR')\n"
            "- Optionally one for alternative approaches (e.g., 'sparse signal recovery direction finding')\n"
            "- Optionally one for performance benchmark (e.g., 'Cramer-Rao bound angle estimation')\n\n"
            "Requirements:\n"
            "- Each group must be specific enough to find relevant IEEE/arXiv papers\n"
            "- Do NOT include generic terms like 'wireless communication' alone\n"
            "- Focus on terms that appear in paper titles and abstracts in this domain\n"
            "- Output ONLY the keyword groups, one per line, nothing else\n\n"
            f"Task category: {category}\n"
            f"Description: {description}\n"
            f"Waveform: {waveform}\n"
            f"Channel model: {channel_model}\n"
            f"Antenna config: {antenna_config}\n"
            f"Primary metric: {metric}\n"
            f"Approach preference: {approach}\n"
        )
        try:
            response = self.llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=self._max_tokens("knowledge_keyword_extraction"),
                node_name="knowledge_keyword_extraction",
            )
            groups = [
                line.strip().lstrip("0123456789.-) ").strip()
                for line in response.strip().splitlines()
                if line.strip() and len(line.strip()) > 5
            ]
            # Filter out overly long or empty entries
            groups = [g for g in groups if 5 < len(g) < 100]
            if groups:
                return groups[:5]
        except Exception as exc:
            logger.debug("LLM keyword group extraction failed: %s", exc)

        return self._fallback_keyword_groups(task_spec)

    def _fallback_keyword_groups(self, task_spec: dict) -> list[str]:
        """Fallback keyword groups when LLM extraction fails."""
        category = self._as_text(task_spec.get("task_category"), "wireless signal processing")
        description = self._as_text(task_spec.get("task_description"), "")
        waveform = self._as_text((task_spec.get("system_model") or {}).get("waveform"), "")
        approach = self._as_text((task_spec.get("design_preferences") or {}).get("approach"), "")

        groups = [f"{category} algorithm"]
        if description:
            # Take first meaningful phrase from description
            short_desc = " ".join(description.split()[:6])
            groups.append(short_desc)
        if waveform:
            groups.append(f"{waveform} signal processing")
        if approach:
            groups.append(f"{approach} wireless")
        return groups[:5] or ["wireless signal processing algorithm"]

    def _extract_relevant_algorithms(self, task_spec: dict, papers: list[dict], insights: str) -> list[str]:
        """Extract relevant algorithm names from retrieved papers and design insights."""
        category = self._as_text(task_spec.get("task_category"), "wireless signal processing")
        description = self._as_text(task_spec.get("task_description"), "")
        paper_context = "\n".join(
            f"- {p.get('title', '')}: {(p.get('abstract') or p.get('abstract_snippet') or '')[:120]}"
            for p in papers[:6]
        )
        prompt = (
            f"Task: {category} — {description}\n\n"
            f"Papers:\n{paper_context}\n\n"
            f"Design insights (excerpt):\n{insights[:600]}\n\n"
            "Extract the 3-8 most relevant algorithm or method names for this wireless signal processing task.\n"
            "Examples: MUSIC, ESPRIT, MMSE, ZF, OMP, ADMM, EM, Kalman Filter, LASSO, etc.\n"
            "Output ONLY algorithm names, one per line, no descriptions, no numbering."
        )
        try:
            response = self.llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=self._max_tokens("knowledge_algorithm_extraction", 150),
                node_name="knowledge_algorithm_extraction",
            )
            names = [
                line.strip().lstrip("•\u2013-*0123456789.) ")
                for line in response.strip().splitlines()
                if line.strip()
            ]
            names = [n for n in names if 1 < len(n) < 60]
            return names[:8]
        except Exception as exc:
            logger.debug("Algorithm extraction failed: %s", exc)
            return []

    @staticmethod
    def _dedup_papers(papers: list[dict]) -> list[dict]:
        """Deduplicate papers by title (case-insensitive)."""
        seen: set[str] = set()
        result: list[dict] = []
        for p in papers:
            key = p.get("title", "").lower().replace(" ", "")[:80]
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(p)
        return result

    def _filter_relevant_papers(
        self, task_spec: dict, papers: list[dict], top_k: int = 5
    ) -> list[dict]:
        """Use LLM to score and filter papers for relevance to the task."""
        if len(papers) <= top_k:
            return papers

        category = self._as_text(task_spec.get("task_category"), "unknown")
        description = self._as_text(task_spec.get("task_description"), "")

        paper_list = []
        for i, p in enumerate(papers):
            title = p.get("title", "")
            abstract = (p.get("abstract") or p.get("abstract_snippet") or "")[:200]
            paper_list.append(f"[{i}] {title}\n    Abstract: {abstract or '(none)'}")

        prompt = (
            f"Task: {category} — {description}\n\n"
            f"Below are {len(papers)} candidate papers. Select the {top_k} MOST RELEVANT "
            "papers for this specific wireless signal processing task.\n\n"
            "Relevance criteria:\n"
            "- Paper must be about wireless/signal processing/communications (NOT astronomy, physics, biology, etc.)\n"
            "- Paper should relate to the specific technique, algorithm, or system model in the task\n"
            "- Prefer papers with concrete algorithmic contributions over surveys\n\n"
            + "\n".join(paper_list)
            + f"\n\nOutput ONLY the indices of the top {top_k} most relevant papers, "
            "separated by commas (e.g., '0,3,5,7,2'). Nothing else."
        )
        try:
            response = self.llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=self._max_tokens("knowledge_relevance_filter", 100),
                node_name="knowledge_relevance_filter",
            )
            # Parse comma-separated indices
            indices = []
            for token in response.strip().split(","):
                token = token.strip()
                if token.isdigit():
                    idx = int(token)
                    if 0 <= idx < len(papers):
                        indices.append(idx)
            if indices:
                return [papers[i] for i in indices[:top_k]]
        except Exception as exc:
            logger.debug("LLM relevance filter failed, falling back to citation sort: %s", exc)

        # Fallback: sort by citation count and pick top_k
        papers.sort(key=lambda p: (p.get("citation_count") or 0), reverse=True)
        return papers[:top_k]

    def _synthesize_insights(self, task_spec: dict, papers: list) -> str:
        """Use LLM to synthesize retrieved papers into structured design insights."""
        if not papers:
            return "Online search returned no results (possibly a network issue), recommend starting with classic baseline methods."

        system_model = task_spec.get("system_model") or {}
        waveform = self._as_text(system_model.get("waveform"), "unknown")
        antenna_config = self._as_text(system_model.get("antenna_config"), "unknown")
        task_category = self._as_text(task_spec.get("task_category"), "unknown")

        paper_sections = []
        for i, p in enumerate(papers, start=1):
            title = p.get("title", "")
            year = p.get("year", "")
            source = p.get("source", "")
            citations = p.get("citation_count")
            cite_str = f"Citations:{citations}" if citations is not None else ""
            abstract = (p.get("abstract") or p.get("abstract_snippet") or "").strip()
            paper_sections.append(
                f"[P{i}] {title} ({year}, {source}{', ' + cite_str if cite_str else ''})\n"
                f"     Abstract: {abstract or '(No abstract)'}"
            )

        prompt = (
            f"Task category: {task_category}\n"
            f"System model: {waveform}, antenna config={antenna_config}\n\n"
            f"== Retrieved relevant papers (total {len(papers)}, showing first {len(paper_sections)}) ==\n"
            + "\n\n".join(paper_sections)
            + "\n\nImplementation policy: keep the final solution notebook-first, favor lightweight NumPy/Matplotlib execution, and avoid assumptions about optional third-party simulation libraries.\n\n"
            "Please output an in-depth analysis in the following structure (no length limit, be as thorough as possible):\n"
            "1. **Core Technical Roadmap**: Summarize the main algorithmic frameworks from these papers (e.g., sparse recovery/deep unfolding/end-to-end DL/classical optimization)\n"
            "2. **Key Innovation Extraction**: 1-2 most important technical contributions per paper (cite [P#])\n"
            "3. **Recommended Algorithm Framework**: Based on task characteristics, recommend the top 1-2 candidate technical approaches with rationale\n"
            "4. **Notebook Implementation Guidance**: What should be emphasized in the notebook narrative, executable experiment design, and result presentation\n"
            "5. **Caveats**: Common implementation pitfalls or mandatory constraints for this task"
        )
        return self.llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=self._max_tokens("knowledge_retrieval"),
            node_name="knowledge_retrieval",
        )
