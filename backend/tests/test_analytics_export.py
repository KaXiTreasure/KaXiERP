import csv
import io

from openpyxl import load_workbook

from kaxi.analytics.export_services import _render
from kaxi.analytics.services import result_digest


def test_csv_export_is_utf8_and_tabular():
    body, mime_type, extension = _render(
        [{"sku": "KAXI-001", "quantity": 2}, {"sku": "KAXI-002", "quantity": 3}],
        "csv",
    )
    rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
    assert mime_type == "text/csv"
    assert extension == "csv"
    assert rows == [["quantity", "sku"], ["2", "KAXI-001"], ["3", "KAXI-002"]]


def test_xlsx_export_produces_valid_workbook():
    body, mime_type, extension = _render({"gross_margin": "88.20"}, "xlsx")
    workbook = load_workbook(io.BytesIO(body), read_only=True)
    rows = list(workbook.active.values)
    assert extension == "xlsx"
    assert mime_type.endswith("spreadsheetml.sheet")
    assert rows == [("gross_margin",), ("88.20",)]


def test_report_snapshot_digest_is_stable_across_key_order():
    assert result_digest({"b": 2, "a": 1}) == result_digest({"a": 1, "b": 2})
