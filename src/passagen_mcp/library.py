from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from passagen.assistant.retrieval import InMemorySectionRetrieval, RetrievedSection
from passagen.catalog import (
    CatalogNotFoundError,
    CatalogService,
    InvalidArtifactError,
    PaperFilters,
    PaperSort,
    PaperView,
    SortDirection,
    TagMatch,
    validate_summary_json,
)
from passagen.config import AssistantSettings, LlmSettings
from passagen.domain import PaperStatus
from passagen.parsing import ParsedPaper
from passagen.research import CollectionReportService, CollectionSynthesisService
from passagen.research.schemas import CollectionArtifact
from passagen.research.schemas import CollectionReportView as CoreReportView
from passagen.stages.abstract_fixing import load_cleaned_abstract
from passagen.storage.repository import get_artifact
from pydantic import ValidationError

from passagen_mcp.schemas import (
    AbstractContent,
    ArtifactAvailability,
    CollectionArtifactRef,
    CollectionContextResult,
    CollectionDetail,
    CollectionItem,
    CollectionListResult,
    CollectionMember,
    CollectionRef,
    CollectionReportItem,
    CollectionReportListResult,
    CollectionReportView,
    CollectionSynthesisView,
    ContextPart,
    PaperContextResult,
    PaperListItem,
    PaperListResult,
    PaperMetadata,
    SectionHit,
    SectionSearchResult,
    SourceStatusView,
    SummarySection,
    TagItem,
    TagListResult,
    TagRef,
    UnavailableContent,
)

MAX_SEARCH_PAPERS = 100
MAX_EXPLICIT_SEARCH_PAPERS = 50


class LibraryRequestError(ValueError):
    pass


