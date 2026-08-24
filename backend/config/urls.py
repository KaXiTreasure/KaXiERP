from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("kaxi.identity.urls")),
    path("api/v1/system/", include("kaxi.system.urls")),
    path("api/v1/master-data/", include("kaxi.master_data.urls")),
    path("api/v1/products/", include("kaxi.products.urls")),
    path("api/v1/warehouses/", include("kaxi.warehouse.urls")),
    path("api/v1/pricing/", include("kaxi.pricing.urls")),
    path("api/v1/sales/", include("kaxi.sales.urls")),
    path("api/v1/purchasing/", include("kaxi.purchasing.urls")),
    path("api/v1/inventory/", include("kaxi.inventory.urls")),
    path("api/v1/manufacturing/", include("kaxi.manufacturing.urls")),
    path("api/v1/prepack/", include("kaxi.prepack.urls")),
    path("api/v1/product-serials/", include("kaxi.products.serial_urls")),
    path("api/v1/finance/", include("kaxi.finance.urls")),
    path("api/v1/workflow/", include("kaxi.workflow.urls")),
    path("api/v1/documents/", include("kaxi.documents.urls")),
    path("api/v1/integrations/", include("kaxi.integrations.urls")),
    path("api/v1/trade/", include("kaxi.trade.urls")),
    path("api/v1/aftersales/", include("kaxi.aftersales.urls")),
    path("api/v1/analytics/", include("kaxi.analytics.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
