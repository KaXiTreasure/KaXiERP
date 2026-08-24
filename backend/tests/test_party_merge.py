import pytest
from rest_framework.test import APIClient

from kaxi.identity.models import User
from kaxi.master_data.models import (
    Company,
    Currency,
    CustomerProfile,
    Party,
    PartyContact,
    PartyMergeCandidate,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_party_duplicate_detection_and_atomic_merge():
    currency = Currency.objects.create(code="CNY", name="人民币")
    company = Company.objects.create(
        company_code="MDM",
        legal_name="主数据测试",
        display_name="主数据测试",
        base_currency=currency,
    )
    requester = User.objects.create_superuser(
        username="merge-requester", password="StrongPass123!", display_name="查重申请人"
    )
    approver = User.objects.create_superuser(
        username="merge-approver", password="StrongPass123!", display_name="合并审批人"
    )
    canonical = Party.objects.create(
        company=company,
        party_no="C-001",
        party_type=Party.PartyType.ORGANIZATION,
        legal_name="卡西贸易有限公司",
        display_name="卡西贸易",
        status=Party.Status.ACTIVE,
    )
    duplicate = Party.objects.create(
        company=company,
        party_no="C-002",
        party_type=Party.PartyType.ORGANIZATION,
        legal_name="卡西 贸易（有限公司）",
        display_name="卡西贸易旧档",
        status=Party.Status.ACTIVE,
    )
    CustomerProfile.objects.create(party=duplicate)
    contact = PartyContact.objects.create(party=duplicate, name="张三", mobile="13800000000")

    client = APIClient()
    client.force_authenticate(requester)
    detected = client.post(
        "/api/v1/master-data/merge-candidates/detect/",
        {"company_id": company.pk},
        format="json",
    )
    assert detected.status_code == 201, detected.data
    assert detected.data["created_candidates"] == 1
    candidate = PartyMergeCandidate.objects.get()
    assert (
        client.post(f"/api/v1/master-data/merge-candidates/{candidate.pk}/approve/").status_code
        == 400
    )

    client.force_authenticate(approver)
    approved = client.post(f"/api/v1/master-data/merge-candidates/{candidate.pk}/approve/")
    assert approved.status_code == 200, approved.data
    duplicate.refresh_from_db()
    contact.refresh_from_db()
    assert duplicate.status == Party.Status.INACTIVE
    assert duplicate.merged_into_id == canonical.pk
    assert duplicate.merged_by_id == approver.pk
    assert contact.party_id == canonical.pk
    assert CustomerProfile.objects.filter(party=canonical).exists()
    assert approved.data["reference_counts"]["master_data.partycontact.party"] == 1


def test_merge_refuses_conflicting_one_to_one_profiles():
    currency = Currency.objects.create(code="USD", name="美元")
    company = Company.objects.create(
        company_code="MD2", legal_name="冲突测试", display_name="冲突测试", base_currency=currency
    )
    requester = User.objects.create_superuser(
        username="merge-owner", password="StrongPass123!", display_name="申请人"
    )
    approver = User.objects.create_superuser(
        username="merge-reviewer", password="StrongPass123!", display_name="审批人"
    )
    parties = [
        Party.objects.create(
            company=company,
            party_no=f"P-{index}",
            party_type=Party.PartyType.ORGANIZATION,
            legal_name=f"企业 {index}",
            display_name=f"企业 {index}",
        )
        for index in (1, 2)
    ]
    for party in parties:
        CustomerProfile.objects.create(party=party)
    candidate = PartyMergeCandidate.objects.create(
        company=company,
        canonical_party=parties[0],
        duplicate_party=parties[1],
        match_score=0.9,
        match_reasons=["manual"],
        requested_by=requester,
    )
    client = APIClient()
    client.force_authenticate(approver)
    response = client.post(f"/api/v1/master-data/merge-candidates/{candidate.pk}/approve/")
    assert response.status_code == 400, response.data
    candidate.refresh_from_db()
    assert candidate.status == PartyMergeCandidate.Status.PENDING
    assert Party.objects.get(pk=parties[1].pk).merged_into_id is None
