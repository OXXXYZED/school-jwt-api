from rest_framework.permissions import SAFE_METHODS, BasePermission

from users.permissions import IsTeacher


class IsTeacherOrReadOnly(IsTeacher):
    """Reading is open to any authenticated user (the queryset is scoped per role)."""

    message = "Only teachers can manage grades."

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or super().has_permission(request, view)


class IsGradeAuthorOrReadOnly(BasePermission):
    message = "You can only modify grades you have given."

    def has_object_permission(self, request, view, obj):
        return request.method in SAFE_METHODS or obj.teacher_id == request.user.pk
