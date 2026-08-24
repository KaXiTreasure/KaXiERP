from rest_framework.routers import DefaultRouter

from kaxi.master_data.merge_api import MergeCandidateViewSet
from kaxi.master_data.models import (
    Address,
    Company,
    Currency,
    CustomerProfile,
    Party,
    PartyContact,
    Region,
    SupplierProfile,
    UnitOfMeasure,
)
from kaxi.shared.crud import crud_for, unscoped_crud_for

router = DefaultRouter()
router.register("companies", crud_for(Company, "system.company.manage", "id"), basename="company")
router.register(
    "currencies", unscoped_crud_for(Currency, "system.config.manage"), basename="currency"
)
router.register("regions", unscoped_crud_for(Region, "system.config.manage"), basename="region")
router.register("uoms", unscoped_crud_for(UnitOfMeasure, "system.config.manage"), basename="uom")
router.register("merge-candidates", MergeCandidateViewSet, basename="party-merge-candidate")
router.register("parties", crud_for(Party, "master.party.manage"), basename="party")
router.register(
    "customer-profiles",
    crud_for(CustomerProfile, "master.party.manage", "party__company_id"),
    basename="customer-profile",
)
router.register(
    "supplier-profiles",
    crud_for(SupplierProfile, "master.party.manage", "party__company_id"),
    basename="supplier-profile",
)
router.register(
    "contacts",
    crud_for(PartyContact, "master.party.manage", "party__company_id"),
    basename="party-contact",
)
router.register(
    "addresses",
    crud_for(Address, "master.party.manage", "party__company_id"),
    basename="party-address",
)
urlpatterns = router.urls
