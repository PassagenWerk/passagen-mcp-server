from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContextPart(StrEnum):
    ABSTRACT = "abstract"
    SUMMARY = "summary"
    OUTLINE = "outline"
    NOTE = "note"


class SummarySection(StrEnum):
    CLASSIFICATION = "classification"
    PROBLEM = "problem"
    CONTRIBUTIONS = "contributions"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    EVALUATION = "evaluation"
    DISCUSSION = "discussion"
    RELATED_WORK = "related_work"


class PaperField(StrEnum):
    ID = "id"
    TITLE = "title"
    AUTHORS = "authors"
    YEAR = "year"
    VENUE = "venue"
    DOI = "doi"
    ARXIV_ID = "arxiv_id"
    STATUS = "status"
    TAGS = "tags"
    COLLECTIONS = "collections"
    ARTIFACTS = "artifacts"
    UPDATED_AT = "updated_at"
    RESOURCE_URI = "resource_uri"


class TagField(StrEnum):
    ID = "id"
    NAME = "name"
    COLOR = "color"
    CREATED_AT = "created_at"
    PAPER_COUNT = "paper_count"


class CollectionDocumentInclude(StrEnum):
    PAPERS = "papers"
    PAPER_CHANGES = "paper_changes"


class TagRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str


class CollectionRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str


class ArtifactAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    abstract: bool
    summary: bool
    outline: bool
    extracted_text: bool
    note: bool


class PaperMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str | None
    authors: list[str]
    year: int | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    source_url: str | None
    original_filename: str
    status: str
    imported_at: str
    updated_at: str
    metadata_sources: dict[str, str]
    tags: list[TagRef]
    collections: list[CollectionRef]
    artifacts: ArtifactAvailability
    resource_uri: str


class PaperListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str | None
    authors: list[str]
    year: int | None
    venue: str | None
    status: str
    tags: list[TagRef]
    collections: list[CollectionRef]
    artifacts: ArtifactAvailability
    updated_at: str
    resource_uri: str


class PaperListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int
    limit: int
    returned: int
    total: int
    next_offset: int | None
    has_more: bool
    items: list[dict[str, Any]]


class PaperBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[dict[str, Any]]
    not_found: list[str]


class PaperResolutionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str
    kind: str
    status: str
    matches: list[dict[str, Any]]


class PaperResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[PaperResolutionItem]


class AbstractContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    variant: str
    raw_available: bool


class UnavailableContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    reason: str


class PaperContextResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper: PaperMetadata
    abstract: AbstractContent | None = None
    summary: dict[str, Any] | None = None
    outline: str | None = None
    note: str | None = None
    unavailable: list[UnavailableContent] = Field(default_factory=list)


class PaperCitationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_id: str
    format: str
    content: str
    source: str
    authoritative: bool
    warnings: list[str]
    cached: bool
    updated_at: str | None
    remote_checked_at: str | None


class TagItem(TagRef):
    color: str | None
    created_at: str
    paper_count: int


class TagListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int
    limit: int
    returned: int
    total: int
    next_offset: int | None
    has_more: bool
    items: list[dict[str, Any]]


class CollectionItem(CollectionRef):
    description: str | None
    created_at: str
    updated_at: str
    paper_count: int
    resource_uri: str


class CollectionListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int
    limit: int
    returned: int
    total: int
    next_offset: int | None
    has_more: bool
    items: list[CollectionItem]


class CollectionMember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper: PaperListItem
    position: int
    note: str | None
    added_at: str


class CollectionDetail(CollectionItem):
    papers: list[CollectionMember]


class CollectionDocumentPaper(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str | None


class CollectionDocumentPaperChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")
    added: list[CollectionDocumentPaper]
    removed: list[CollectionDocumentPaper]
    order_changed: bool


class CollectionDocumentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    collection_id: str
    title: str
    document_type: str
    kind: str
    status: str
    editable: bool
    source: str
    external_id: str | None
    revision: int | None
    papers: list[CollectionDocumentPaper]
    paper_changes: CollectionDocumentPaperChanges
    created_at: str
    updated_at: str
    resource_uri: str


class CollectionDocumentListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int
    limit: int
    returned: int
    total: int
    next_offset: int | None
    has_more: bool
    items: list[dict[str, Any]]


class CollectionDocumentView(CollectionDocumentItem):
    markdown: str | None


class SourceStatusView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stale: bool
    reasons: list[str]


class CollectionArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    version: str
    sha256: str
    size_bytes: int
    created_at: str


class CollectionSynthesisView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection_id: str
    run_id: str | None
    synthesis: dict[str, Any]
    artifacts: list[CollectionArtifactRef]
    source_status: SourceStatusView
    resource_uri: str


class CollectionContextResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection: CollectionItem
    papers: PaperListResult | None = None
    synthesis: CollectionSynthesisView | None = None
    unavailable: list[UnavailableContent] = Field(default_factory=list)


class CollectionPaperMutationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_id: str
    status: str
    reason: str | None = None


class CollectionPaperMutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool
    atomic: bool
    affected: int
    skipped: int
    collection_total: int
    results: list[CollectionPaperMutationItem]


class PaperTagMutationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_id: str
    status: str
    tags_added: list[str]
    tags_removed: list[str]
    reason: str | None = None


class PaperTagMutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool
    affected: int
    skipped: int
    results: list[PaperTagMutationItem]


class CollectionReportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    collection_id: str
    kind: str
    status: str
    title: str
    user_prompt: str | None
    run_id: str | None
    created_at: str
    completed_at: str | None
    source_status: SourceStatusView
    resource_uri: str


class CollectionReportListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[CollectionReportItem]


class CollectionReportView(CollectionReportItem):
    report: dict[str, Any] | None
    artifacts: list[CollectionArtifactRef]


class SectionHit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_id: str
    paper_title: str | None
    section_ordinal: int
    section_title: str | None
    pages: list[int]
    text: str
    score: float
    artifact_sha256: str
    resource_uri: str


class SectionSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SectionHit]
    searched_paper_count: int
    skipped_paper_ids: list[str]
    truncated: bool
