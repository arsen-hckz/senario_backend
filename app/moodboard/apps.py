from django.apps import AppConfig


class MoodboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'moodboard'

    def ready(self):
        from . import signals  # noqa: F401
