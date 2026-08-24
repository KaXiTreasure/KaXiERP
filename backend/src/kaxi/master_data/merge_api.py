from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import AuditLog, User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.master_data.merge_services import (
    approve_party_merge,
    detect_party_duplicates,
    reject_party_merge,
)
from kaxi.master_data.models import PartyMergeCandidate


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied("需要有效业务用户。")
    return request.user


class MergeCandidateSerializer(serializers.ModelSerializer[PartyMergeCandidate]):
    class Meta:
        model = PartyMergeCandidate
        fields = "__all__"
        read_only_fields = [
            "status",
            "requested_by",
            "decided_by",
            "decided_at",
            "decision_reason",
            "reference_counts",
            "row_version",
        ]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs["company"]
        canonical = attrs["canonical_party"]
        duplicate = attrs["duplicate_party"]
        if canonical.pk == duplicate.pk:
            raise serializers.ValidationError("合并源和目标不能相同。")
        if canonical.company_id != company.pk or duplicate.company_id != company.pk:
            raise serializers.ValidationError("合并双方必须属于候选公司。")
        if canonical.merged_into_id or duplicate.merged_into_id:
            raise serializers.ValidationError("已合并档案不能再次加入候选。")
        return attrs


class DetectSerializer(serializers.Serializer[dict[str, int]]):
    company_id = serializers.IntegerField(required=False)


class RejectSerializer(serializers.Serializer[dict[str, str]]):
    reason = serializers.CharField()


class MergeCandidateViewSet(viewsets.ModelViewSet[PartyMergeCandidate]):
    queryset = PartyMergeCandidate.objects.select_related(
        "company", "canonical_party", "duplicate_party", "requested_by", "decided_by"
    ).order_by("-created_at")
    serializer_class = MergeCandidateSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        name: "mdm.merge.approve"
        for name in ["list", "retrieve", "create", "destroy", "detect", "approve", "reject"]
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def perform_create(self, serializer: MergeCandidateSerializer) -> None:
        company_id = company_id_for_request(self.request)
        if company_id is not None and serializer.validated_data["company"].pk != company_id:
            raise PermissionDenied("不能创建其他公司的合并候选。")
        serializer.save(requested_by=_user(self.request))

    def perform_destroy(self, instance: PartyMergeCandidate) -> None:
        if instance.status != PartyMergeCandidate.Status.PENDING:
            raise PermissionDenied("已处理的合并记录不可删除。")
        instance.delete()

    @action(detail=False, methods=["post"])
    def detect(self, request: Request) -> Response:
        serializer = DetectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company_id = company_id_for_request(request)
        requested = serializer.validated_data.get("company_id")
        if company_id is None:
            if not requested:
                raise ValidationError("超级管理员执行查重时必须指定 company_id。")
            company_id = requested
        elif requested and requested != company_id:
            raise PermissionDenied("不能扫描其他公司的主数据。")
        count = detect_party_duplicates(company_id=company_id, actor=_user(request))
        return Response({"created_candidates": count}, status=status.HTTP_201_CREATED)

    def _audit(self, request: Request, candidate: PartyMergeCandidate, action_name: str) -> None:
        AuditLog.objects.create(
            company=candidate.company,
            actor=_user(request),
            action=action_name,
            object_type="master_data.party_merge_candidate",
            object_id=str(candidate.pk),
            changes={"reference_counts": candidate.reference_counts},
        )

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        try:
            candidate = approve_party_merge(candidate_id=self.get_object().pk, actor=_user(request))
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        self._audit(request, candidate, "master_data.party_merge.approve")
        return Response(self.get_serializer(candidate).data)

    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        serializer = RejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            candidate = reject_party_merge(
                candidate_id=self.get_object().pk,
                actor=_user(request),
                reason=serializer.validated_data["reason"],
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        self._audit(request, candidate, "master_data.party_merge.reject")
        return Response(self.get_serializer(candidate).data)
