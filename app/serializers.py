from rest_framework import serializers

from app.models import Grade
from users.models import User


class GradeSerializer(serializers.ModelSerializer):
    student = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.STUDENT, is_active=True),
    )
    student_name = serializers.CharField(source="student.display_name", read_only=True)
    teacher_name = serializers.CharField(source="teacher.display_name", read_only=True)

    class Meta:
        model = Grade
        fields = (
            "id",
            "student",
            "student_name",
            "subject",
            "value",
            "comment",
            "teacher",
            "teacher_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("teacher", "created_at", "updated_at")
