from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from kaxi.identity.models import User, UserRole
from kaxi.shared.outbox_service import append_outbox_event
from kaxi.workflow.models import (
    ApprovalDefinition,
    ApprovalInstance,
    ApprovalNode,
    ApprovalTask,
    Notification,
)


def _role_users(node: ApprovalNode) -> list[User]:
    now = timezone.now()
    return list(
        User.objects.filter(
            userrole__role=node.approver_role,
            userrole__starts_at__lte=now,
            status=User.Status.ACTIVE,
        )
        .filter(Q(userrole__expires_at__isnull=True) | Q(userrole__expires_at__gt=now))
        .distinct()
    )


def _create_tasks(instance: ApprovalInstance, node: ApprovalNode) -> list[ApprovalTask]:
    due_at = timezone.now() + timedelta(hours=node.timeout_hours)
    if node.approver_user_id:
        users = [node.approver_user]
    elif node.approval_mode == ApprovalNode.Mode.ALL:
        users = _role_users(node)
    else:
        users = []
    if node.approval_mode == ApprovalNode.Mode.ALL and not users:
        raise ValidationError("会签节点当前没有有效审批人。")
    tasks = []
    if users:
        for user in users:
            task = ApprovalTask.objects.create(
                instance=instance, node=node, assignee=user, due_at=due_at
            )
            tasks.append(task)
            Notification.objects.create(
                user=user,
                notification_type="approval_task",
                title=f"待审批：{node.name}",
                business_type=instance.business_type,
                business_id=instance.business_id,
            )
    else:
        tasks.append(
            ApprovalTask.objects.create(
                instance=instance,
                node=node,
                assignee_role=node.approver_role,
                due_at=due_at,
            )
        )
    return tasks


@transaction.atomic
def start_approval(
    *,
    company_id: int,
    definition_id: int,
    business_type: str,
    business_id: str,
    applicant: User,
    snapshot: dict[str, object],
    idempotency_key: str,
) -> ApprovalInstance:
    existing = ApprovalInstance.objects.filter(
        company_id=company_id, idempotency_key=idempotency_key
    ).first()
    if existing:
        return existing
    definition = ApprovalDefinition.objects.select_for_update().get(pk=definition_id)
    now = timezone.now()
    if (
        definition.company_id != company_id
        or definition.business_type != business_type
        or definition.status != ApprovalDefinition.Status.ACTIVE
        or definition.effective_from > now
        or (definition.effective_to and definition.effective_to <= now)
    ):
        raise ValidationError("审批定义对当前业务无效。")
    first_node = definition.nodes.order_by("step_no").first()
    if first_node is None:
        raise ValidationError("审批定义没有节点。")
    instance = ApprovalInstance.objects.create(
        company_id=company_id,
        definition=definition,
        business_type=business_type,
        business_id=business_id,
        applicant=applicant,
        current_step=first_node.step_no,
        business_snapshot=snapshot,
        idempotency_key=idempotency_key,
    )
    _create_tasks(instance, first_node)
    append_outbox_event(
        company=definition.company,
        aggregate_type="workflow.approval",
        aggregate_id=str(instance.pk),
        aggregate_version=instance.row_version,
        event_type="workflow.approval.started",
        payload={"business_type": business_type, "business_id": business_id},
    )
    return instance


def _can_process(task: ApprovalTask, actor: User) -> bool:
    if task.assignee_id:
        return task.assignee_id == actor.pk
    now = timezone.now()
    return (
        UserRole.objects.filter(user=actor, role=task.assignee_role, starts_at__lte=now)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .exists()
    )


@transaction.atomic
def decide_task(*, task_id: int, actor: User, decision: str, comment: str = "") -> ApprovalInstance:
    task = (
        ApprovalTask.objects.select_for_update()
        .select_related("instance__company", "node")
        .get(pk=task_id)
    )
    instance = ApprovalInstance.objects.select_for_update().get(pk=task.instance_id)
    if (
        task.status != ApprovalTask.Status.PENDING
        or instance.status != ApprovalInstance.Status.PENDING
    ):
        raise ValidationError("审批任务已经处理。")
    if not _can_process(task, actor):
        raise PermissionDenied("当前用户不是此任务的有效审批人。")
    if instance.applicant_id == actor.pk:
        raise PermissionDenied("申请人不得审批自己的申请。")
    if decision not in {ApprovalTask.Status.APPROVED, ApprovalTask.Status.REJECTED}:
        raise ValidationError("审批结论必须是 approved 或 rejected。")
    task.status = decision
    task.decision_by = actor
    task.decision_at = timezone.now()
    task.comment = comment
    task.row_version += 1
    task.save()
    if decision == ApprovalTask.Status.REJECTED:
        instance.status = ApprovalInstance.Status.REJECTED
        instance.completed_at = timezone.now()
        instance.tasks.filter(status=ApprovalTask.Status.PENDING).update(
            status=ApprovalTask.Status.CANCELLED
        )
    else:
        node_tasks = instance.tasks.filter(node=task.node)
        node_complete = (
            not node_tasks.filter(status=ApprovalTask.Status.PENDING).exists()
            if task.node.approval_mode == ApprovalNode.Mode.ALL
            else True
        )
        if node_complete:
            node_tasks.filter(status=ApprovalTask.Status.PENDING).update(
                status=ApprovalTask.Status.CANCELLED
            )
            next_node = (
                instance.definition.nodes.filter(step_no__gt=task.node.step_no)
                .order_by("step_no")
                .first()
            )
            if next_node:
                instance.current_step = next_node.step_no
                _create_tasks(instance, next_node)
            else:
                instance.status = ApprovalInstance.Status.APPROVED
                instance.completed_at = timezone.now()
    instance.row_version += 1
    instance.save()
    if instance.status != ApprovalInstance.Status.PENDING:
        Notification.objects.create(
            user=instance.applicant,
            notification_type="approval_result",
            title=f"审批{instance.get_status_display()}：{instance.business_type}",
            business_type=instance.business_type,
            business_id=instance.business_id,
        )
        append_outbox_event(
            company=instance.company,
            aggregate_type="workflow.approval",
            aggregate_id=str(instance.pk),
            aggregate_version=instance.row_version,
            event_type=f"workflow.approval.{instance.status}",
            payload={"business_type": instance.business_type, "business_id": instance.business_id},
        )
    return instance


@transaction.atomic
def transfer_task(*, task_id: int, actor: User, target: User, comment: str) -> ApprovalTask:
    task = ApprovalTask.objects.select_for_update().get(pk=task_id)
    if not _can_process(task, actor) or task.status != ApprovalTask.Status.PENDING:
        raise PermissionDenied("当前任务不可转交。")
    if target.company_id != task.instance.company_id or target.status != User.Status.ACTIVE:
        raise ValidationError("只能转交给同公司有效用户。")
    task.status = ApprovalTask.Status.TRANSFERRED
    task.decision_by = actor
    task.decision_at = timezone.now()
    task.comment = comment
    task.save()
    new_task = ApprovalTask.objects.create(
        instance=task.instance,
        node=task.node,
        assignee=target,
        due_at=task.due_at,
        transferred_from=task,
    )
    Notification.objects.create(
        user=target,
        notification_type="approval_task",
        title=f"转交待审批：{task.node.name}",
        business_type=task.instance.business_type,
        business_id=task.instance.business_id,
    )
    return new_task
