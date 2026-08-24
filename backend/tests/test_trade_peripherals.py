from datetime import date

import pytest
from rest_framework.test import APIClient

from kaxi.identity.models import User
from kaxi.master_data.models import Company, Currency
from kaxi.trade.models import Shipment, TradeDocument

pytestmark = pytest.mark.django_db(transaction=True)


def test_trade_document_snapshot_requires_separate_issuer():
    currency = Currency.objects.create(code="CNY", name="人民币")
    company = Company.objects.create(
        company_code="TRADE", legal_name="贸易测试", display_name="贸易测试", base_currency=currency
    )
    creator = User.objects.create_superuser(
        username="document-creator", password="StrongPass123!", display_name="制单人"
    )
    issuer = User.objects.create_superuser(
        username="document-issuer", password="StrongPass123!", display_name="签发人"
    )
    shipment = Shipment.objects.create(
        company=company,
        shipment_no="SHP-001",
        trade_type="export",
        transport_mode="sea",
        destination="Hamburg",
    )
    client = APIClient()
    client.force_authenticate(creator)
    response = client.post(
        "/api/v1/trade/documents/",
        {
            "company": company.pk,
            "shipment": shipment.pk,
            "document_type": "commercial_invoice",
            "document_no": "CI-001",
            "language": "en-US",
            "template_version": "v1",
            "snapshot": {
                "issue_date": date.today().isoformat(),
                "shipment_no": shipment.shipment_no,
                "total": "100.00",
            },
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    document_id = response.data["id"]
    generated = client.post(f"/api/v1/trade/documents/{document_id}/generate/")
    assert generated.status_code == 200, generated.data
    assert len(generated.data["content_sha256"]) == 64
    assert client.post(f"/api/v1/trade/documents/{document_id}/issue/").status_code == 403

    client.force_authenticate(issuer)
    issued = client.post(f"/api/v1/trade/documents/{document_id}/issue/")
    assert issued.status_code == 200, issued.data
    assert issued.data["status"] == TradeDocument.Status.ISSUED
    assert issued.data["issued_by"] == issuer.pk
    assert (
        client.patch(
            f"/api/v1/trade/documents/{document_id}/",
            {"snapshot": {"tampered": True}},
            format="json",
        ).status_code
        == 403
    )


def test_trade_document_rejects_cross_company_shipment():
    currency = Currency.objects.create(code="USD", name="美元")
    first = Company.objects.create(
        company_code="T1", legal_name="公司一", display_name="公司一", base_currency=currency
    )
    second = Company.objects.create(
        company_code="T2", legal_name="公司二", display_name="公司二", base_currency=currency
    )
    actor = User.objects.create_superuser(
        username="trade-root", password="StrongPass123!", display_name="贸易管理员"
    )
    shipment = Shipment.objects.create(
        company=second,
        shipment_no="SHP-OTHER",
        trade_type="export",
        transport_mode="air",
    )
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post(
        "/api/v1/trade/documents/",
        {
            "company": first.pk,
            "shipment": shipment.pk,
            "document_type": "packing_list",
            "document_no": "PL-CROSS",
            "template_version": "v1",
            "snapshot": {},
        },
        format="json",
    )
    assert response.status_code == 400, response.data
