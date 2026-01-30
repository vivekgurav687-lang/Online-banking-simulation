from django.utils import timezone
from .models import ScheduledTransfer, Transaction, UserProfile

def update_pending_transactions():
    due_transfers = ScheduledTransfer.objects.filter(
        status='Pending',
        schedule_datetime__lte=timezone.now()
    )

    for transfer in due_transfers:
        try:
            # Credit receiver balance
            receiver_profile = UserProfile.objects.get(
                user__username=transfer.receiver_name
            )
            receiver_profile.balance += transfer.amount
            receiver_profile.save()

            # Mark scheduled transfer complete
            transfer.status = 'Completed'
            transfer.save()

            # Update matching transaction
            Transaction.objects.filter(
                sender=transfer.user,
                amount=transfer.amount,
                method=transfer.payment_method,
                status='pending',
                scheduled_time=transfer.schedule_datetime
            ).update(status='completed')

        except UserProfile.DoesNotExist:
            transfer.status = 'Failed'
            transfer.save()
