from __future__ import annotations

import pytest
from passagen.catalog import CatalogNotFoundError, PaperSort, SortDirection, TagMatch

from passagen_mcp.library import LibraryReader, LibraryRequestError
from passagen_mcp.schemas import (
    CollectionDocumentInclude,
    ContextPart,
    PaperField,
    SummarySection,
)


def test_list_papers_filters_expands_references_and_paginates(library: LibraryReader) -> None:
    systems = next(tag for tag in library.list_tags().items if tag["name"] == "Systems")
    fields = [
        PaperField.ID,
        PaperField.TITLE,
        PaperField.YEAR,
        PaperField.TAGS,
        PaperField.COLLECTIONS,
        PaperField.ARTIFACTS,
    ]

    first = library.list_papers(
        title_query="a",
        tag_ids=[str(systems["id"])],
        tag_match=TagMatch.ALL,
        sort=PaperSort.YEAR,
        direction=SortDirection.DESC,
        fields=fields,
        limit=1,
    )
    second = library.list_papers(
        title_query="a",
        tag_ids=[str(systems["id"])],
        tag_match=TagMatch.ALL,
        sort=PaperSort.YEAR,
        direction=SortDirection.DESC,
        fields=fields,
        offset=first.next_offset or 0,
        limit=2,
    )

    assert first.total == 2
    assert first.items[0]["id"] == "paper-a"
    assert {tag["name"] for tag in first.items[0]["tags"]} == {"Systems", "Priority"}
    assert first.items[0]["collections"][0]["name"] == "Reading Queue"
    assert first.items[0]["artifacts"]["summary"] is True
    assert second.items[0]["id"] == "paper-b"
    assert second.next_offset is None


def test_offset_can_be_resumed_with_a_different_limit(library: LibraryReader) -> None:
    first = library.list_papers(limit=1)
    second = library.list_papers(offset=first.next_offset or 0, limit=2)

    assert first.returned == 1
    assert second.returned == 2
    assert {item["id"] for item in [*first.items, *second.items]} == {
        "paper-a",
        "paper-b",
        "paper-c",
    }


def test_unknown_tag_and_collection_are_errors(library: LibraryReader) -> None:
    with pytest.raises(LibraryRequestError, match="Unknown tag IDs"):
        library.list_papers(tag_ids=["missing"])
    with pytest.raises(Exception, match="Collection not found"):
        library.list_papers(collection_id="missing")


def test_projected_batch_read_and_identifier_resolution(library: LibraryReader) -> None:
    batch = library.get_papers(
        ["paper-c", "missing", "paper-a"], fields=[PaperField.ID, PaperField.TITLE]
    )
    resolved = library.resolve_papers(
        ids=["paper-a", "missing"],
        titles=["  alpha LATENCY system  "],
    )

    assert batch.items == [
        {"id": "paper-c", "title": "Gamma Network"},
        {"id": "paper-a", "title": "Alpha Latency System"},
    ]
    assert batch.not_found == ["missing"]
    assert [item.status for item in resolved.results] == ["matched", "not_found", "matched"]
    assert resolved.results[2].matches[0]["id"] == "paper-a"


def test_tag_and_collection_updates_support_dry_run_and_partial_results(
    library: LibraryReader,
) -> None:
    tag = library.create_tag("Programmable Network")
    collection = library.create_collection("Draft", "Old description")

    preview = library.update_paper_tags(["paper-a", "missing"], tags_add=[tag.id], dry_run=True)
    assert tag.id not in library.catalog.get_paper("paper-a").tag_ids
    applied = library.update_paper_tags(["paper-a", "missing"], tags_add=[tag.id])
    renamed = library.update_tag(tag.id, name="Programmable Networks")
    updated_collection = library.update_collection(
        collection.id, name="Curated", clear_description=True
    )

    assert [item.status for item in preview.results] == ["would_update", "not_found"]
    assert [item.status for item in applied.results] == ["updated", "not_found"]
    assert tag.id in library.catalog.get_paper("paper-a").tag_ids
    assert renamed.name == "Programmable Networks"
    assert updated_collection.name == "Curated"
    assert updated_collection.description is None


