from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.system.import_services import commit_batch, stage_csv, validate_batch
from kaxi.system.models import DataImportBatch, DataImportRow


class ImportRowSerializer(serializers.ModelSerializer[DataImportRow]):
    class Meta:
        model = DataImportRow
        fields = "__all__"


class ImportBatchSerializer(serializers.ModelSerializer[DataImportBatch]):
    rows = ImportRowSerializer(many=True, read_only=True)

    class Meta:
        model = DataImportBatch
        fields = "__all__"
        read_only_fields = [
            "batch_no",
            "source_sha256",
            "status",
            "total_rows",
            "valid_rows",
            "invalid_rows",
            "requested_by",
            "committed_at",
            "row_version",
        ]


class StageImportSerializer(serializers.Serializer[dict[str, object]]):
    company_id = serializers.IntegerField(required=False)
    entity_type = serializers.ChoiceField(choices=DataImportBatch.Entity)
    filename = serializers.CharField(max_length=300)
    csv_content = serializers.CharField(max_length=5 * 1024 * 1024, trim_whitespace=False)


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied("需要有效业务用户。")
    return request.user


class DataImportViewSet(viewsets.ReadOnlyModelViewSet[DataImportBatch]):
    queryset = DataImportBatch.objects.select_related("company", "requested_by").prefetch_related(
        "rows"
    )
    serializer_class = ImportBatchSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "system.data_import.manage",
        "retrieve": "system.data_import.manage",
        "stage": "system.data_import.manage",
        "validate": "system.data_import.manage",
        "commit": "system.data_import.commit",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    @action(detail=False, methods=["post"])
    def stage(self, request: Request) -> Response:
        serializer = StageImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _user(request)
        company_id = user.company_id or serializer.validated_data.get("company_id")
        if not company_id:
            raise serializers.ValidationError("超级管理员必须指定 company_id。")
        batch = stage_csv(
            company_id=company_id,
            entity_type=serializer.validated_data["entity_type"],
            filename=serializer.validated_data["filename"],
            content=serializer.validated_data["csv_content"].encode(),
            actor=user,
        )
        return Response(self.get_serializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def validate(self, request: Request, pk: str | None = None) -> Response:
        batch = validate_batch(batch_id=self.get_object().pk)
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=["post"])
    def commit(self, request: Request, pk: str | None = None) -> Response:
        batch = commit_batch(batch_id=self.get_object().pk, actor=_user(request))
        return Response(self.get_serializer(batch).data)
