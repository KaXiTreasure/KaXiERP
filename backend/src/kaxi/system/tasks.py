from celery import shared_task
from django.db import transaction
from django.utils import timezone

from kaxi.documents.models import ShareLink
from kaxi.identity.models import UserPermissionOverride
from kaxi.inventory.models import InventoryReservation
from kaxi.inventory.reservation_services import release_reservation
from kaxi.pricing.models import PriceList
from kaxi.system.branding_services import refresh_bing_background
from kaxi.system.models import BrandingConfiguration
from kaxi.system.task_runtime import recorded_task
from kaxi.workflow.models import ApprovalTask, Notification


def _window(minutes: int) -> str:
    now = timezone.now()
    return str(int(now.timestamp()) // (minutes * 60))


@shared_task(name="auth.expire_user_overrides")
def expire_user_overrides() -> int:
    with recorded_task(
        task_name="auth.expire_user_overrides",
        idempotency_key=_window(1),
        queue="critical",
    ) as execution:
        if execution is None:
            return 0
        return UserPermissionOverride.objects.filter(
            revoked_at__isnull=True, expires_at__isnull=False, expires_at__lte=timezone.now()
        ).update(revoked_at=timezone.now())


@shared_task(name="document.expire_shares")
def expire_shares() -> int:
    with recorded_task(
        task_name="document.expire_shares",
        idempotency_key=_window(1),
        queue="documents",
    ) as execution:
        if execution is None:
            return 0
        return ShareLink.objects.filter(
            revoked_at__isnull=True, expires_at__lte=timezone.now()
        ).update(revoked_at=timezone.now())


@shared_task(name="inventory.release_expired_reservations")
def release_expired_reservations() -> int:
    with recorded_task(
        task_name="inventory.release_expired_reservations",
        idempotency_key=_window(1),
        queue="critical",
    ) as execution:
        if execution is None:
            return 0
        ids = list(
            InventoryReservation.objects.filter(
                status=InventoryReservation.Status.ACTIVE,
                expires_at__isnull=False,
                expires_at__lte=timezone.now(),
            ).values_list("pk", flat=True)
        )
        for reservation_id in ids:
            with transaction.atomic():
                reservation = InventoryReservation.objects.get(pk=reservation_id)
                remaining = reservation.remaining_qty
                if remaining > 0:
                    release_reservation(reservation_id=reservation_id, quantity=remaining)
                InventoryReservation.objects.filter(pk=reservation_id).update(
                    status=InventoryReservation.Status.EXPIRED
                )
        return len(ids)


@shared_task(name="workflow.escalate_overdue_tasks")
def escalate_overdue_tasks() -> int:
    with recorded_task(
        task_name="workflow.escalate_overdue_tasks",
        idempotency_key=_window(15),
        queue="maintenance",
    ) as execution:
        if execution is None:
            return 0
        count = 0
        tasks = ApprovalTask.objects.filter(
            status=ApprovalTask.Status.PENDING,
            due_at__lt=timezone.now(),
            assignee__isnull=False,
        ).select_related("assignee", "instance")
        for task in tasks:
            _, created = Notification.objects.get_or_create(
                user=task.assignee,
                notification_type="approval.overdue",
                business_type="approval_task",
                business_id=str(task.pk),
                defaults={
                    "title": "审批任务已逾期",
                    "body": f"审批任务 #{task.pk} 已超过截止时间，请及时处理。",
                },
            )
            count += int(created)
        return count


@shared_task(name="pricing.activate_versions")
def activate_price_versions() -> int:
    now = timezone.now()
    with recorded_task(
        task_name="pricing.activate_versions",
        idempotency_key=_window(1),
        queue="maintenance",
    ) as execution:
        if execution is None:
            return 0
        activated = PriceList.objects.filter(
            status=PriceList.Status.APPROVED, valid_from__lte=now
        ).update(status=PriceList.Status.ACTIVE)
        expired = PriceList.objects.filter(
            status=PriceList.Status.ACTIVE, valid_to__isnull=False, valid_to__lte=now
        ).update(status=PriceList.Status.EXPIRED)
        return activated + expired


@shared_task(name="branding.refresh_bing_background")
def refresh_bing_background_task() -> int:
    configuration = BrandingConfiguration.objects.filter(singleton_key="global").first()
    if (
        configuration is None
        or configuration.background_source != BrandingConfiguration.BackgroundSource.BING
    ):
        return 0
    refresh_bing_background()
    return 1