def test_context_projects_summary_and_reports_missing_content(library: LibraryReader) -> None:
    alpha = library.get_paper_context(
        "paper-a",
        include=[ContextPart.ABSTRACT, ContextPart.SUMMARY, ContextPart.OUTLINE],
        summary_sections=[SummarySection.PROBLEM],
    )
    gamma = library.get_paper_context(
        "paper-c", include=[ContextPart.ABSTRACT, ContextPart.SUMMARY]
    )

    assert alpha.abstract is not None and alpha.abstract.variant == "raw"
    assert alpha.summary is not None
    assert set(alpha.summary) == {"schema_version", "identity", "problem"}
    assert alpha.outline == "# Alpha outline\n\n- Tail latency\n"
    assert {(item.kind, item.reason) for item in gamma.unavailable} == {
        ("abstract", "not_available"),
        ("summary", "artifact_not_generated"),
    }


def test_paper_citation_is_materialized_then_read_from_cache(library: LibraryReader) -> None:
    first = library.get_paper_citation("paper-a")
    second = library.get_paper_citation("paper-a")
    refreshed = library.get_paper_citation("paper-a", refresh=True)

    assert first.paper_id == "paper-a"
    assert first.format == "bibtex"
    assert first.source == "local_metadata"
    assert first.authoritative is False
    assert first.content.startswith("@misc{author2024alphalatencysystem-")
    assert first.cached is False
    assert first.updated_at is not None
    assert second.content == first.content
    assert second.cached is True
    assert refreshed.content == first.content
    assert refreshed.cached is False


def test_search_sections_is_scoped_ranked_and_page_linked(library: LibraryReader) -> None:
    result = library.search_sections("tail latency", paper_ids=["paper-a"])

    assert result.searched_paper_count == 1
    assert result.skipped_paper_ids == []
    assert [item.section_ordinal for item in result.items] == [1, 0]
    assert result.items[0].pages == [7, 8]
    assert result.items[0].artifact_sha256
    assert result.items[0].resource_uri.endswith("/sections/1")


def test_search_skips_papers_without_extracted_text(library: LibraryReader) -> None:
    result = library.search_sections("storage", paper_ids=["paper-a", "paper-b"])

    assert result.skipped_paper_ids == ["paper-b"]


def test_collection_preserves_member_order(library: LibraryReader) -> None:
    collection = library.list_collections().items[0]
    detail = library.get_collection(collection.id)

    assert collection.paper_count == 2
    assert [member.paper.id for member in detail.papers] == ["paper-b", "paper-a"]
    assert [member.position for member in detail.papers] == [0, 1]


def test_create_collection_and_add_existing_papers(library: LibraryReader) -> None:
    created = library.create_collection("Distributed Systems", "Agent reading list")

    assert created.name == "Distributed Systems"
    assert created.description == "Agent reading list"
    assert created.papers == []

    updated = library.add_papers_to_collection(created.id, ["paper-c", "paper-a"])
    retried = library.add_papers_to_collection(created.id, ["paper-a"])

    assert updated.affected == 2
    assert [item.status for item in updated.results] == ["added", "added"]
    assert retried.affected == 0
    assert retried.results[0].status == "already_present"
    assert library.get_collection(created.id).paper_count == 2


