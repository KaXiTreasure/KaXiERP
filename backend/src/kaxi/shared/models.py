from django.db import models


class AuditedModel(models.Model):
    """Technical audit fields shared by business-owned models."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    row_version = models.PositiveBigIntegerField(default=1)

    class Meta:
        abstract = True
