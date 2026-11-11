from __future__ import annotations

import pandas as pd

from datake.profiler import profile_dataframe


def test_profile_dataframe_summarizes_quality_and_columns() -> None:
    summary = profile_dataframe(
        pd.DataFrame(
            {
                "customer_id": [1, 2, 2],
                "email": ["a@example.com", None, None],
                "amount": [10, 20, 20],
            }
        )
    )

    assert summary.row_count == 3
    assert summary.column_count == 3
    assert summary.duplicate_rows == 1
    assert summary.quality_score < 100
    email = next(column for column in summary.columns if column.name == "email")
    assert email.missing_count == 2
    assert email.missing_percent == 66.67
    amount = next(column for column in summary.columns if column.name == "amount")
    assert amount.minimum == 10
    assert amount.maximum == 20
    assert amount.top_values[0] == {"value": 20, "count": 2}
