import secrets

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField("email address", unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    timezone = models.CharField(max_length=64, default="UTC")
    embed_enabled = models.BooleanField(default=False)
    embed_key = models.CharField(max_length=64, blank=True, default="")

    def __str__(self):
        return f"Profile for {self.user.email}"


class ApiToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_tokens")
    label = models.CharField(max_length=64)
    key = models.CharField(max_length=64, unique=True, db_index=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} ({self.user.email})"

    @classmethod
    def generate_key(cls) -> str:
        return secrets.token_hex(20)

    @classmethod
    def create_for_user(cls, user, label: str) -> "ApiToken":
        return cls.objects.create(user=user, label=label, key=cls.generate_key())

    def touch(self) -> None:
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])
