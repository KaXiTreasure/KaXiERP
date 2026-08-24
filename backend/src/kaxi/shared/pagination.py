from rest_framework.pagination import CursorPagination


class StableCursorPagination(CursorPagination):
    """Stable pagination for models with heterogeneous timestamp field names."""

    ordering = "-pk"
