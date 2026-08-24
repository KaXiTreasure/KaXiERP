from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied

from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request


class AllFieldsSerializer(serializers.ModelSerializer):
    class Meta:
        fields = "__all__"


class ScopedCrudViewSet(viewsets.ModelViewSet):
    permission_classes = [AtomicPermissionRequired]
    company_lookup = "company_id"

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return (
            queryset if company_id is None else queryset.filter(**{self.company_lookup: company_id})
        )

    def _assert_company(self, instance):  # type: ignore[no-untyped-def]
        company_id = company_id_for_request(self.request)
        if company_id is None:
            return
        actual = instance
        for part in self.company_lookup.removesuffix("_id").split("__"):
            actual = getattr(actual, part)
        if getattr(actual, "pk", actual) != company_id:
            raise PermissionDenied("不能写入其他公司的主数据。")

    @transaction.atomic
    def perform_create(self, serializer):  # type: ignore[no-untyped-def]
        instance = serializer.save()
        self._assert_company(instance)

    @transaction.atomic
    def perform_update(self, serializer):  # type: ignore[no-untyped-def]
        instance = serializer.save()
        self._assert_company(instance)

    @transaction.atomic
    def perform_destroy(self, instance):  # type: ignore[no-untyped-def]
        self._assert_company(instance)
        instance.delete()


def serializer_for(model):  # type: ignore[no-untyped-def]
    meta = type("Meta", (), {"model": model, "fields": "__all__"})
    prefix = model._meta.app_label.title().replace("_", "")
    return type(f"{prefix}{model.__name__}Serializer", (AllFieldsSerializer,), {"Meta": meta})


def crud_for(model, permission: str, company_lookup: str = "company_id"):  # type: ignore[no-untyped-def]
    actions = ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    return type(
        f"{model.__name__}ViewSet",
        (ScopedCrudViewSet,),
        {
            "queryset": model.objects.all(),
            "serializer_class": serializer_for(model),
            "company_lookup": company_lookup,
            "atomic_permissions": dict.fromkeys(actions, permission),
        },
    )


def unscoped_crud_for(model, permission: str):  # type: ignore[no-untyped-def]
    actions = ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    return type(
        f"{model.__name__}GlobalViewSet",
        (viewsets.ModelViewSet,),
        {
            "queryset": model.objects.all(),
            "serializer_class": serializer_for(model),
            "permission_classes": [AtomicPermissionRequired],
            "atomic_permissions": dict.fromkeys(actions, permission),
        },
    )
