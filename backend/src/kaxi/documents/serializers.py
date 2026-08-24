from rest_framework import serializers

from kaxi.documents.models import (
    DisposalBatch,
    DisposalItem,
    FileAuditLog,
    FileBusinessLink,
    FileCategory,
    FileObject,
    FilePermission,
    FileVersion,
    RetentionPolicy,
    ShareLink,
)


class CategorySerializer(serializers.ModelSerializer[FileCategory]):
    class Meta:
        model = FileCategory
        fields = "__all__"

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs.get("company", getattr(self.instance, "company", None))
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        if parent is not None and parent.company_id != company.pk:
            raise serializers.ValidationError("上级分类必须属于同一公司。")
        return attrs


class RetentionSerializer(serializers.ModelSerializer[RetentionPolicy]):
    class Meta:
        model = RetentionPolicy
        fields = "__all__"


class VersionSerializer(serializers.ModelSerializer[FileVersion]):
    class Meta:
        model = FileVersion
        exclude = ["storage_key"]


class FileSerializer(serializers.ModelSerializer[FileObject]):
    versions = VersionSerializer(many=True, read_only=True)

    class Meta:
        model = FileObject
        fields = "__all__"
        read_only_fields = ["current_version", "status", "row_version"]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs.get("company", getattr(self.instance, "company", None))
        category = attrs.get("category", getattr(self.instance, "category", None))
        retention = attrs.get("retention_policy", getattr(self.instance, "retention_policy", None))
        if category is not None and category.company_id != company.pk:
            raise serializers.ValidationError("文件分类必须属于同一公司。")
        if retention is not None and retention.company_id != company.pk:
            raise serializers.ValidationError("保留策略必须属于同一公司。")
        return attrs


class LinkSerializer(serializers.ModelSerializer[FileBusinessLink]):
    class Meta:
        model = FileBusinessLink
        fields = "__all__"


class PermissionSerializer(serializers.ModelSerializer[FilePermission]):
    class Meta:
        model = FilePermission
        fields = "__all__"


class AuditSerializer(serializers.ModelSerializer[FileAuditLog]):
    class Meta:
        model = FileAuditLog
        fields = "__all__"


class ShareSerializer(serializers.ModelSerializer[ShareLink]):
    class Meta:
        model = ShareLink
        exclude = ["token_hash", "password_hash"]
        read_only_fields = [
            "file_object",
            "expires_at",
            "max_downloads",
            "download_count",
            "watermark",
            "revoked_at",
            "created_by",
            "row_version",
        ]


class UploadVersionSerializer(serializers.Serializer[dict[str, object]]):
    original_filename = serializers.CharField(max_length=500)
    storage_key = serializers.CharField(max_length=1000)
    mime_type = serializers.CharField(max_length=200)
    size_bytes = serializers.IntegerField(min_value=1)
    sha256 = serializers.RegexField(r"^[0-9A-Fa-f]{64}$")
    change_reason = serializers.CharField(required=False, allow_blank=True, default="")


class PrepareUploadSerializer(serializers.Serializer[dict[str, object]]):
    original_filename = serializers.CharField(max_length=500)
    mime_type = serializers.CharField(max_length=200)
    sha256 = serializers.RegexField(r"^[0-9A-Fa-f]{64}$")


class CreateShareSerializer(serializers.Serializer[dict[str, object]]):
    expires_at = serializers.DateTimeField()
    max_downloads = serializers.IntegerField(min_value=1)
    password = serializers.CharField(required=False, allow_blank=True, write_only=True)
    watermark = serializers.CharField(required=False, allow_blank=True)


class DisposalItemSerializer(serializers.ModelSerializer[DisposalItem]):
    class Meta:
        model = DisposalItem
        fields = ["file_object", "reason"]


class DisposalSerializer(serializers.ModelSerializer[DisposalBatch]):
    items = DisposalItemSerializer(many=True)

    class Meta:
        model = DisposalBatch
        fields = "__all__"
        read_only_fields = [
            "status",
            "requested_by",
            "approved_by",
            "approved_at",
            "executed_at",
            "row_version",
        ]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs.get("company", getattr(self.instance, "company", None))
        if any(item["file_object"].company_id != company.pk for item in attrs.get("items", [])):
            raise serializers.ValidationError("销毁批次只能包含同一公司的文件。")
        return attrs

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        items = validated_data.pop("items")
        batch = DisposalBatch.objects.create(**validated_data)
        for item in items:
            DisposalItem.objects.create(batch=batch, **item)
        return batch
