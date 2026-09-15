from __future__ import annotations

import pytest
from passagen.catalog import CatalogNotFoundError, PaperSort, SortDirection, TagMatch

from passagen_mcp.library import LibraryReader, LibraryRequestError
from passagen_mcp.schemas import ContextPart, SummarySection


def test_list_papers_filters_expands_references_and_paginates(library: LibraryReader) -> None:
    systems = next(tag for tag in library.list_tags().items if tag.name == "Systems")

    first = library.list_papers(
        title_query="a",
        tag_ids=[systems.id],
        tag_match=TagMatch.ALL,
        sort=PaperSort.YEAR,
        direction=SortDirection.DESC,
        page_size=1,
    )
    second = library.list_papers(
        title_query="a",
        tag_ids=[systems.id],
        tag_match=TagMatch.ALL,
        sort=PaperSort.YEAR,
        direction=SortDirection.DESC,
        page_size=1,
        cursor=first.next_cursor,
    )

    assert first.total == 2
    assert first.items[0].id == "paper-a"
    assert {tag.name for tag in first.items[0].tags} == {"Systems", "Priority"}
    assert first.items[0].collections[0].name == "Reading Queue"
    assert first.items[0].artifacts.summary is True
    assert second.items[0].id == "paper-b"
    assert second.next_cursor is None


def test_cursor_is_bound_to_filters(library: LibraryReader) -> None:
    first = library.list_papers(page_size=1)

    with pytest.raises(LibraryRequestError, match="Invalid cursor"):
        library.list_papers(title_query="Alpha", page_size=1, cursor=first.next_cursor)


def test_unknown_tag_and_collection_are_errors(library: LibraryReader) -> None:
    with pytest.raises(LibraryRequestError, match="Unknown tag IDs"):
        library.list_papers(tag_ids=["missing"])
    with pytest.raises(Exception, match="Collection not found"):
        library.list_papers(collection_id="missing")


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

    assert [member.paper.id for member in updated.papers] == ["paper-c", "paper-a"]
    assert [member.paper.id for member in retried.papers] == ["paper-c", "paper-a"]


def test_add_papers_to_collection_validates_bounded_batch(library: LibraryReader) -> None:
    collection = library.create_collection("Validation")

    with pytest.raises(LibraryRequestError, match="at least one"):
        library.add_papers_to_collection(collection.id, [])
    with pytest.raises(LibraryRequestError, match="at most 100"):
        library.add_papers_to_collection(collection.id, [f"paper-{index}" for index in range(101)])
    with pytest.raises(CatalogNotFoundError, match="One or more papers"):
        library.add_papers_to_collection(collection.id, ["paper-a", "missing"])

    assert library.get_collection(collection.id).papers == []


def test_collection_context_reads_safe_persisted_synthesis(library: LibraryReader) -> None:
    collection = library.list_collections().items[0]
    context = library.get_collection_context(collection.id)

    assert context.papers is not None
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
