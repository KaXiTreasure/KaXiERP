import re
from collections import defaultdict

from django.db import IntegrityError, transaction
from django.utils import timezone

from kaxi.identity.models import User
from kaxi.master_data.models import Party, PartyMergeCandidate
from kaxi.shared.outbox_service import append_outbox_event


def _normalized_name(value: str) -> str:
    return re.sub(r"[^\w]", "", value.casefold(), flags=re.UNICODE)


@transaction.atomic
def detect_party_duplicates(*, company_id: int, actor: User) -> int:
    groups: dict[str, list[Party]] = defaultdict(list)
    parties = Party.objects.filter(company_id=company_id, merged_into__isnull=True).order_by("id")
    for party in parties:
        key = _normalized_name(party.legal_name or party.display_name)
        if key:
            groups[key].append(party)
    created = 0
    for matches in groups.values():
        if len(matches) < 2:
            continue
        canonical = matches[0]
        for duplicate in matches[1:]:
            _, was_created = PartyMergeCandidate.objects.get_or_create(
                company_id=company_id,
                canonical_party=canonical,
                duplicate_party=duplicate,
                defaults={
                    "match_score": 1,
                    "match_reasons": ["normalized_legal_name"],
                    "requested_by": actor,
                },
            )
            created += int(was_created)
    return created


@transaction.atomic
def approve_party_merge(*, candidate_id: int, actor: User) -> PartyMergeCandidate:
    candidate = (
        PartyMergeCandidate.objects.select_for_update()
        .select_related("canonical_party", "duplicate_party", "company", "requested_by")
        .get(pk=candidate_id)
    )
    if candidate.status != PartyMergeCandidate.Status.PENDING:
        raise ValueError("合并候选已经处理。")
    if candidate.requested_by_id == actor.pk:
        raise ValueError("合并申请人与审批人必须分离。")
    canonical = Party.objects.select_for_update().get(pk=candidate.canonical_party_id)
    duplicate = Party.objects.select_for_update().get(pk=candidate.duplicate_party_id)
    if canonical.company_id != candidate.company_id or duplicate.company_id != candidate.company_id:
        raise ValueError("合并双方必须属于候选公司。")
    if canonical.merged_into_id or duplicate.merged_into_id:
        raise ValueError("已合并档案不能再次作为合并源或目标。")

    counts: dict[str, int] = {}
    try:
        for relation in Party._meta.related_objects:
            model = relation.related_model
            if model is PartyMergeCandidate:
                continue
            field = relation.field
            source_rows = model.objects.filter(**{field.name: duplicate})
            if not source_rows.exists():
                continue
            if relation.one_to_one and model.objects.filter(**{field.name: canonical}).exists():
                raise ValueError(f"目标档案已存在一对一资料：{model._meta.label_lower}")
            updated = source_rows.update(**{field.name: canonical})
            counts[f"{model._meta.label_lower}.{field.name}"] = updated
    except IntegrityError as exc:
        raise ValueError("关联记录存在唯一性冲突，必须先人工清理后再合并。") from exc

    duplicate.status = Party.Status.INACTIVE
    duplicate.merged_into = canonical
    duplicate.merged_at = candidate.decided_at = timezone.now()
    duplicate.merged_by = actor
    duplicate.row_version += 1
    duplicate.save()
    candidate.status = PartyMergeCandidate.Status.APPROVED
    candidate.decided_by = actor
    candidate.reference_counts = counts
    candidate.row_version += 1
    candidate.save()
    append_outbox_event(
        company=candidate.company,
        aggregate_type="party_merge",
        aggregate_id=str(candidate.pk),
        aggregate_version=candidate.row_version,
        event_type="master_data.party.merged",
        payload={
            "canonical_party_id": canonical.pk,
            "duplicate_party_id": duplicate.pk,
            "reference_counts": counts,
        },
    )
    return candidate


@transaction.atomic
def reject_party_merge(*, candidate_id: int, actor: User, reason: str) -> PartyMergeCandidate:
    candidate = PartyMergeCandidate.objects.select_for_update().get(pk=candidate_id)
    if candidate.status != PartyMergeCandidate.Status.PENDING:
        raise ValueError("合并候选已经处理。")
    candidate.mark_decided(actor=actor, status=PartyMergeCandidate.Status.REJECTED, reason=reason)
    candidate.row_version += 1
    candidate.save()
    return candidate
