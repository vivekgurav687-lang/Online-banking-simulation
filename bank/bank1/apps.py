from django.apps import AppConfig


class Bank1Config(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bank1'

    def ready(self):
        import bank1.signals