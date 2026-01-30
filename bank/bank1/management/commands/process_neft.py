from django.core.management.base import BaseCommand
from django.utils import timezone
from bank1.models import Transaction, UserProfile

class Command(BaseCommand):
    help = 'Process pending NEFT transactions'

    def handle(self, *args, **kwargs):
        now = timezone.now()
        pending_nefts = Transaction.objects.filter(
            method='NEFT',
            status='pending',
            scheduled_time__lte=now
        )

        for tx in pending_nefts:
            receiver_profile = tx.receiver.userprofile
            receiver_profile.balance += tx.amount
            receiver_profile.save()

            tx.status = 'completed'
            tx.save()

        self.stdout.write(self.style.SUCCESS(f"{pending_nefts.count()} NEFT transactions processed."))