def test_collection_markdown_documents_can_be_created_listed_and_read(
    library: LibraryReader,
) -> None:
    collection = library.create_collection("External documents")
    library.add_papers_to_collection(collection.id, ["paper-a"])

    created = library.create_collection_document(
        collection.id,
        title="Service brief",
        markdown="# Brief\n\nImported content.",
        external_id="service-42",
    )
    retried = library.create_collection_document(
        collection.id,
        title="Service brief",
        markdown="# Brief\n\nImported content.",
        external_id="service-42",
    )
    library.catalog.remove_collection_paper(collection.id, "paper-a")
    library.add_papers_to_collection(collection.id, ["paper-b"])
    listed = library.list_collection_documents(
        collection.id,
        include=[CollectionDocumentInclude.PAPERS, CollectionDocumentInclude.PAPER_CHANGES],
    )
    compact = library.list_collection_documents(collection.id)
    detail = library.get_collection_document(collection.id, created.id)

    assert retried.id == created.id
    listed_item = next(item for item in listed.items if item["id"] == created.id)
    assert listed_item["title"] == "Service brief"
    assert {item["document_type"] for item in listed.items} == {"manual"}
    assert "papers" not in compact.items[0]
    assert "paper_changes" not in compact.items[0]
    assert detail.markdown == "# Brief\n\nImported content."
    assert detail.resource_uri.endswith(f"/documents/{created.id}")
    assert [(paper.id, paper.title) for paper in detail.papers] == [
        ("paper-a", "Alpha Latency System")
    ]
    assert [paper.id for paper in detail.paper_changes.added] == ["paper-b"]
    assert [paper.id for paper in detail.paper_changes.removed] == ["paper-a"]


def test_add_papers_to_collection_validates_bounded_batch(library: LibraryReader) -> None:
    collection = library.create_collection("Validation")

    with pytest.raises(LibraryRequestError, match="at least one"):
        library.add_papers_to_collection(collection.id, [])
    with pytest.raises(LibraryRequestError, match="at most 100"):
        library.add_papers_to_collection(collection.id, [f"paper-{index}" for index in range(101)])
    preview = library.add_papers_to_collection(collection.id, ["paper-a", "missing"], dry_run=True)
    atomic = library.add_papers_to_collection(collection.id, ["paper-a", "missing"], atomic=True)

    assert preview.affected == 1
    assert preview.collection_total == 1
    assert library.get_collection(collection.id).papers == []
    assert atomic.affected == 0
    assert [item.status for item in atomic.results] == ["skipped", "not_found"]
    result = library.add_papers_to_collection(collection.id, ["paper-a", "missing"])

    assert result.affected == 1
    assert [item.status for item in result.results] == ["added", "not_found"]
    assert [item.paper.id for item in library.get_collection(collection.id).papers] == ["paper-a"]


def test_collection_context_reads_safe_persisted_synthesis(library: LibraryReader) -> None:
    collection = library.list_collections().items[0]
    context = library.get_collection_context(collection.id, include_papers=True, paper_limit=1)

    assert context.papers is not None
    assert context.papers.returned == 1
    assert context.papers.items[0]["paper"]["id"] == "paper-b"
    assert context.synthesis is not None
    assert context.synthesis.synthesis["executive_overview"] == (
        "The collection studies system latency."
    )
    assert context.synthesis.source_status.stale is True
    assert context.synthesis.source_status.reasons == ["source_manifest_missing"]
    assert context.synthesis.artifacts[0].kind == "synthesis_json"
    assert all("path" not in artifact.model_dump() for artifact in context.synthesis.artifacts)


def test_collection_reports_list_and_read_without_paths(library: LibraryReader) -> None:
    collection = library.list_collections().items[0]
    listed = library.list_collection_reports(collection.id)
    detail = library.get_collection_report(collection.id, "report-1")

    assert [(item.id, item.status, item.kind) for item in listed.items] == [
        ("report-1", "completed", "review")
    ]
    assert listed.items[0].source_status.stale is True
    assert detail.report is not None
    assert detail.report["title"] == "Latency review"
    assert detail.artifacts[0].sha256
    assert all("path" not in artifact.model_dump() for artifact in detail.artifacts)


def test_report_must_belong_to_requested_collection(library: LibraryReader) -> None:
    other = library.catalog.create_collection("Other")

    with pytest.raises(CatalogNotFoundError, match="Collection report not found"):
        library.get_collection_report(other.id, "report-1")
