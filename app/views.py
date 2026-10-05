from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from app.models import Grade
from app.permissions import IsGradeAuthorOrReadOnly, IsTeacherOrReadOnly
from app.serializers import GradeSerializer


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("student", int, description="Filter by student id"),
            OpenApiParameter("subject", str, description="Filter by subject (case-insensitive)"),
        ],
    ),
)
class GradeViewSet(viewsets.ModelViewSet):
    """Grades: teachers see all grades and manage the ones they gave; students see only their own."""

    serializer_class = GradeSerializer
    permission_classes = [IsAuthenticated, IsTeacherOrReadOnly, IsGradeAuthorOrReadOnly]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # OpenAPI schema generation
            return Grade.objects.none()

        user = self.request.user
        queryset = Grade.objects.select_related("student", "teacher")
        if not user.is_teacher:
            queryset = queryset.filter(student=user)

        params = self.request.query_params
        if student := params.get("student"):
            if not student.isdigit():
                raise ValidationError({"student": "Must be an integer id."})
            queryset = queryset.filter(student_id=int(student))
        if subject := params.get("subject"):
            queryset = queryset.filter(subject__iexact=subject.strip())
        return queryset

    def perform_create(self, serializer):
        serializer.save(teacher=self.request.user)
