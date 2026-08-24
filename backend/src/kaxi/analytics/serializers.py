from rest_framework import serializers

from kaxi.analytics.models import ExportJob, ReportDefinition, ReportSnapshot


class DefinitionSerializer(serializers.ModelSerializer[ReportDefinition]):
    class Meta:
        model = ReportDefinition
        fields = "__all__"
        ref_name = "AnalyticsReportDefinition"


class AnalyticsResponseSerializer(serializers.Serializer[dict[str, object]]):
    pass


class SnapshotSerializer(serializers.ModelSerializer[ReportSnapshot]):
    class Meta:
        model = ReportSnapshot
        fields = "__all__"
        read_only_fields = ["result", "result_sha256", "generated_by", "row_version"]


class ExportJobSerializer(serializers.ModelSerializer[ExportJob]):
    class Meta:
        model = ExportJob
        fields = "__all__"
        read_only_fields = ["requested_by", "status", "file_object", "error_message", "row_version"]
        extra_kwargs = {"expires_at": {"required": False}}


class SnapshotRequestSerializer(serializers.Serializer[dict[str, object]]):
    company_id = serializers.IntegerField(required=False)
    filters = serializers.JSONField(required=False, default=dict)
