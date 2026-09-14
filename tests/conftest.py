from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from passagen.catalog import CatalogService
from passagen.parsing import ParsedPaper, ParsedSection
from passagen.research import CollectionReport, CollectionSynthesis
from passagen.storage.database import connect_database, initialize_database

from passagen_mcp.library import LibraryReader


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data"
    path.mkdir()
    database_path = path / "passagen.db"
    initialize_database(database_path)
    with connect_database(database_path) as connection:
        for paper_id, title, year, status, abstract in (
            ("paper-a", "Alpha Latency System", 2024, "outlined", "Alpha abstract."),
            ("paper-b", "Beta Storage", 2022, "summarized", "Beta abstract."),
            ("paper-c", "Gamma Network", 2023, "discovered", None),
        ):
            connection.execute(
                """
                INSERT INTO papers
                    (id, title, abstract, authors_json, year, venue, original_filename,
                     pdf_sha256, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    title,
                    abstract,
                    json.dumps(["Ada Author"]),
                    year,
                    "SOSP" if paper_id != "paper-c" else "OSDI",
                    f"{paper_id}.pdf",
                    paper_id.ljust(64, "0"),
                    status,
                ),
            )

    _artifact(
        path,
        "paper-a",
        "summary_json",
        "papers/paper-a/summary.json",
        b'{"schema_version":"2","identity":{"title":"Alpha Latency System"},'
        b'"problem":{"problem_statement":"Tail latency is high."},'
        b'"contributions":[{"statement":"A faster scheduler."}]}',
        version="2",
    )
    _artifact(
        path,
        "paper-a",
        "outline_md",
        "papers/paper-a/outline.md",
        b"# Alpha outline\n\n- Tail latency\n",
        version="2",
    )
    parsed = ParsedPaper(
        sections=(
            ParsedSection(title="Introduction", text="Scheduling latency matters.", pages=(1,)),
            ParsedSection(
                title="Evaluation",
                text="Tail latency dropped to 12 ms under the storage workload.",
                pages=(7, 8),
            ),
        ),
        parser="test",
    )
    _artifact(
        path,
        "paper-a",
        "extracted_json",
        "papers/paper-a/extracted.json",
        parsed.model_dump_json().encode(),
        version="1",
    )

    catalog = CatalogService(database_path, path)
    systems = catalog.create_tag("Systems")
    priority = catalog.create_tag("Priority")
    catalog.set_paper_tags("paper-a", [systems.id, priority.id])
    catalog.set_paper_tags("paper-b", [systems.id])
    reading = catalog.create_collection("Reading Queue", "Papers to review")
    catalog.add_collection_papers(reading.id, ["paper-b", "paper-a"])
    _seed_collection_research(path, reading.id)
    return path


@pytest.fixture
def library(data_dir: Path) -> LibraryReader:
    return LibraryReader(data_dir / "passagen.db", data_dir)


def _artifact(
    data_dir: Path,
    paper_id: str,
    kind: str,
    relative_path: str,
    content: bytes,
    *,
    version: str,
) -> None:
    path = data_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    with connect_database(data_dir / "passagen.db") as connection:
        connection.execute(
            """
            INSERT INTO artifacts (id, paper_id, kind, path, version, sha256, size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{paper_id}-{kind}",
                paper_id,
                kind,
                relative_path,
                version,
                hashlib.sha256(content).hexdigest(),
                len(content),
            ),
        )


def _seed_collection_research(data_dir: Path, collection_id: str) -> None:
    summary_sha = hashlib.sha256(
        (data_dir / "papers/paper-a/summary.json").read_bytes()
    ).hexdigest()
    citation = {
        "citation_id": "c-1",
        "paper_id": "paper-a",
        "artifact_kind": "summary_json",
        "artifact_id": "paper-a-summary_json",
        "artifact_sha256": summary_sha,
        "summary_path": "problem.problem_statement",
    }
    synthesis = CollectionSynthesis.model_validate(
        {
            "executive_overview": "The collection studies system latency.",
            "claims": [{"text": "Latency is a shared concern.", "citation_ids": ["c-1"]}],
            "citations": [citation],
            "coverage": {
                "included_paper_ids": ["paper-a"],
                "missing_summary_paper_ids": ["paper-b"],
                "partial": True,
            },
        }
    )
    report = CollectionReport.model_validate(
        {
            "kind": "review",
            "title": "Latency review",
            "coverage": synthesis.coverage.model_dump(),
            "sections": [
                {
                    "heading": "Overview",
                    "body_markdown": "The collection studies latency [c-1].",
                }
            ],
            "claims": synthesis.claims,
            "citations": [citation],
        }
    )
    synthesis_content = synthesis.model_dump_json().encode()
    report_content = report.model_dump_json().encode()
    synthesis_path = data_dir / "collections/synthesis.json"
    report_path = data_dir / "collections/report.json"
    synthesis_path.parent.mkdir(parents=True, exist_ok=True)
    synthesis_path.write_bytes(synthesis_content)
    report_path.write_bytes(report_content)
    fingerprint = "f" * 64
    with connect_database(data_dir / "passagen.db") as connection:
        connection.execute(
            """
            INSERT INTO generation_runs (id, kind, collection_id, status)
            VALUES ('synthesis-run', 'collection_synthesis', ?, 'completed'),
                   ('report-run', 'report', ?, 'completed')
            """,
            (collection_id, collection_id),
        )
        connection.execute(
            """
            INSERT INTO collection_artifacts
                (id, collection_id, generation_run_id, kind, path, version, sha256,
                 size_bytes, source_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "synthesis-artifact",
                collection_id,
                "synthesis-run",
                "synthesis_json",
                "collections/synthesis.json",
                "2",
                hashlib.sha256(synthesis_content).hexdigest(),
                len(synthesis_content),
                fingerprint,
            ),
        )
        connection.execute(
            """
            INSERT INTO collection_artifacts
                (id, collection_id, generation_run_id, kind, path, version, sha256,
                 size_bytes, source_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "report-artifact",
                collection_id,
                "report-run",
                "report_json",
                "collections/report.json",
                "1",
                hashlib.sha256(report_content).hexdigest(),
                len(report_content),
                fingerprint,
            ),
        )
        connection.execute(
            """
            INSERT INTO collection_reports
                (id, collection_id, kind, status, title, source_snapshot_json,
                 source_fingerprint, run_id, report_artifact_id, completed_at)
            VALUES ('report-1', ?, 'review', 'completed', 'Latency review', '{}', ?,
                    'report-run', 'report-artifact', CURRENT_TIMESTAMP)
            """,
            (collection_id, fingerprint),
        )
