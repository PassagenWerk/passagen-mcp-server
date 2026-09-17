from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from passagen.assistant.retrieval import InMemorySectionRetrieval, RetrievedSection
from passagen.assistant.schemas import SourceSnapshot
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
from passagen.citations import CitationService
from passagen.config import AssistantSettings, LlmSettings
from passagen.domain import PaperStatus
from passagen.parsing import ParsedPaper
from passagen.research import (
    CollectionReportService,
    CollectionSynthesisService,
    render_report_markdown,
)
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
    CollectionDocumentInclude,
    CollectionDocumentItem,
    CollectionDocumentListResult,
    CollectionDocumentPaper,
    CollectionDocumentPaperChanges,
    CollectionDocumentView,
    CollectionItem,
    CollectionListResult,
    CollectionMember,
    CollectionPaperMutationItem,
    CollectionPaperMutationResult,
    CollectionRef,
    CollectionReportItem,
    CollectionReportListResult,
    CollectionReportView,
    CollectionSynthesisView,
    ContextPart,
    PaperBatchResult,
    PaperCitationResult,
    PaperContextResult,
    PaperField,
    PaperListItem,
    PaperListResult,
    PaperMetadata,
    PaperResolutionItem,
    PaperResolutionResult,
    PaperTagMutationItem,
    PaperTagMutationResult,
    SectionHit,
    SectionSearchResult,
    SourceStatusView,
    SummarySection,
    TagField,
    TagItem,
    TagListResult,
    TagRef,
    UnavailableContent,
)

MAX_SEARCH_PAPERS = 100
MAX_EXPLICIT_SEARCH_PAPERS = 50
DEFAULT_PAPER_FIELDS = (PaperField.ID, PaperField.TITLE, PaperField.YEAR, PaperField.TAGS)
RESOLUTION_PAPER_FIELDS = (
    PaperField.ID,
    PaperField.TITLE,
    PaperField.YEAR,
    PaperField.DOI,
    PaperField.ARXIV_ID,
)
DEFAULT_TAG_FIELDS = (TagField.ID, TagField.NAME, TagField.PAPER_COUNT)


class LibraryRequestError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "validation_error",
        details: dict[str, object] | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details
        self.hint = hint

    def __str__(self) -> str:
        parts = [f"{self.code}: {super().__str__()}"]
        if self.details:
            rendered = ", ".join(f"{key}={value!r}" for key, value in self.details.items())
            parts.append(f"details: {rendered}")
        if self.hint:
            parts.append(f"hint: {self.hint}")
        return "; ".join(parts)


