from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError

from kaxi.documents import storage
from kaxi.identity.management.commands.seed_permissions import permission_codes


def test_permission_catalog_covers_runtime_and_conditional_permissions():
    codes = permission_codes()
    assert len(codes) >= 80
    assert "analytics.dashboard.read" in codes
    assert "document.file.upload" in codes
    assert "document.sensitive.read" in codes
    assert "finance.cost.manage" in codes
    assert "finance.ledger.read" in codes
    assert "integration.monitor.read" in codes
    assert "workflow.task.process" in codes


def test_presigned_upload_binds_company_file_and_integrity_metadata(monkeypatch, settings):
    client = Mock()
    client.generate_presigned_url.return_value = "https://storage.example/upload"
    monkeypatch.setattr(storage, "_client", lambda: client)
    settings.KAXI_S3_BUCKET = "kaxi-documents"
    settings.KAXI_S3_PRESIGN_TTL = 900

    result = storage.create_upload(
        company_id=7,
        file_id=11,
        filename="proof.pdf",
        mime_type="application/pdf",
        sha256="a" * 64,
    )

    assert result["storage_key"].startswith("companies/7/files/11/")
    assert result["headers"]["x-amz-meta-sha256"] == "a" * 64
    params = client.generate_presigned_url.call_args.kwargs["Params"]
    assert params["Metadata"] == {"sha256": "a" * 64}


def test_upload_completion_rejects_cross_file_storage_key(monkeypatch):
    client = Mock()
    monkeypatch.setattr(storage, "_client", lambda: client)

    with pytest.raises(ValidationError, match="不属于当前文件"):
        storage.verify_upload(
            company_id=7,
            file_id=11,
            storage_key="companies/7/files/12/object.pdf",
            size_bytes=20,
            sha256="a" * 64,
        )

    client.head_object.assert_not_called()


def test_upload_completion_verifies_remote_size_and_hash(monkeypatch, settings):
    client = Mock()
    client.head_object.return_value = {
        "ContentLength": 20,
        "Metadata": {"sha256": "b" * 64},
    }
    monkeypatch.setattr(storage, "_client", lambda: client)
    settings.KAXI_S3_BUCKET = "kaxi-documents"

    storage.verify_upload(
        company_id=7,
        file_id=11,
        storage_key="companies/7/files/11/object.pdf",
        size_bytes=20,
        sha256="b" * 64,
    )
