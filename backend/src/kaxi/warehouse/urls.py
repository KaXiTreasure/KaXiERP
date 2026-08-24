from rest_framework.routers import DefaultRouter

from kaxi.shared.crud import crud_for
from kaxi.warehouse.models import Warehouse, WarehouseArea, WarehouseLocation, WarehouseRack
from kaxi.warehouse.task_api import WarehouseTaskViewSet

router = DefaultRouter()
router.register("warehouses", crud_for(Warehouse, "warehouse.master.manage"), basename="warehouse")
router.register(
    "areas",
    crud_for(WarehouseArea, "warehouse.master.manage", "warehouse__company_id"),
    basename="warehouse-area",
)
router.register("tasks", WarehouseTaskViewSet, basename="warehouse-task")
router.register(
    "racks",
    crud_for(WarehouseRack, "warehouse.master.manage", "warehouse__company_id"),
    basename="warehouse-rack",
)
router.register(
    "locations",
    crud_for(WarehouseLocation, "warehouse.master.manage", "warehouse__company_id"),
    basename="warehouse-location",
)
urlpatterns = router.urls