class LibraryReader:
    """Agent-oriented projection over a Passagen library."""

    def __init__(
        self,
        database_path: Path,
        data_dir: Path,
        llm_settings: LlmSettings | None = None,
        assistant_settings: AssistantSettings | None = None,
        citation_timeout_seconds: float = 10.0,
    ) -> None:
        self.database_path = database_path.expanduser().resolve()
        self.data_dir = data_dir.expanduser().resolve()
        self.catalog = CatalogService(self.database_path, self.data_dir)
        self.citations = CitationService(
            self.database_path, timeout_seconds=citation_timeout_seconds
        )
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
        fields: Sequence[PaperField] = DEFAULT_PAPER_FIELDS,
        offset: int = 0,
        limit: int = 100,
    ) -> PaperListResult:
        self._validate_page(offset, limit)
        selected = self._paper_fields(fields)
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
            limit=limit,
            offset=offset,
        )
        return self._paper_page(
            page.items,
            total=page.total,
            offset=offset,
            limit=limit,
            fields=selected,
        )

    def get_papers(
        self,
        paper_ids: Sequence[str],
        *,
        fields: Sequence[PaperField] = DEFAULT_PAPER_FIELDS,
    ) -> PaperBatchResult:
        ids = self._bounded_unique_ids(paper_ids, name="paper_ids")
        selected = self._paper_fields(fields)
        papers = self.catalog.get_papers(ids)
        found = {paper.id for paper in papers}
        return PaperBatchResult(
            items=self._project_papers(papers, selected),
            not_found=[paper_id for paper_id in ids if paper_id not in found],
        )

    def resolve_papers(
        self,
        *,
        ids: Sequence[str] = (),
        titles: Sequence[str] = (),
        dois: Sequence[str] = (),
        arxiv_ids: Sequence[str] = (),
        fields: Sequence[PaperField] = RESOLUTION_PAPER_FIELDS,
    ) -> PaperResolutionResult:
        inputs = [*ids, *titles, *dois, *arxiv_ids]
        if not inputs:
            raise LibraryRequestError(
                "at least one identifier is required", code="invalid_argument"
            )
        if len(inputs) > 100:
            raise LibraryRequestError("at most 100 identifiers may be resolved")
        selected = self._paper_fields(fields)
        papers = self._all_papers()
        indices = {
            "id": self._index_papers(papers, lambda paper: paper.id),
            "title": self._index_papers(papers, lambda paper: _normalize_title(paper.title)),
            "doi": self._index_papers(papers, lambda paper: _normalize_doi(paper.doi)),
            "arxiv_id": self._index_papers(
                papers, lambda paper: _normalize_arxiv_id(paper.arxiv_id)
            ),
        }
        requests = (
            [("id", value, value) for value in ids]
            + [("title", value, _normalize_title(value)) for value in titles]
            + [("doi", value, _normalize_doi(value)) for value in dois]
            + [("arxiv_id", value, _normalize_arxiv_id(value)) for value in arxiv_ids]
        )
        results = []
        for kind, original, normalized in requests:
            matches = indices[kind].get(normalized, []) if normalized else []
            results.append(
                PaperResolutionItem(
                    input=original,
                    kind=kind,
                    status=(
                        "matched" if len(matches) == 1 else "ambiguous" if matches else "not_found"
                    ),
                    matches=self._project_papers(matches, selected),
                )
            )
        return PaperResolutionResult(results=results)

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

    def get_paper_citation(self, paper_id: str, *, refresh: bool = False) -> PaperCitationResult:
        citation = self.citations.get_bibtex(paper_id, refresh=refresh)
        return PaperCitationResult(
            paper_id=citation.paper_id,
            format=citation.format,
            content=citation.content,
            source=citation.source.value,
            authoritative=citation.authoritative,
            warnings=list(citation.warnings),
            cached=citation.cached,
            updated_at=citation.updated_at,
            remote_checked_at=citation.remote_checked_at,
        )

    def list_tags(
        self,
        *,
        fields: Sequence[TagField] = DEFAULT_TAG_FIELDS,
        offset: int = 0,
        limit: int = 100,
    ) -> TagListResult:
        self._validate_page(offset, limit)
        selected = set(fields) | {TagField.ID, TagField.NAME}
        tags = self.catalog.list_tag_usage()
        page = tags[offset : offset + limit]
        items = []
        for tag in page:
            values = {
                TagField.ID: tag.id,
                TagField.NAME: tag.name,
                TagField.COLOR: tag.color,
                TagField.CREATED_AT: tag.created_at,
                TagField.PAPER_COUNT: tag.paper_count,
            }
            items.append({field.value: values[field] for field in TagField if field in selected})
        return TagListResult(items=items, **_page_values(offset, limit, len(tags), len(items)))

    def list_collections(self, *, offset: int = 0, limit: int = 100) -> CollectionListResult:
        self._validate_page(offset, limit)
        collections = self.catalog.list_collections()
        items = []
        for item in collections[offset : offset + limit]:
            collection = self.catalog.get_collection(item.id)
            items.append(self._collection_item(collection, len(collection.papers)))
        return CollectionListResult(
            items=items, **_page_values(offset, limit, len(collections), len(items))
        )

    def create_tag(self, name: str, color: str | None = None) -> TagItem:
        return self._tag_item(self.catalog.create_tag(name, color), paper_count=0)

    def update_tag(
        self,
        tag_id: str,
        *,
        name: str | None = None,
        color: str | None = None,
        clear_color: bool = False,
    ) -> TagItem:
        if name is None and color is None and not clear_color:
            raise LibraryRequestError("at least one tag field is required", code="invalid_argument")
        if color is not None and clear_color:
            raise LibraryRequestError(
                "color and clear_color cannot be used together", code="invalid_argument"
            )
        current = self.catalog.get_tag(tag_id)
        updated = self.catalog.update_tag(
            tag_id,
            name=name,
            color=None if clear_color else color if color is not None else current.color,
        )
        usage = next(tag for tag in self.catalog.list_tag_usage() if tag.id == tag_id)
        return self._tag_item(updated, paper_count=usage.paper_count)

    def create_collection(self, name: str, description: str | None = None) -> CollectionDetail:
        collection = self.catalog.create_collection(name, description)
        return self.get_collection(collection.id)

    def update_collection(
        self,
        collection_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        clear_description: bool = False,
    ) -> CollectionItem:
        if name is None and description is None and not clear_description:
            raise LibraryRequestError(
                "at least one collection field is required", code="invalid_argument"
            )
        if description is not None and clear_description:
            raise LibraryRequestError(
                "description and clear_description cannot be used together",
                code="invalid_argument",
            )
        current = self.catalog.get_collection(collection_id)
        updated = self.catalog.update_collection(
            collection_id,
            name=name,
            description=(
                None
                if clear_description
                else description
                if description is not None
                else current.description
            ),
        )
        return self._collection_item(updated, len(updated.papers))

    def add_papers_to_collection(
        self,
        collection_id: str,
        paper_ids: Sequence[str],
        *,
        dry_run: bool = False,
        atomic: bool = False,
    ) -> CollectionPaperMutationResult:
        ids = self._bounded_unique_ids(paper_ids, name="paper_ids")
        collection = self.catalog.get_collection(collection_id)
        found = {paper.id for paper in self.catalog.get_papers(ids)}
        existing = {member.paper_id for member in collection.papers}
        missing = set(ids) - found
        to_add = [paper_id for paper_id in ids if paper_id in found and paper_id not in existing]
        blocked = atomic and bool(missing)
        results = []
        for paper_id in ids:
            if paper_id in missing:
                status, reason = "not_found", "paper_not_found"
            elif paper_id in existing:
                status, reason = "already_present", None
            elif blocked:
                status, reason = "skipped", "atomic_batch_not_applied"
            else:
                status, reason = ("would_add" if dry_run else "added"), None
            results.append(
                CollectionPaperMutationItem(paper_id=paper_id, status=status, reason=reason)
            )
        applied = [] if blocked else to_add
        if applied and not dry_run:
            collection = self.catalog.add_collection_papers(collection_id, applied)
        affected = len(applied)
        total = len(collection.papers) + (affected if dry_run else 0)
        return CollectionPaperMutationResult(
            dry_run=dry_run,
            atomic=atomic,
            affected=affected,
            skipped=len(ids) - affected,
            collection_total=total,
            results=results,
        )

    def update_paper_tags(
        self,
        paper_ids: Sequence[str],
        *,
        tags_add: Sequence[str] = (),
        tags_remove: Sequence[str] = (),
        dry_run: bool = False,
    ) -> PaperTagMutationResult:
        ids = self._bounded_unique_ids(paper_ids, name="paper_ids")
        add = list(dict.fromkeys(tags_add))
        remove = list(dict.fromkeys(tags_remove))
        if not add and not remove:
            raise LibraryRequestError(
                "tags_add or tags_remove is required", code="invalid_argument"
            )
        overlap = sorted(set(add) & set(remove))
        if overlap:
            raise LibraryRequestError(
                "tags_add and tags_remove overlap",
                code="invalid_argument",
                details={"tag_ids": overlap},
            )
        known_tags = {tag.id for tag in self.catalog.list_tags()}
        unknown_tags = [tag_id for tag_id in [*add, *remove] if tag_id not in known_tags]
        if unknown_tags:
            raise LibraryRequestError(
                "unknown tag IDs",
                code="not_found",
                details={"tag_ids": unknown_tags},
            )
        papers = {paper.id: paper for paper in self.catalog.get_papers(ids)}
        results = []
        affected = 0
        for paper_id in ids:
            paper = papers.get(paper_id)
            if paper is None:
                results.append(
                    PaperTagMutationItem(
                        paper_id=paper_id,
                        status="not_found",
                        tags_added=[],
                        tags_removed=[],
                        reason="paper_not_found",
                    )
                )
                continue
            current = set(paper.tag_ids)
            added = [tag_id for tag_id in add if tag_id not in current]
            removed = [tag_id for tag_id in remove if tag_id in current]
            if not added and not removed:
                status = "unchanged"
            else:
                status = "would_update" if dry_run else "updated"
                affected += 1
                if not dry_run:
                    target = [tag_id for tag_id in paper.tag_ids if tag_id not in remove]
                    target.extend(tag_id for tag_id in add if tag_id not in current)
                    self.catalog.set_paper_tags(paper_id, target)
            results.append(
                PaperTagMutationItem(
                    paper_id=paper_id,
                    status=status,
                    tags_added=added,
                    tags_removed=removed,
                )
            )
        return PaperTagMutationResult(
            dry_run=dry_run,
            affected=affected,
            skipped=len(ids) - affected,
            results=results,
        )

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
        include_papers: bool = False,
        include_synthesis: bool = True,
        paper_fields: Sequence[PaperField] = DEFAULT_PAPER_FIELDS,
        paper_offset: int = 0,
        paper_limit: int = 100,
    ) -> CollectionContextResult:
        self._validate_page(paper_offset, paper_limit)
        collection = self.catalog.get_collection(collection_id)
        result = CollectionContextResult(
            collection=self._collection_item(collection, len(collection.papers)),
        )
        if include_papers:
            selected_members = collection.papers[paper_offset : paper_offset + paper_limit]
            papers = self.catalog.get_papers([member.paper_id for member in selected_members])
            projected = self._project_papers(papers, self._paper_fields(paper_fields))
            result.papers = PaperListResult(
                items=[
                    {
                        "paper": paper,
                        "position": member.position,
                        "note": member.note,
                        "added_at": member.added_at,
                    }
                    for member, paper in zip(selected_members, projected, strict=True)
                ],
                **_page_values(
                    paper_offset, paper_limit, len(collection.papers), len(selected_members)
                ),
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

    def list_collection_documents(
        self,
        collection_id: str,
        *,
        include: Sequence[CollectionDocumentInclude] = (),
        offset: int = 0,
        limit: int = 100,
    ) -> CollectionDocumentListResult:
        self._validate_page(offset, limit)
        manual = [
            self._collection_document(item)
            for item in self.catalog.list_collection_documents(collection_id)
        ]
        generated = [
            self._report_document(view) for view in self.reports.list_reports(collection_id)
        ]
        documents = sorted(
            [*manual, *generated], key=lambda item: (item.updated_at, item.id), reverse=True
        )
        selected = set(include)
        items = []
        for document in documents[offset : offset + limit]:
            excluded = set()
            if CollectionDocumentInclude.PAPERS not in selected:
                excluded.add("papers")
            if CollectionDocumentInclude.PAPER_CHANGES not in selected:
                excluded.add("paper_changes")
            items.append(document.model_dump(mode="json", exclude=excluded))
        return CollectionDocumentListResult(
            items=items,
            **_page_values(offset, limit, len(documents), len(items)),
        )

    def get_collection_document(
        self, collection_id: str, document_id: str
    ) -> CollectionDocumentView:
        manual = next(
            (
                item
                for item in self.catalog.list_collection_documents(collection_id)
                if item.id == document_id
            ),
            None,
        )
        if manual is not None:
            return CollectionDocumentView(
                **self._collection_document(manual).model_dump(),
                markdown=manual.content_markdown,
            )
        report = self.reports.get_report(document_id)
        if report.record.collection_id != collection_id:
            raise CatalogNotFoundError(f"Collection document not found: {document_id}")
        return CollectionDocumentView(
            **self._report_document(report).model_dump(),
            markdown=(
                report.record.edited_markdown
                or (render_report_markdown(report.report) if report.report is not None else None)
            ),
        )

    def create_collection_document(
        self,
        collection_id: str,
        *,
        title: str,
        markdown: str,
        external_id: str | None = None,
    ) -> CollectionDocumentItem:
        document = self.catalog.create_collection_document(
            collection_id,
            title=title,
            content_markdown=markdown,
            source="mcp",
            external_id=external_id,
        )
        return self._collection_document(document)

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

    def _collection_document(self, document: Any) -> CollectionDocumentItem:
        papers = [CollectionDocumentPaper(id=item.id, title=item.title) for item in document.papers]
        return CollectionDocumentItem(
            id=document.id,
            collection_id=document.collection_id,
            title=document.title,
            document_type="manual",
            kind="markdown",
            status="ready",
            editable=True,
            source=document.source,
            external_id=document.external_id,
            revision=document.revision,
            papers=papers,
            paper_changes=self._paper_changes(document.collection_id, papers),
            created_at=document.created_at,
            updated_at=document.updated_at,
            resource_uri=(
                f"passagen://collections/{document.collection_id}/documents/{document.id}"
            ),
        )

    def _report_document(self, view: CoreReportView) -> CollectionDocumentItem:
        try:
            snapshot = SourceSnapshot.model_validate_json(view.record.source_snapshot_json)
        except ValidationError:
            snapshot = None
        papers = [
            CollectionDocumentPaper(id=paper.paper_id, title=paper.title)
            for paper in (
                snapshot.collection.papers
                if snapshot is not None and snapshot.collection is not None
                else []
            )
        ]
        return CollectionDocumentItem(
            id=view.record.id,
            collection_id=view.record.collection_id,
            title=view.record.title,
            document_type="generated",
            kind=view.record.kind.value,
            status=view.record.status,
            editable=view.record.status == "completed",
            source="generated",
            external_id=None,
            revision=view.record.revision,
            papers=papers,
            paper_changes=self._paper_changes(view.record.collection_id, papers),
            created_at=view.record.created_at,
            updated_at=view.record.updated_at or view.record.completed_at or view.record.created_at,
            resource_uri=(
                f"passagen://collections/{view.record.collection_id}/documents/{view.record.id}"
            ),
        )

    def _paper_changes(
        self, collection_id: str, saved: list[CollectionDocumentPaper]
    ) -> CollectionDocumentPaperChanges:
        collection = self.catalog.get_collection(collection_id)
        current = [
            CollectionDocumentPaper(
                id=member.paper_id,
                title=self.catalog.get_paper(member.paper_id).title,
            )
            for member in collection.papers
        ]
        saved_ids = [paper.id for paper in saved]
        current_ids = [paper.id for paper in current]
        saved_set = set(saved_ids)
        current_set = set(current_ids)
        return CollectionDocumentPaperChanges(
            added=[paper for paper in current if paper.id not in saved_set],
            removed=[paper for paper in saved if paper.id not in current_set],
            order_changed=(
                [paper_id for paper_id in saved_ids if paper_id in current_set]
                != [paper_id for paper_id in current_ids if paper_id in saved_set]
            ),
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

    def _paper_page(
        self,
        papers: Sequence[PaperView],
        *,
        total: int,
        offset: int,
        limit: int,
        fields: set[PaperField],
    ) -> PaperListResult:
        items = self._project_papers(papers, fields)
        return PaperListResult(
            items=items,
            **_page_values(offset, limit, total, len(items)),
        )

    def _project_papers(
        self, papers: Sequence[PaperView], fields: set[PaperField]
    ) -> list[dict[str, Any]]:
        tags = (
            {tag.id: TagRef(id=tag.id, name=tag.name) for tag in self.catalog.list_tags()}
            if PaperField.TAGS in fields
            else {}
        )
        collections = (
            {
                item.id: CollectionRef(id=item.id, name=item.name)
                for item in self.catalog.list_collections()
            }
            if PaperField.COLLECTIONS in fields
            else {}
        )
        items = []
        for paper in papers:
            values: dict[PaperField, Any] = {
                PaperField.ID: paper.id,
                PaperField.TITLE: paper.title,
                PaperField.AUTHORS: list(paper.authors),
                PaperField.YEAR: paper.year,
                PaperField.VENUE: paper.venue,
                PaperField.DOI: paper.doi,
                PaperField.ARXIV_ID: paper.arxiv_id,
                PaperField.STATUS: paper.status.value,
                PaperField.UPDATED_AT: paper.updated_at,
                PaperField.RESOURCE_URI: f"passagen://papers/{paper.id}",
            }
            if PaperField.TAGS in fields:
                values[PaperField.TAGS] = [tags[tag_id].model_dump() for tag_id in paper.tag_ids]
            if PaperField.COLLECTIONS in fields:
                values[PaperField.COLLECTIONS] = [
                    collections[item_id].model_dump() for item_id in paper.collection_ids
                ]
            if PaperField.ARTIFACTS in fields:
                values[PaperField.ARTIFACTS] = self._availability(paper).model_dump()
            items.append({field.value: values[field] for field in PaperField if field in fields})
        return items

    def _paper_fields(self, fields: Sequence[PaperField]) -> set[PaperField]:
        return set(fields) | {PaperField.ID}

    def _all_papers(self) -> list[PaperView]:
        papers: list[PaperView] = []
        offset = 0
        while True:
            page = self.catalog.list_papers(limit=200, offset=offset)
            papers.extend(page.items)
            offset += len(page.items)
            if offset >= page.total:
                return papers

    @staticmethod
    def _index_papers(
        papers: Sequence[PaperView], key: Callable[[PaperView], str | None]
    ) -> dict[str, list[PaperView]]:
        result: dict[str, list[PaperView]] = {}
        for paper in papers:
            value = key(paper)
            if value:
                result.setdefault(value, []).append(paper)
        return result

    @staticmethod
    def _validate_page(offset: int, limit: int) -> None:
        if offset < 0:
            raise LibraryRequestError("offset must be non-negative", code="invalid_argument")
        if not 1 <= limit <= 200:
            raise LibraryRequestError("limit must be between 1 and 200", code="invalid_argument")

    @staticmethod
    def _bounded_unique_ids(values: Sequence[str], *, name: str) -> list[str]:
        ids = list(values)
        if not ids:
            raise LibraryRequestError(
                f"{name} must contain at least one ID", code="invalid_argument"
            )
        if len(ids) > 100:
            raise LibraryRequestError(f"{name} must contain at most 100 IDs")
        if len(ids) != len(set(ids)):
            raise LibraryRequestError(
                f"{name} must not contain duplicates", code="invalid_argument"
            )
        return ids

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

    @staticmethod
    def _tag_item(tag: Any, *, paper_count: int) -> TagItem:
        return TagItem(
            id=tag.id,
            name=tag.name,
            color=tag.color,
            created_at=tag.created_at,
            paper_count=paper_count,
        )

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


def _page_values(offset: int, limit: int, total: int, returned: int) -> dict[str, Any]:
    next_offset = offset + returned
    has_more = next_offset < total
    return {
        "offset": offset,
        "limit": limit,
        "returned": returned,
        "total": total,
        "next_offset": next_offset if has_more else None,
        "has_more": has_more,
    }


def _normalize_title(value: str | None) -> str | None:
    return " ".join(value.casefold().split()) if value else None


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized or None


def _normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().casefold()
    if normalized.startswith("arxiv:"):
        normalized = normalized[6:].strip()
    return normalized or None
