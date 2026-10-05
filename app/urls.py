from rest_framework.routers import DefaultRouter

from app.views import GradeViewSet

app_name = "school"

router = DefaultRouter()
router.register("grades", GradeViewSet, basename="grade")

urlpatterns = router.urls
