import uuid
from django.db import models
from django.dispatch import receiver
from django.db.models.signals import post_save
from django.contrib.auth.models import User
from django import forms
from django.utils import timezone
from django.contrib.auth.hashers import check_password,make_password

# class UserForm(models.Model):
#      username = models.CharField(max_length=150, unique=True)
#      email = models.EmailField(unique=True)
#      password = models.CharField(max_length=10)
#      password2 = models.CharField(max_length=10)
#      first_name = models.CharField(max_length=100)

class UserProfile(models.Model):
         user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='userprofile')
         is_approved = models.BooleanField(default=False)
         account_number = models.CharField(max_length=12, unique=True, null=True, blank=True)
         upi_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
         balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
         upi_pin = models.CharField(max_length=128, null=True, blank=True)     # New
         tpin = models.CharField(max_length=10, null=True, blank=True)
    
         def __str__(self):
              return self.user.username
    
         def set_upi_pin(self, raw_pin: str):
              if not raw_pin:
                       raise ValueError("UPI PIN cannot be empty")
              self.upi_pin = make_password(raw_pin)
              self.save()
    
         def check_pin(self, raw_pin: str) -> bool:
              if not self.upi_pin:
                       return False
              return check_password(raw_pin, self.upi_pin)

class Transaction(models.Model):
         METHOD_CHOICES = [
              ('UPI', 'UPI'),
              ('IMPS', 'IMPS'),
              ('NEFT', 'NEFT'),
              ('Deposit', 'Deposit'),
              ('Bill Payment', 'Bill Payment'),
              ('Recharge', 'Recharge'),
         ]

         BILL_CHOICES = [
              ('Electricity', 'Electricity'),
              ('Water', 'Water'),
              ('Gas', 'Gas'),
              ('Mobile', 'Mobile Recharge'),
              ('DTH', 'DTH Recharge'),
         ]

         TX_TYPE_CHOICES = [
              ('debit', 'Debit'),
              ('credit', 'Credit'),
              ('deposit', 'Deposit'),
         ]

         SERVICE_CHOICES = [
              ('FASTAG', 'FASTag Top-up'),
              ('METRO', 'Metro Card Top-up'),
         ]

         sender = models.ForeignKey(
              User, on_delete=models.CASCADE, related_name='sent_transactions', null=True, blank=True
         )
         receiver = models.ForeignKey(
              User, on_delete=models.CASCADE, related_name='received_transactions', null=True, blank=True
         )
         amount = models.DecimalField(max_digits=10, decimal_places=2)
         timestamp = models.DateTimeField(auto_now_add=True)
         method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='UPI')
         bill_type = models.CharField(max_length=20, choices=BILL_CHOICES, null=True, blank=True)
         tx_type = models.CharField(max_length=10, choices=TX_TYPE_CHOICES, default='debit')
         status = models.CharField(max_length=20, default='completed')
         scheduled_time = models.DateTimeField(null=True, blank=True)

         subscriber = models.CharField(max_length=64, null=True, blank=True)   
         operator = models.CharField(max_length=64, null=True, blank=True)         
         category = models.CharField(max_length=64, null=True, blank=True)         

         # Added fields for FASTag / Metro
         service_type = models.CharField(max_length=10, choices=SERVICE_CHOICES,default="")
         bank_name = models.CharField(max_length=100,default="")
         vehicle_or_card_number = models.CharField(max_length=50,default="")
         # This field will now automatically generate a unique ID
         transaction_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

         def __str__(self):
              # Priority: Bill Payment display
              if self.method == "Bill Payment":
                       return f"{self.tx_type.upper()}: {self.sender} paid {self.bill_type} bill ₹{self.amount}"
              # Recharge display
              if self.method == "Recharge":
                       return f"{self.tx_type.upper()}: {self.sender} recharged {self.subscriber} ({self.operator}, {self.category}) ₹{self.amount}"
              # FASTag / Metro display
              if self.service_type:
                       return f"{self.service_type} - {self.transaction_id} - ₹{self.amount}"
              # Default display
              return f"{self.tx_type.upper()}: {self.sender} → {self.receiver} ₹{self.amount} via {self.method}"
    
