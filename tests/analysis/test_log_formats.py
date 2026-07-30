"""Parsing, merging, and templating regressions for real-world log formats.

Shapes mirror the incident-log samples the product targets: bracketed TCS STP
logs, pipe-delimited batch/UI logs (date|time split by the delimiter), the
level-first pipe format, Java stack traces, and multi-hundred-line framework
object dumps following a DEBUG header.
"""

from __future__ import annotations

from datetime import UTC, datetime

from logan_analysis.activities.preprocessing import merge_entries, preprocess_entries
from logan_analysis.algorithms.multiline import merge_physical_lines
from logan_analysis.algorithms.parsers import extract_service, parse_timestamp
from logan_analysis.algorithms.redactors import redact_text
from logan_analysis.algorithms.template_extractor import TemplateExtractor
from logan_analysis.models import IngestedFile, RawPhysicalLine

STP_LINE = (
    "[2026-06-22 07:37:41,437] ERROR - [Instance :4]"
    "[TDT_TASK_ID:ee0c8a386776616a2a8880b00f926332][Task Name:EVENT_IMPACT_IB]"
    "[Nap Key:G ;2600721548 ;BP0000003 ;][Task Status:UNDER_PROCESSING]"
    "[Service Name:UPDTANNC][WorkerThread8] [Thread-10] "
    "[com.tcs.ncs.stp.delegates.NtfctnUpdtAnncSTP - callServiceImpl(133)]- "
    "External Loop currentTrigger NOTF"
)
PIPE_LINE = (
    "2026-06-16|19:31:12,703|ERROR||threadpooltaskexecutor-2|"
    "com.tcs.mastercraft.mctype.ServerContext:641| JobName: job56291 StepName: step56291 "
    "Job ExecutionId: 3819569 Step Execution Id: 5312639 Entity: G: |BERSEC1825361185|"
    "INTERNAL_ERROR|System Error Occurred.Please Contact Database Administrator|"
    "com.tcs.bfsarch.springbatch.writers.WriterAdapter.process:334|56291|"
)
LEVEL_FIRST_LINE = (
    "|ERROR|2023-09-18|17:31:26,352|COMP_COMMON_IN|746280|GPC 134873331231267 4233546057|"
    "hkl20142165.hk.comp|ServiceIntegrator||EAI-000511|Message/variable length check failed. "
    "The error is `No match found for reconciliation for[Tag:DEPMUREF "
    "Reference:134873331231267 Purpose:RECONCILE]`|Possible reason for this failure could "
    "be(a) See the Description||tcs.bancs.si.actions.listeners.ActionLogger:34|COMP_COMMON_IN-1"
)
SESSION_LINE = (
    "2026-06-19|20:01:29,117|ERROR||WebContainer : 10|"
    "com.tcs.ncs.tmc.actions.CashTransactionAtAccountLevelAction:272|"
    "1232:44109693:91:RbSIxyeof8iyFmKLMOD8BWG:130.198.38.28:  : "
    "/Bancs/tmc/TMC1200S.cado METHOD=TMC1200Q|inside RR curForm "
    "com.tcs.ncs.tmc.forms.CashTransactionAtAccountLevelForm@e4900dee|"
)


def test_parse_timestamp_supports_pipe_delimited_date_time() -> None:
    parsed, quality = parse_timestamp(PIPE_LINE)
    assert quality == "parsed"
    assert parsed == datetime(2026, 6, 16, 19, 31, 12, 703000, tzinfo=UTC)

    parsed, quality = parse_timestamp(LEVEL_FIRST_LINE)
    assert quality == "parsed"
    assert parsed == datetime(2023, 9, 18, 17, 31, 26, 352000, tzinfo=UTC)

    parsed, quality = parse_timestamp(STP_LINE)
    assert quality == "parsed"
    assert parsed == datetime(2026, 6, 22, 7, 37, 41, 437000, tzinfo=UTC)


def test_extract_service_prefers_named_service_then_component_then_class() -> None:
    assert extract_service(STP_LINE) == "UPDTANNC"
    assert extract_service(LEVEL_FIRST_LINE) == "COMP_COMMON_IN"
    assert extract_service(PIPE_LINE) == "ServerContext"


def test_redaction_keeps_clock_times() -> None:
    redacted = redact_text("[2026-06-19 13:13:58,392] DEBUG - worker heartbeat")
    assert "13:13:58" in redacted
    assert redact_text("connect 2001:db8:85a3::7334 failed") != "connect 2001:db8:85a3::7334 failed"


