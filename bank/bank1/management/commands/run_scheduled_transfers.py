from django.core.management.base import BaseCommand
from django.utils import timezone
from bank.bank1.models import ScheduledTransfer, Transaction, UserProfile

class Command(BaseCommand):
    help = 'Process all scheduled transfers (NEFT, IMPS, UPI) that are due'

    def handle(self, *args, **kwargs):
        due_transfers = ScheduledTransfer.objects.filter(
            status='Pending',
            schedule_datetime__lte=timezone.now()
        )

        for transfer in due_transfers:
            try:
                receiver_profile = UserProfile.objects.get(
                    user__username=transfer.receiver_name
                )

                # Credit receiver balance
                receiver_profile.balance += transfer.amount
                receiver_profile.save()

                # Mark scheduled transfer complete
                transfer.status = 'Completed'
                transfer.save()

                # Update related transaction status
                Transaction.objects.filter(
                    sender=transfer.user,
                    amount=transfer.amount,
                    method=transfer.payment_method,
                    status='pending',
                    scheduled_time=transfer.schedule_datetime
                ).update(status='completed')

                self.stdout.write(self.style.SUCCESS(
                    f"{transfer.payment_method} transfer {transfer.id} completed to {transfer.receiver_name}."
                ))

            except UserProfile.DoesNotExist:
                transfer.status = 'Failed'
                transfer.save()
                self.stderr.write(f"Transfer {transfer.id} failed: Receiver not found.")
