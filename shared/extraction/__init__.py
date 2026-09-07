"""Pure evidence parsing and candidate extraction primitives."""

from shared.extraction.candidate_extraction import build_candidate_rows, pre_extract
from shared.extraction.entity_rules import extract_entity_candidates, extract_relation_candidates
from shared.extraction.normalization import fuse_candidates, normalize_candidate, normalize_name
from shared.extraction.evidence_parsing import (
    merge_spans_to_unit_rows,
    parse_to_span_rows,
)

__all__ = [
    "build_candidate_rows",
    "extract_entity_candidates",
    "extract_relation_candidates",
    "fuse_candidates",
    "merge_spans_to_unit_rows",
    "normalize_candidate",
    "normalize_name",
    "parse_to_span_rows",
    "pre_extract",
]
