from rest_framework import serializers

from kaxi.workflow.models import (
    ApprovalDefinition,
    ApprovalInstance,
    ApprovalNode,
    ApprovalRule,
    ApprovalTask,
    Notification,
    NotificationPreference,
)


class NodeSerializer(serializers.ModelSerializer[ApprovalNode]):
    class Meta:
        model = ApprovalNode
        fields = "__all__"
        read_only_fields = ["definition", "row_version"]


class DefinitionSerializer(serializers.ModelSerializer[ApprovalDefinition]):
    nodes = NodeSerializer(many=True)

    class Meta:
        model = ApprovalDefinition
        fields = "__all__"
        ref_name = "WorkflowApprovalDefinition"
        read_only_fields = ["row_version"]

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        nodes = validated_data.pop("nodes")
        definition = ApprovalDefinition.objects.create(**validated_data)
        for node in nodes:
            ApprovalNode.objects.create(definition=definition, **node)
        return definition


class RuleSerializer(serializers.ModelSerializer[ApprovalRule]):
    class Meta:
        model = ApprovalRule
        fields = "__all__"


class TaskSerializer(serializers.ModelSerializer[ApprovalTask]):
    class Meta:
        model = ApprovalTask
        fields = "__all__"


class InstanceSerializer(serializers.ModelSerializer[ApprovalInstance]):
    tasks = TaskSerializer(many=True, read_only=True)

    class Meta:
        model = ApprovalInstance
        fields = "__all__"


class StartApprovalSerializer(serializers.Serializer[dict[str, object]]):
    company_id = serializers.IntegerField()
    definition_id = serializers.IntegerField()
    business_type = serializers.CharField(max_length=80)
    business_id = serializers.CharField(max_length=100)
    snapshot = serializers.JSONField()
    idempotency_key = serializers.CharField(max_length=100)


class DecisionSerializer(serializers.Serializer[dict[str, object]]):
    decision = serializers.ChoiceField(choices=["approved", "rejected"])
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class TransferSerializer(serializers.Serializer[dict[str, object]]):
    target_user_id = serializers.IntegerField()
    comment = serializers.CharField()


class NotificationSerializer(serializers.ModelSerializer[Notification]):
    class Meta:
        model = Notification
        fields = "__all__"


class PreferenceSerializer(serializers.ModelSerializer[NotificationPreference]):
    class Meta:
        model = NotificationPreference
        fields = "__all__"
        read_only_fields = ["user", "row_version"]