class LibraryReader:
    """Agent-oriented projection over a Passagen library."""

    def __init__(
        self,
        database_path: Path,
        data_dir: Path,
        llm_settings: LlmSettings | None = None,
        assistant_settings: AssistantSettings | None = None,
    ) -> None:
        self.database_path = database_path.expanduser().resolve()
        self.data_dir = data_dir.expanduser().resolve()
        self.catalog = CatalogService(self.database_path, self.data_dir)
        llm = llm_settings or LlmSettings()
        self.syntheses = CollectionSynthesisService(
            self.database_path, self.data_dir, llm, assistant_settings
        )
        self.reports = CollectionReportService(
            self.database_path, self.data_dir, llm, assistant_settings
        )

    def list_papers(
        self,
        *,
        title_query: str | None = None,
        status: PaperStatus | None = None,
        tag_ids: Sequence[str] = (),
        tag_match: TagMatch = TagMatch.ALL,
        venue: str | None = None,
        year: int | None = None,
        collection_id: str | None = None,
        unfiled: bool = False,
        sort: PaperSort = PaperSort.IMPORTED_AT,
        direction: SortDirection = SortDirection.DESC,
        page_size: int = 20,
        cursor: str | None = None,
    ) -> PaperListResult:
        if not 1 <= page_size <= 100:
            raise LibraryRequestError("page_size must be between 1 and 100")
        criteria = {
            "title_query": title_query,
            "status": status.value if status else None,
            "tag_ids": list(tag_ids),
            "tag_match": tag_match.value,
            "venue": venue,
            "year": year,
            "collection_id": collection_id,
            "unfiled": unfiled,
            "sort": sort.value,
            "direction": direction.value,
            "page_size": page_size,
        }
        offset = _decode_cursor(cursor, criteria)
        self._validate_scope(tag_ids, collection_id)
        page = self.catalog.list_papers(
            PaperFilters(
                query=title_query,
                status=status,
                tag_ids=tuple(tag_ids),
                tag_match=tag_match,
                venue=venue,
                year=year,
                collection_id=collection_id,
                unfiled=unfiled,
            ),
            sort=sort,
            direction=direction,
            limit=page_size,
            offset=offset,
        )
        tags, collections = self._references()
        next_offset = offset + len(page.items)
        return PaperListResult(
            items=[self._list_item(paper, tags, collections) for paper in page.items],
            total=page.total,
            next_cursor=(
                _encode_cursor(next_offset, criteria) if next_offset < page.total else None
            ),
        )

    def get_paper_context(
        self,
        paper_id: str,
        *,
        include: Sequence[ContextPart] = (ContextPart.ABSTRACT, ContextPart.SUMMARY),
        summary_sections: Sequence[SummarySection] = (),
        prefer_cleaned_abstract: bool = True,
    ) -> PaperContextResult:
        paper = self.catalog.get_paper(paper_id)
        tags, collections = self._references()
        result = PaperContextResult(paper=self._metadata(paper, tags, collections))
        kinds = set(paper.artifact_kinds)
        if ContextPart.ABSTRACT in include:
            result.abstract = self._abstract(paper, prefer_cleaned=prefer_cleaned_abstract)
            if result.abstract is None:
                result.unavailable.append(
                    UnavailableContent(kind="abstract", reason="not_available")
                )
        if ContextPart.SUMMARY in include:
            if "summary_json" not in kinds:
                result.unavailable.append(
                    UnavailableContent(kind="summary", reason="artifact_not_generated")
                )
            else:
                summary = self._summary(paper_id)
                if summary_sections:
                    selected = {section.value for section in summary_sections}
                    summary = {
                        key: value
                        for key, value in summary.items()
                        if key in {"schema_version", "identity"} or key in selected
                    }
                result.summary = summary
        if ContextPart.OUTLINE in include:
            if "outline_md" not in kinds:
                result.unavailable.append(
                    UnavailableContent(kind="outline", reason="artifact_not_generated")
                )
            else:
                result.outline = self._text_artifact(paper_id, "outline_md")
        if ContextPart.NOTE in include:
            result.note = self.catalog.get_paper_note(paper_id)
        return result

    def list_tags(self) -> TagListResult:
        return TagListResult(
            items=[
                TagItem(
                    id=tag.id,
                    name=tag.name,
                    color=tag.color,
                    created_at=tag.created_at,
                    paper_count=tag.paper_count,
                )
                for tag in self.catalog.list_tag_usage()
            ]
        )

    def list_collections(self) -> CollectionListResult:
        items = []
        for item in self.catalog.list_collections():
            collection = self.catalog.get_collection(item.id)
            items.append(self._collection_item(collection, len(collection.papers)))
        return CollectionListResult(items=items)

    def create_collection(self, name: str, description: str | None = None) -> CollectionDetail:
        collection = self.catalog.create_collection(name, description)
        return self.get_collection(collection.id)

    def add_papers_to_collection(
        self, collection_id: str, paper_ids: Sequence[str]
    ) -> CollectionDetail:
        if not paper_ids:
            raise LibraryRequestError("paper_ids must contain at least one paper ID")
        if len(paper_ids) > 100:
            raise LibraryRequestError("paper_ids must contain at most 100 paper IDs")
        collection = self.catalog.add_collection_papers(collection_id, list(paper_ids))
        return self.get_collection(collection.id)

    def get_collection(self, collection_id: str) -> CollectionDetail:
        collection = self.catalog.get_collection(collection_id)
        tags, collections = self._references()
        return CollectionDetail(
            **self._collection_item(collection, len(collection.papers)).model_dump(),
            papers=[
                CollectionMember(
                    paper=self._list_item(
                        self.catalog.get_paper(member.paper_id), tags, collections
                    ),
                    position=member.position,
                    note=member.note,
                    added_at=member.added_at,
                )
                for member in collection.papers
            ],
        )

    def get_collection_context(
        self,
        collection_id: str,
        *,
        include_papers: bool = True,
        include_synthesis: bool = True,
    ) -> CollectionContextResult:
        detail = self.get_collection(collection_id)
        result = CollectionContextResult(
            collection=CollectionItem.model_validate(detail.model_dump(exclude={"papers"})),
            papers=detail.papers if include_papers else None,
        )
        if include_synthesis:
            synthesis = self.syntheses.latest(collection_id)
            if synthesis is None:
                result.unavailable.append(
                    UnavailableContent(kind="synthesis", reason="artifact_not_generated")
                )
            else:
                result.synthesis = CollectionSynthesisView(
                    collection_id=collection_id,
                    run_id=synthesis.run_id,
                    synthesis=synthesis.synthesis.model_dump(mode="json"),
                    artifacts=[self._collection_artifact(item) for item in synthesis.artifacts],
                    source_status=SourceStatusView(
                        stale=synthesis.source_status.stale,
                        reasons=list(synthesis.source_status.reasons),
                    ),
                    resource_uri=f"passagen://collections/{collection_id}/synthesis",
                )
        return result

    def list_collection_reports(self, collection_id: str) -> CollectionReportListResult:
        self.catalog.get_collection(collection_id)
        return CollectionReportListResult(
            items=[self._report_item(view) for view in self.reports.list_reports(collection_id)]
        )

    def get_collection_report(self, collection_id: str, report_id: str) -> CollectionReportView:
        self.catalog.get_collection(collection_id)
        view = self.reports.get_report(report_id)
        if view.record.collection_id != collection_id:
            raise CatalogNotFoundError(f"Collection report not found: {report_id}")
        return CollectionReportView(
            **self._report_item(view).model_dump(),
            report=view.report.model_dump(mode="json") if view.report is not None else None,
            artifacts=[self._collection_artifact(item) for item in view.artifacts],
        )

    def search_sections(
        self,
        query: str,
        *,
        paper_ids: Sequence[str] = (),
        collection_id: str | None = None,
        max_results: int = 10,
        max_chars: int = 30_000,
    ) -> SectionSearchResult:
        if not query.strip():
            raise LibraryRequestError("query must not be blank")
        if not 1 <= max_results <= 20:
            raise LibraryRequestError("max_results must be between 1 and 20")
        if not 1_000 <= max_chars <= 100_000:
            raise LibraryRequestError("max_chars must be between 1000 and 100000")
        papers = self._search_scope(paper_ids, collection_id)
        ranked: list[tuple[int, PaperView, RetrievedSection]] = []
        skipped: list[str] = []
        for order, paper in enumerate(papers):
            loaded = self._parsed(paper.id)
            if loaded is None:
                skipped.append(paper.id)
                continue
            parsed, sha256 = loaded
            retrieval = InMemorySectionRetrieval(paper.id, parsed, artifact_sha256=sha256)
            for section in retrieval.search(
                [query], max_sections=max_results, max_tokens=max(1, max_chars // 4)
            ):
                ranked.append((order, paper, section))
        ranked.sort(key=lambda item: (-item[2].score, item[0], item[2].ordinal))
        hits: list[SectionHit] = []
        used_chars = 0
        truncated = len(ranked) > max_results
        for _order, paper, section in ranked:
            if len(hits) >= max_results:
                break
            remaining = max_chars - used_chars
            if remaining <= 0:
                truncated = True
                break
            text = section.text[:remaining]
            if len(text) < len(section.text):
                truncated = True
            hits.append(
                SectionHit(
                    paper_id=paper.id,
                    paper_title=paper.title,
                    section_ordinal=section.ordinal,
                    section_title=section.title,
                    pages=list(section.pages),
                    text=text,
                    score=section.score,
                    artifact_sha256=section.artifact_sha256,
                    resource_uri=f"passagen://papers/{paper.id}/sections/{section.ordinal}",
                )
            )
            used_chars += len(text)
        return SectionSearchResult(
            items=hits,
            searched_paper_count=len(papers),
            skipped_paper_ids=skipped,
            truncated=truncated,
        )

    def get_section(self, paper_id: str, ordinal: int) -> dict[str, object]:
        self.catalog.get_paper(paper_id)
        loaded = self._parsed(paper_id)
        if loaded is None:
            raise CatalogNotFoundError(f"Extracted text not found for paper: {paper_id}")
        parsed, sha256 = loaded
        if ordinal < 0 or ordinal >= len(parsed.sections):
            raise CatalogNotFoundError(f"Section not found: {paper_id}/{ordinal}")
        section = parsed.sections[ordinal]
        return {
            "paper_id": paper_id,
            "ordinal": ordinal,
            "title": section.title,
            "pages": list(section.pages),
            "text": section.text,
            "artifact_sha256": sha256,
        }

    def _validate_scope(self, tag_ids: Sequence[str], collection_id: str | None) -> None:
        known_tags = {tag.id for tag in self.catalog.list_tags()}
        unknown = sorted(set(tag_ids) - known_tags)
        if unknown:
            raise LibraryRequestError(f"Unknown tag IDs: {', '.join(unknown)}")
        if collection_id is not None:
            self.catalog.get_collection(collection_id)

    def _search_scope(self, paper_ids: Sequence[str], collection_id: str | None) -> list[PaperView]:
        if paper_ids and collection_id is not None:
            raise LibraryRequestError("paper_ids and collection_id are mutually exclusive")
        unique_ids = list(dict.fromkeys(paper_ids))
        if len(unique_ids) > MAX_EXPLICIT_SEARCH_PAPERS:
            raise LibraryRequestError(
                f"paper_ids may contain at most {MAX_EXPLICIT_SEARCH_PAPERS} papers"
            )
        if unique_ids:
            return [self.catalog.get_paper(paper_id) for paper_id in unique_ids]
        filters = PaperFilters(collection_id=collection_id)
        if collection_id is not None:
            self.catalog.get_collection(collection_id)
        page = self.catalog.list_papers(
            filters,
            sort=(PaperSort.COLLECTION_ORDER if collection_id else PaperSort.UPDATED_AT),
            direction=(SortDirection.ASC if collection_id else SortDirection.DESC),
            limit=MAX_SEARCH_PAPERS,
        )
        if page.total > MAX_SEARCH_PAPERS:
            raise LibraryRequestError(
                f"Search scope has {page.total} papers; narrow it to at most {MAX_SEARCH_PAPERS}"
            )
        return list(page.items)

    def _references(self) -> tuple[dict[str, TagRef], dict[str, CollectionRef]]:
        tags = {tag.id: TagRef(id=tag.id, name=tag.name) for tag in self.catalog.list_tags()}
        collections = {
            item.id: CollectionRef(id=item.id, name=item.name)
            for item in self.catalog.list_collections()
        }
        return tags, collections

    def _metadata(
        self,
        paper: PaperView,
        tags: dict[str, TagRef],
        collections: dict[str, CollectionRef],
    ) -> PaperMetadata:
        return PaperMetadata(
            id=paper.id,
            title=paper.title,
            authors=list(paper.authors),
            year=paper.year,
            venue=paper.venue,
            doi=paper.doi,
            arxiv_id=paper.arxiv_id,
            source_url=paper.source_url,
            original_filename=paper.original_filename,
            status=paper.status.value,
            imported_at=paper.imported_at,
            updated_at=paper.updated_at,
            metadata_sources=paper.metadata_sources,
            tags=[tags[tag_id] for tag_id in paper.tag_ids],
            collections=[collections[item_id] for item_id in paper.collection_ids],
            artifacts=self._availability(paper),
            resource_uri=f"passagen://papers/{paper.id}",
        )

    def _list_item(
        self,
        paper: PaperView,
        tags: dict[str, TagRef],
        collections: dict[str, CollectionRef],
    ) -> PaperListItem:
        metadata = self._metadata(paper, tags, collections)
        return PaperListItem(
            id=metadata.id,
            title=metadata.title,
            authors=metadata.authors,
            year=metadata.year,
            venue=metadata.venue,
            status=metadata.status,
            tags=metadata.tags,
            collections=metadata.collections,
            artifacts=metadata.artifacts,
            updated_at=metadata.updated_at,
            resource_uri=metadata.resource_uri,
        )

    def _availability(self, paper: PaperView) -> ArtifactAvailability:
        kinds = set(paper.artifact_kinds)
        return ArtifactAvailability(
            abstract=paper.abstract is not None,
            summary="summary_json" in kinds,
            outline="outline_md" in kinds,
            extracted_text="extracted_json" in kinds,
            note=bool(self.catalog.get_paper_note(paper.id)),
        )

    def _collection_item(self, collection: Any, paper_count: int) -> CollectionItem:
        return CollectionItem(
            id=collection.id,
            name=collection.name,
            description=collection.description,
            created_at=collection.created_at,
            updated_at=collection.updated_at,
            paper_count=paper_count,
            resource_uri=f"passagen://collections/{collection.id}",
        )

    def _report_item(self, view: CoreReportView) -> CollectionReportItem:
        record = view.record
        return CollectionReportItem(
            id=record.id,
            collection_id=record.collection_id,
            kind=record.kind.value,
            status=record.status,
            title=record.title,
            user_prompt=record.user_prompt,
            run_id=record.run_id,
            created_at=record.created_at,
            completed_at=record.completed_at,
            source_status=SourceStatusView(
                stale=view.source_status.stale,
                reasons=list(view.source_status.reasons),
            ),
            resource_uri=(f"passagen://collections/{record.collection_id}/reports/{record.id}"),
        )

    def _collection_artifact(self, artifact: CollectionArtifact) -> CollectionArtifactRef:
        return CollectionArtifactRef(
            id=artifact.id,
            kind=artifact.kind,
            version=artifact.version,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            created_at=artifact.created_at,
        )

    def _abstract(self, paper: PaperView, *, prefer_cleaned: bool) -> AbstractContent | None:
        if paper.abstract is None:
            return None
        if prefer_cleaned:
            cleaned = load_cleaned_abstract(self.database_path, self.data_dir, paper.id)
            if cleaned is not None:
                return AbstractContent(
                    text=cleaned.cleaned_abstract, variant="cleaned", raw_available=True
                )
        return AbstractContent(text=paper.abstract, variant="raw", raw_available=True)

    def _summary(self, paper_id: str) -> dict[str, Any]:
        path = self.catalog.resolve_artifact(paper_id, "summary_json")
        try:
            return validate_summary_json(path.read_bytes())
        except OSError as exc:
            raise InvalidArtifactError("Summary artifact could not be read") from exc

    def _text_artifact(self, paper_id: str, kind: str) -> str:
        path = self.catalog.resolve_artifact(paper_id, kind)
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise InvalidArtifactError(f"Artifact is not readable UTF-8 text: {kind}") from exc

    def _parsed(self, paper_id: str) -> tuple[ParsedPaper, str] | None:
        artifact = get_artifact(self.database_path, paper_id, "extracted_json")
        if artifact is None:
            return None
        path = self.catalog.resolve_artifact(paper_id, "extracted_json")
        try:
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if artifact.sha256 is not None and artifact.sha256 != digest:
                raise InvalidArtifactError("Extracted text hash does not match its catalog record")
            return ParsedPaper.model_validate_json(content), artifact.sha256 or digest
        except (OSError, ValidationError) as exc:
            raise InvalidArtifactError("Extracted text artifact is invalid") from exc


def _criteria_digest(criteria: Mapping[str, object]) -> str:
    encoded = json.dumps(criteria, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()[:16]


def _encode_cursor(offset: int, criteria: Mapping[str, object]) -> str:
    payload = json.dumps(
        {"v": 1, "offset": offset, "criteria": _criteria_digest(criteria)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str | None, criteria: Mapping[str, object]) -> int:
    if cursor is None:
        return 0
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("criteria") != _criteria_digest(criteria)
            or not isinstance(payload.get("offset"), int)
            or payload["offset"] < 0
        ):
            raise ValueError
        return int(payload["offset"])
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LibraryRequestError("Invalid cursor for the requested paper filters") from exc
