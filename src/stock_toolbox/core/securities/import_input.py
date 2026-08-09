"""Infer a ticker column without weakening the existing import validation."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, replace

_MAX_BYTES = 10 * 1024 * 1024
_MAX_ROWS = 100_000
_MAX_COLUMNS = 256
_DELIMITERS = (",", "\t", ";", "|")
_EXACT_HEADERS = frozenset(
    {
        "symbol",
        "symbols",
        "ticker",
        "tickers",
        "code",
        "security code",
        "underlying",
        "证券代码",
        "股票代码",
        "证券代号",
        "股票代号",
    }
)
_FUZZY_HEADER_PARTS = (
    "symbol",
    "ticker",
    "code",
    "证券",
    "股票",
    "代码",
    "代号",
    "underlying",
)
_NON_SYMBOL_HEADERS = frozenset(
    {
        "name",
        "company",
        "company name",
        "description",
        "security name",
        "stock name",
        "名称",
        "公司",
        "公司名称",
        "证券名称",
        "股票名称",
    }
)
_EXCHANGE_PREFIX = re.compile(
    r"^(?:NASDAQ|NYSE|AMEX|ARCA|BATS|US)[:：\s]+",
    re.IGNORECASE,
)
_US_EQUITY_SUFFIX = re.compile(r"\s+US(?:\s+EQUITY)?$", re.IGNORECASE)
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


class ImportInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ImportColumnCandidate:
    index: int
    name: str
    samples: tuple[str, ...]
    valid_count: int
    score: int
    symbols: tuple[str, ...]
    invalid_count: int
    duplicate_count: int


@dataclass(frozen=True, slots=True)
class ImportInputPreview:
    candidates: tuple[ImportColumnCandidate, ...]
    selected_index: int | None
    selected_column: str | None
    symbols: tuple[str, ...]
    invalid_count: int
    duplicate_count: int
    row_count: int

    @property
    def requires_column_choice(self) -> bool:
        return bool(self.candidates) and self.selected_index is None


def parse_import_file(content: bytes) -> ImportInputPreview:
    if len(content) > _MAX_BYTES:
        raise ImportInputError("file_too_large")
    text = _decode(content)
    rows = _rows(text)
    if not rows:
        raise ImportInputError("file_empty")
    if len(rows) > _MAX_ROWS + 1:
        raise ImportInputError("too_many_rows")
    width = max(len(row) for row in rows)
    if width > _MAX_COLUMNS:
        raise ImportInputError("too_many_columns")
    has_header = _has_header(rows)
    names = (
        tuple(_header_name(value, index) for index, value in enumerate(rows[0]))
        if has_header
        else tuple(f"第 {index + 1} 列" for index in range(width))
    )
    data_rows = rows[1:] if has_header else rows
    candidates = tuple(
        candidate
        for index in range(width)
        if (
            candidate := _candidate(
                index,
                names[index] if index < len(names) else f"第 {index + 1} 列",
                data_rows,
                has_header=has_header,
            )
        )
        is not None
    )
    if not candidates:
        raise ImportInputError("symbol_column_not_found")
    ranked = sorted(candidates, key=lambda item: (-item.score, item.index))
    selected = (
        ranked[0]
        if ranked[0].score >= 120
        and (
            len(ranked) == 1
            or ranked[0].score - ranked[1].score >= 20
        )
        else None
    )
    preview = ImportInputPreview(
        tuple(sorted(candidates, key=lambda item: item.index)),
        None,
        None,
        (),
        0,
        0,
        len(data_rows),
    )
    return (
        select_import_column(preview, selected.index)
        if selected is not None
        else preview
    )


def select_import_column(
    preview: ImportInputPreview,
    index: int,
) -> ImportInputPreview:
    candidate = next(
        (item for item in preview.candidates if item.index == index),
        None,
    )
    if candidate is None:
        raise ImportInputError("invalid_column")
    return replace(
        preview,
        selected_index=index,
        selected_column=candidate.name,
        symbols=candidate.symbols,
        invalid_count=candidate.invalid_count,
        duplicate_count=candidate.duplicate_count,
    )


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportInputError("unsupported_encoding")


def _rows(text: str) -> list[tuple[str, ...]]:
    delimiter = _delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [
        tuple(cell.strip() for cell in row)
        for row in reader
        if any(cell.strip() for cell in row)
    ]
    return rows


def _delimiter(text: str) -> str:
    sample = text[:32_768]
    try:
        hinted = csv.Sniffer().sniff(sample, delimiters="".join(_DELIMITERS))
        preferred = hinted.delimiter
    except csv.Error:
        preferred = ","
    ranked = sorted(
        _DELIMITERS,
        key=lambda delimiter: (
            _shape_score(sample, delimiter),
            delimiter == preferred,
        ),
        reverse=True,
    )
    return ranked[0]


def _shape_score(text: str, delimiter: str) -> tuple[int, int, int]:
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))[:50]
    except csv.Error:
        return (0, 0, 0)
    widths = [len(row) for row in rows if any(cell.strip() for cell in row)]
    if not widths:
        return (0, 0, 0)
    common = max(set(widths), key=widths.count)
    consistent = sum(width == common for width in widths)
    return (int(common > 1), consistent, common)


def _has_header(rows: list[tuple[str, ...]]) -> bool:
    first = rows[0]
    if any(_header_score(cell) for cell in first):
        return True
    if len(rows) < 2:
        return False
    first_valid = sum(_normalize_symbol(cell) is not None for cell in first)
    second_valid = sum(
        _normalize_symbol(cell) is not None for cell in rows[1]
    )
    return second_valid > first_valid


def _header_name(value: str, index: int) -> str:
    return " ".join(value.split()) or f"第 {index + 1} 列"


def _header_score(value: str) -> int:
    normalized = _normalized_header(value)
    if normalized in _EXACT_HEADERS:
        return 100
    return (
        60
        if any(part in normalized for part in _FUZZY_HEADER_PARTS)
        else 0
    )


def _normalized_header(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").split())


def _candidate(
    index: int,
    name: str,
    rows: list[tuple[str, ...]],
    *,
    has_header: bool,
) -> ImportColumnCandidate | None:
    values = [
        row[index].strip() if index < len(row) else ""
        for row in rows
    ]
    normalized = [_normalize_symbol(value) for value in values]
    valid_count = sum(value is not None for value in normalized)
    ratio = round(valid_count * 100 / len(values)) if values else 0
    header_score = _header_score(name) if has_header else 60
    if (
        has_header
        and header_score == 0
        and _normalized_header(name) in _NON_SYMBOL_HEADERS
    ):
        return None
    if not valid_count or (ratio < 40 and not header_score):
        return None
    symbols = tuple(
        dict.fromkeys(value for value in normalized if value is not None)
    )
    return ImportColumnCandidate(
        index,
        name,
        tuple(value for value in values if value)[:3],
        valid_count,
        header_score + ratio,
        symbols,
        len(values) - valid_count,
        valid_count - len(symbols),
    )


def _normalize_symbol(value: str) -> str | None:
    symbol = " ".join(value.strip().split())
    symbol = symbol.removeprefix("$")
    symbol = _EXCHANGE_PREFIX.sub("", symbol)
    symbol = _US_EQUITY_SUFFIX.sub("", symbol)
    symbol = symbol.upper()
    symbol = symbol.removesuffix(".US")
    if not _SYMBOL.fullmatch(symbol):
        return None
    return f"{symbol}.US"
