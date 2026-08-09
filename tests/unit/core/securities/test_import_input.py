from __future__ import annotations

import pytest

from stock_toolbox.core.securities.import_input import (
    ImportInputError,
    parse_import_file,
    select_import_column,
)


@pytest.mark.parametrize(
    ("content", "column", "symbols"),
    [
        (
            b"\xef\xbb\xbfName,Symbol,Price\nApple,AAPL,210\nNVIDIA,NVDA,180\n",
            "Symbol",
            ("AAPL.US", "NVDA.US"),
        ),
        (
            "名称,证券代码,价格\n超威半导体,AMD,100\n艾瑞恩,IREN,20\n".encode(
                "gb18030"
            ),
            "证券代码",
            ("AMD.US", "IREN.US"),
        ),
        (
            b"Name\tTicker\tQuantity\nMicrosoft\tMSFT\t1\nCrowdStrike\tCRWD\t2\n",
            "Ticker",
            ("MSFT.US", "CRWD.US"),
        ),
        (
            b"Name;Code\nApple;NASDAQ:AAPL\nNVIDIA;$NVDA\n",
            "Code",
            ("AAPL.US", "NVDA.US"),
        ),
    ],
)
def test_detects_symbol_column(
    content: bytes,
    column: str,
    symbols: tuple[str, ...],
) -> None:
    preview = parse_import_file(content)

    assert preview.selected_column == column
    assert preview.symbols == symbols
    assert not preview.requires_column_choice


def test_ambiguous_columns_require_user_choice() -> None:
    preview = parse_import_file(
        "Symbol,Underlying,名称\n"
        "AAPL,QQQ,Apple\n"
        "NVDA,SPY,NVIDIA\n".encode()
    )

    assert preview.requires_column_choice
    assert [item.name for item in preview.candidates] == [
        "Symbol",
        "Underlying",
    ]

    selected = select_import_column(preview, 1)
    assert selected.selected_column == "Underlying"
    assert selected.symbols == ("QQQ.US", "SPY.US")


def test_headerless_single_column_is_importable() -> None:
    preview = parse_import_file(b"AAPL\nNVDA\nAAPL\nbad value\n")

    assert preview.symbols == ("AAPL.US", "NVDA.US")
    assert preview.duplicate_count == 1
    assert preview.invalid_count == 1
    assert preview.row_count == 4


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"x" * (10 * 1024 * 1024 + 1), "file_too_large"),
        (b"\xff\xfe\x00\xff", "unsupported_encoding"),
    ],
)
def test_rejects_unsafe_file_shape(content: bytes, code: str) -> None:
    with pytest.raises(ImportInputError, match=code):
        parse_import_file(content)
