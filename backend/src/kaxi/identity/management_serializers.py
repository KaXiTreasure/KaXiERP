from rest_framework import serializers

from kaxi.identity.models import (
    AtomicPermission,
    AuditLog,
    Department,
    Position,
    Role,
    RolePermission,
    User,
    UserPermissionOverride,
    UserRole,
)


class DepartmentSerializer(serializers.ModelSerializer[Department]):
    class Meta:
        model = Department
        fields = "__all__"


class PositionSerializer(serializers.ModelSerializer[Position]):
    class Meta:
        model = Position
        fields = "__all__"


class IdentityPermissionSerializer(serializers.ModelSerializer[AtomicPermission]):
    class Meta:
        model = AtomicPermission
        fields = "__all__"
        read_only_fields = ["permission_code", "name", "description", "risk_level", "row_version"]


class UserManagementSerializer(serializers.ModelSerializer[User]):
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    employee_no = serializers.CharField(required=False, allow_blank=True, default="")

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "password",
            "display_name",
            "employee_no",
            "email",
            "company",
            "department",
            "position",
            "mobile",
            "timezone",
            "locale",
            "status",
            "is_active",
            "must_change_password",
            "failed_login_attempts",
            "locked_at",
            "locked_reason",
            "row_version",
        ]
        read_only_fields = [
            "must_change_password",
            "failed_login_attempts",
            "locked_at",
            "locked_reason",
            "row_version",
        ]
        extra_kwargs = {
            "employee_no": {"required": False, "allow_blank": True},
            "email": {"required": False, "allow_blank": True},
        }

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs.get("company", getattr(self.instance, "company", None))
        department = attrs.get("department", getattr(self.instance, "department", None))
        position = attrs.get("position", getattr(self.instance, "position", None))
        if department and department.company_id != getattr(company, "pk", None):
            raise serializers.ValidationError("部门必须属于用户公司。")
        if position and position.company_id != getattr(company, "pk", None):
            raise serializers.ValidationError("岗位必须属于用户公司。")
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError("创建用户必须设置初始密码。")
        return attrs

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):  # type: ignore[no-untyped-def]
        password = validated_data.pop("password", None)
        previous_status = instance.status
        for name, value in validated_data.items():
            setattr(instance, name, value)
        if previous_status == User.Status.LOCKED and instance.status == User.Status.ACTIVE:
            instance.failed_login_attempts = 0
            instance.locked_at = None
            instance.locked_reason = ""
        if password:
            instance.set_password(password)
            instance.must_change_password = True
        instance.row_version += 1
        instance.save()
        return instance


class RoleSerializer(serializers.ModelSerializer[Role]):
    permission_ids = serializers.PrimaryKeyRelatedField(
        source="permissions",
        many=True,
        required=False,
        queryset=AtomicPermission.objects.filter(is_active=True),
    )

    class Meta:
        model = Role
        fields = [
            "id",
            "company",
            "role_code",
            "name",
            "is_active",
            "permission_ids",
            "row_version",
        ]
        read_only_fields = ["row_version"]

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        permissions = validated_data.pop("permissions", [])
        role = Role.objects.create(**validated_data)
        RolePermission.objects.bulk_create(
            [RolePermission(role=role, permission=permission) for permission in permissions]
        )
        return role

    def update(self, instance, validated_data):  # type: ignore[no-untyped-def]
        permissions = validated_data.pop("permissions", None)
        for name, value in validated_data.items():
            setattr(instance, name, value)
        instance.row_version += 1
        instance.save()
        if permissions is not None:
            RolePermission.objects.filter(role=instance).delete()
            RolePermission.objects.bulk_create(
                [RolePermission(role=instance, permission=permission) for permission in permissions]
            )
        return instance


class UserRoleSerializer(serializers.ModelSerializer[UserRole]):
    class Meta:
        model = UserRole
        fields = "__all__"

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        user = attrs.get("user", getattr(self.instance, "user", None))
        role = attrs.get("role", getattr(self.instance, "role", None))
        if user is None or role is None:
            raise serializers.ValidationError("用户和角色不能为空。")
        if role.company_id not in {None, user.company_id}:
            raise serializers.ValidationError("角色与用户公司不一致。")
        return attrs


class OverrideSerializer(serializers.ModelSerializer[UserPermissionOverride]):
    class Meta:
        model = UserPermissionOverride
        fields = "__all__"
        read_only_fields = [
            "approval_status",
            "requested_by",
            "approved_by",
            "approved_at",
            "revoked_by",
            "revoked_at",
            "row_version",
        ]


class IdentityAuditSerializer(serializers.ModelSerializer[AuditLog]):
    class Meta:
        model = AuditLog
        fields = "__all__"
