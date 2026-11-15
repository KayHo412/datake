from __future__ import annotations

import pandas as pd

from datake.privacy import detect_sensitive_columns, hash_sensitive_columns


def test_detect_sensitive_columns_uses_column_names_only() -> None:
    assert detect_sensitive_columns(["email", "phone_number", "order_total"]) == {
        "email": "email",
        "phone_number": "phone",
    }


def test_hash_sensitive_columns_returns_copy() -> None:
    source = pd.DataFrame({"email": ["ada@example.com"], "total": [3]})

    hashed = hash_sensitive_columns(source, ["email"])

    assert hashed.loc[0, "email"] != source.loc[0, "email"]
    assert hashed.loc[0, "total"] == 3