# @receiver(post_save, sender=User)
# def create_or_update_user_profile(sender, instance, created, **kwargs):
#      if created:
#               UserProfile.objects.create(user=instance)
#      else:
#               instance.userprofile.save()     

class UserAccount(models.Model):
         name = models.CharField(max_length=100)
         upi_id = models.CharField(max_length=100, unique=True)
         # ifsc_code = models.CharField(max_length=11)
         balance = models.DecimalField(max_digits=10, decimal_places=2)

         def __str__(self):
              return f"{self.name} ({self.upi_id})"


class Notification(models.Model):
         user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
         message = models.TextField()
         created_at = models.DateTimeField(auto_now_add=True)


         def __str__(self):
              return f"{self.user.username}: {self.message}"
    
class BankTransferForm(forms.Form):
         receiver_account_number = forms.CharField(max_length=20, label="Receiver Account Number")
         amount = forms.DecimalField(max_digits=10, decimal_places=2)
         method = forms.ChoiceField(
              choices=[('NEFT', 'NEFT (30-60 mins)'), ('IMPS', 'IMPS (Instant)')],
         )

class Beneficiary(models.Model):
         TYPE_CHOICES = [
              ('bank', 'Bank Transfer'),
              ('upi', 'UPI Transfer'),
         ]

         user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='beneficiaries')    # Owner of beneficiary
         beneficiary_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_from', null=True, blank=True)     # Actual receiver
    
         type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='bank')
         name = models.CharField(max_length=100)
         account_number = models.CharField(max_length=20, blank=True, null=True)
         ifsc = models.CharField(max_length=11, blank=True, null=True)
         upi_id = models.CharField(max_length=50, blank=True, null=True)

         def __str__(self):
              return f"{self.name} ({self.type})"

class ScheduledTransfer(models.Model):
         TRANSFER_METHODS = (
              ('UPI', 'UPI'),
              ('NEFT', 'NEFT'),
              ('IMPS', 'IMPS'),
         )

         user = models.ForeignKey(User, on_delete=models.CASCADE)
         receiver_name = models.CharField(max_length=100)
         receiver_upi = models.CharField(max_length=100, blank=True)
         receiver_account = models.CharField(max_length=20, blank=True)
         ifsc = models.CharField(max_length=11, blank=True)
         method = models.CharField(max_length=10, choices=TRANSFER_METHODS)
         amount = models.DecimalField(max_digits=10, decimal_places=2)
         tpin = models.CharField(max_length=10)
         schedule_datetime = models.DateTimeField()
         status = models.CharField(max_length=20, default='Pending')   # Pending, Completed, Failed

         created_at = models.DateTimeField(auto_now_add=True)

         def is_due(self):
              return timezone.now() >= self.schedule_datetime
    
class UPIRequest(models.Model):
         STATUS_CHOICES = [
              ('pending', 'Pending'),
              ('approved', 'Approved'),
              ('declined', 'Declined'),
              ('later', 'Later'),
         ]

         requester = models.ForeignKey(User, on_delete=models.CASCADE, related_name='money_requests_sent')
         requestee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='money_requests_received')
         amount = models.DecimalField(max_digits=10, decimal_places=2)
         reason = models.CharField(max_length=255, blank=True, null=True)
         status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
         created_at = models.DateTimeField(auto_now_add=True)

         def __str__(self):
              return f"₹{self.amount} request from {self.requester.username} to {self.requestee.username} ({self.status})"

class SavedNumber(models.Model):
         user = models.ForeignKey(User, on_delete=models.CASCADE)
         number = models.CharField(max_length=15)
         operator = models.CharField(max_length=50)
         date_added = models.DateTimeField(auto_now_add=True)

         class Meta:
              unique_together = ('number', 'operator')

         def __str__(self):
              return f"{self.number} - {self.operator}"     
    
class Recharge(models.Model):
         user = models.ForeignKey(User, on_delete=models.CASCADE)
         mobile_number = models.CharField(max_length=15)   # add this
         operator = models.CharField(max_length=100)
         plan_amount = models.DecimalField(max_digits=10, decimal_places=2)
         date = models.DateTimeField(auto_now_add=True)
    
         def __str__(self):
              return f"{self.user.username} | {self.mobile_number} | ₹{self.plan_amount}" 
