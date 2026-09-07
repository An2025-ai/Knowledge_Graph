"""Pure evidence parsing and candidate extraction primitives."""

from shared.extraction.candidate_extraction import build_candidate_rows, pre_extract
from shared.extraction.evidence_parsing import (
    merge_spans_to_unit_rows,
    parse_to_span_rows,
)

__all__ = [
    "build_candidate_rows",
    "merge_spans_to_unit_rows",
    "parse_to_span_rows",
    "pre_extract",
]
