import secrets

from accounts.models import UserProfile


def ensure_embed_key(profile: UserProfile) -> str:
    if not profile.embed_key:
        profile.embed_key = secrets.token_urlsafe(32)
        profile.save(update_fields=["embed_key"])
    return profile.embed_key
