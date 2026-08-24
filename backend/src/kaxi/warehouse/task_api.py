from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.warehouse.models import WarehouseScanEvent, WarehouseTask, WarehouseTaskLine
from kaxi.warehouse.task_services import complete_task, record_scan, release_task


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied("需要有效业务用户。")
    return request.user


class WarehouseTaskLineSerializer(serializers.ModelSerializer[WarehouseTaskLine]):
    class Meta:
        model = WarehouseTaskLine
        fields = "__all__"
        read_only_fields = ["task", "scanned_qty", "completed_qty", "row_version"]


class WarehouseTaskSerializer(serializers.ModelSerializer[WarehouseTask]):
    lines = WarehouseTaskLineSerializer(many=True)

    class Meta:
        model = WarehouseTask
        fields = "__all__"
        read_only_fields = ["status", "released_at", "started_at", "completed_at", "row_version"]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs.get("company", getattr(self.instance, "company", None))
        warehouse = attrs.get("warehouse", getattr(self.instance, "warehouse", None))
        receipt = attrs.get("goods_receipt", getattr(self.instance, "goods_receipt", None))
        shipment = attrs.get("sales_shipment", getattr(self.instance, "sales_shipment", None))
        task_type = attrs.get("task_type", getattr(self.instance, "task_type", None))
        if warehouse.company_id != company.pk:
            raise serializers.ValidationError({"warehouse": "仓库必须属于任务公司。"})
        if task_type == WarehouseTask.TaskType.PUTAWAY:
            if not receipt or shipment or receipt.company_id != company.pk:
                raise serializers.ValidationError("上架任务必须关联同公司收货单且不能关联发货单。")
        elif not shipment or receipt or shipment.company_id != company.pk:
            raise serializers.ValidationError("拣货/打包任务必须关联同公司发货单且不能关联收货单。")
        for index, line in enumerate(attrs.get("lines", []), start=1):
            sku = line["sku"]
            if sku.company_id != company.pk:
                raise serializers.ValidationError({"lines": f"第 {index} 行 SKU 不属于任务公司。"})
            if task_type == WarehouseTask.TaskType.PUTAWAY:
                source = line.get("source_balance")
                target = line.get("target_location")
                if (
                    source is None
                    or target is None
                    or source.company_id != company.pk
                    or source.warehouse_id != warehouse.pk
                    or source.sku_id != sku.pk
                    or target.warehouse_id != warehouse.pk
                ):
                    raise serializers.ValidationError({"lines": f"第 {index} 行上架维度不一致。"})
            else:
                shipment_line = line.get("sales_shipment_line")
                if (
                    shipment_line is None
                    or shipment_line.shipment_id != shipment.pk
                    or shipment_line.order_line.sku_id != sku.pk
                    or shipment_line.quantity != line["planned_qty"]
                ):
                    raise serializers.ValidationError({"lines": f"第 {index} 行发货明细不一致。"})
        return attrs

    @transaction.atomic
    def create(self, validated_data):  # type: ignore[no-untyped-def]
        lines = validated_data.pop("lines")
        task = WarehouseTask.objects.create(**validated_data)
        WarehouseTaskLine.objects.bulk_create(
            [WarehouseTaskLine(task=task, **line) for line in lines]
        )
        return task

    @transaction.atomic
    def update(self, instance, validated_data):  # type: ignore[no-untyped-def]
        if instance.status != WarehouseTask.Status.DRAFT:
            raise serializers.ValidationError("只有草稿任务可以修改。")
        lines = validated_data.pop("lines", None)
        for name, value in validated_data.items():
            setattr(instance, name, value)
        instance.row_version += 1
        instance.save()
        if lines is not None:
            instance.lines.all().delete()
            WarehouseTaskLine.objects.bulk_create(
                [WarehouseTaskLine(task=instance, **line) for line in lines]
            )
        return instance


class WarehouseScanSerializer(serializers.Serializer[dict[str, object]]):
    line_id = serializers.IntegerField()
    scanned_value = serializers.CharField(max_length=300)
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6)
    idempotency_key = serializers.CharField(max_length=200)
    occurred_at = serializers.DateTimeField(default=timezone.now)
    device_id = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class WarehouseScanEventSerializer(serializers.ModelSerializer[WarehouseScanEvent]):
    class Meta:
        model = WarehouseScanEvent
        fields = "__all__"


class WarehouseTaskViewSet(viewsets.ModelViewSet[WarehouseTask]):
    queryset = WarehouseTask.objects.select_related(
        "company", "warehouse", "goods_receipt", "sales_shipment", "assigned_to"
    ).prefetch_related("lines", "scan_events")
    serializer_class = WarehouseTaskSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "warehouse.task.read",
        "retrieve": "warehouse.task.read",
        "create": "warehouse.task.manage",
        "update": "warehouse.task.manage",
        "partial_update": "warehouse.task.manage",
        "destroy": "warehouse.task.manage",
        "release": "warehouse.task.manage",
        "scan": "warehouse.scan.process",
        "complete": "warehouse.task.manage",
        "scans": "warehouse.task.read",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def perform_create(self, serializer: WarehouseTaskSerializer) -> None:
        company_id = company_id_for_request(self.request)
        if company_id is not None and serializer.validated_data["company"].pk != company_id:
            raise PermissionDenied("不能创建其他公司的仓储任务。")
        serializer.save()

    def perform_destroy(self, instance: WarehouseTask) -> None:
        if instance.status != WarehouseTask.Status.DRAFT:
            raise PermissionDenied("只有草稿仓储任务可以删除。")
        instance.delete()

    def _run(self, operation):  # type: ignore[no-untyped-def]
        try:
            task = operation()
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def release(self, request: Request, pk: str | None = None) -> Response:
        return self._run(lambda: release_task(task_id=self.get_object().pk, actor=_user(request)))

    @action(detail=True, methods=["post"])
    def scan(self, request: Request, pk: str | None = None) -> Response:
        serializer = WarehouseScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            event = record_scan(
                task_id=self.get_object().pk,
                actor=_user(request),
                **serializer.validated_data,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return Response(WarehouseScanEventSerializer(event).data)

    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: str | None = None) -> Response:
        return self._run(
            lambda: complete_task(
                task_id=self.get_object().pk, actor=_user(request), completed_at=timezone.now()
            )
        )

    @action(detail=True, methods=["get"])
    def scans(self, request: Request, pk: str | None = None) -> Response:
        events = self.get_object().scan_events.order_by("occurred_at", "id")
        return Response(WarehouseScanEventSerializer(events, many=True).data)
