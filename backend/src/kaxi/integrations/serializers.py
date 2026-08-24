from rest_framework import serializers

from kaxi.integrations.models import (
    Connector,
    ExternalObjectMapping,
    IntegrationAccount,
    IntegrationEvent,
    SyncCursor,
    WebhookEndpoint,
)


class ConnectorSerializer(serializers.ModelSerializer[Connector]):
    class Meta:
        model = Connector
        fields = "__all__"


class AccountSerializer(serializers.ModelSerializer[IntegrationAccount]):
    class Meta:
        model = IntegrationAccount
        fields = "__all__"
        ref_name = "IntegrationAccount"
        extra_kwargs = {"credential_reference": {"write_only": True}}


class MappingSerializer(serializers.ModelSerializer[ExternalObjectMapping]):
    class Meta:
        model = ExternalObjectMapping
        fields = "__all__"


class CursorSerializer(serializers.ModelSerializer[SyncCursor]):
    class Meta:
        model = SyncCursor
        fields = "__all__"


class EventSerializer(serializers.ModelSerializer[IntegrationEvent]):
    class Meta:
        model = IntegrationEvent
        fields = "__all__"
        read_only_fields = [
            "status",
            "attempts",
            "lease_until",
            "worker_id",
            "error_code",
            "error_message",
            "internal_object_type",
            "internal_object_id",
            "row_version",
        ]


class WebhookSerializer(serializers.ModelSerializer[WebhookEndpoint]):
    class Meta:
        model = WebhookEndpoint
        fields = "__all__"
        extra_kwargs = {"secret_reference": {"write_only": True}}


class RetrySerializer(serializers.Serializer[dict[str, object]]):
    reason = serializers.CharField()
