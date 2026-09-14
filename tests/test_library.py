from __future__ import annotations

import pytest
from passagen.catalog import PaperSort, SortDirection, TagMatch

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