def test_redaction_keeps_business_references_but_masks_cards() -> None:
    # 15-digit reconciliation references are evidence, not payment cards.
    kept = redact_text("No match found for Reference:134873331231267 Purpose:RECONCILE")
    assert "134873331231267" in kept
    # A Luhn-valid card number is still redacted.
    masked = redact_text("paid with 4111 1111 1111 1111 today")
    assert "4111" not in masked
    assert "<CARD>" in masked


def _raw_lines(lines: list[str]) -> list[RawPhysicalLine]:
    return [
        RawPhysicalLine(
            raw_line_id=f"raw-{index}",
            file_id="file-1",
            file_path="app.log",
            line_number=index + 1,
            raw_text=text,
            sha256="",
            ingestion_order=index,
        )
        for index, text in enumerate(lines)
    ]


def test_object_dump_lines_merge_into_the_headed_entry() -> None:
    dump_entry_head = STP_LINE.replace("ERROR", "DEBUG")
    lines = [
        dump_entry_head,
        "Class MONotfOtgngMsgs : ",
        "Base Class AbstractBaseMO ::",
        "",
        "msgId = DFCD4DA8F8773460 (StringBuffer) ",
        "END OF MONotfOtgngMsgs ",
        "",
        STP_LINE,
    ]
    entries = merge_physical_lines(_raw_lines(lines))
    assert len(entries) == 2
    assert "END OF MONotfOtgngMsgs" in entries[0].raw_message
    assert entries[1].raw_message == STP_LINE


def test_headerless_files_do_not_collapse_into_one_entry() -> None:
    lines = ["first plain line", "second plain line", "third plain line"]
    entries = merge_physical_lines(_raw_lines(lines))
    assert len(entries) == 3


def test_exception_header_and_stack_join_previous_error() -> None:
    lines = [
        PIPE_LINE,
        "java.lang.NullPointerException: null",
        "\tat com.tcs.bancs.ADHOC.BI_REPORT_QUEUE.ADHPS95035GnrtRprt(BI_REPORT_QUEUE.java:17206) ~[ADHOC.jar:?]",
        "\tat java.lang.Thread.run(Thread.java:750) [?:1.8.0_492]",
    ]
    entries = merge_physical_lines(_raw_lines(lines))
    assert len(entries) == 1
    assert "NullPointerException" in entries[0].raw_message
    assert entries[0].line_numbers == [1, 2, 3, 4]


def test_high_cardinality_identifiers_share_one_template() -> None:
    extractor = TemplateExtractor()
    variants = [
        STP_LINE,
        STP_LINE.replace("ee0c8a386776616a2a8880b00f926332", "edff305457707462531002d8936153f4")
        .replace("2600721548", "2600679337")
        .replace("BP0000003", "BP10000066")
        .replace("WorkerThread8", "WorkerThread17")
        .replace("Thread-10", "Thread-19"),
    ]
    session_variants = [
        SESSION_LINE,
        SESSION_LINE.replace("RbSIxyeof8iyFmKLMOD8BWG", "fX_-N1d9SRanU-84f0hdnVv")
        .replace("1232:44109693", "1714:44066686")
        .replace("@e4900dee", "@1eaaab4b"),
    ]
    for pair in (variants, session_variants):
        first, second = (
            extractor.to_template(redact_text(text).strip().lower()) for text in pair
        )
        assert first == second

    template = extractor.to_template(redact_text(LEVEL_FIRST_LINE).strip().lower())
    assert "eai-000511" in template
    assert "134873331231267" not in template


def test_preprocess_end_to_end_on_mixed_formats() -> None:
    lines = [STP_LINE, PIPE_LINE, LEVEL_FIRST_LINE, SESSION_LINE]
    files = [
        IngestedFile(
            file_id="file-1",
            original_filename="mixed.log",
            object_uri="file:///mixed.log",
            size_bytes=1,
            sha256="",
            detected_format="log",
            lines=_raw_lines(lines),
        )
    ]
    normalized = preprocess_entries(
        case_id="case-1",
        analysis_run_id="run-1",
        entries=merge_entries(files),
    )
    assert len(normalized) == 4
    assert all(line.timestamp is not None for line in normalized)
    assert all(line.timestamp_quality == "parsed" for line in normalized)
    assert all(line.service for line in normalized)
    assert all(line.template_text for line in normalized)
    assert {line.level for line in normalized} == {"ERROR"}
