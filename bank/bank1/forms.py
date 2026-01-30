from django import forms
from django.contrib.auth.models import User
from .models import Beneficiary, ScheduledTransfer, Transaction, UserProfile

class UserForm(forms.ModelForm):
    password2 = forms.CharField(label='Confirm Password', widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password']
        widgets = {
            'password': forms.PasswordInput()
        }

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password2 = cleaned_data.get("password2")
        if password and password2 and password != password2:
            raise forms.ValidationError("Passwords do not match")
        return cleaned_data



class UPIForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['upi_id','balance']
        widgets = {
            'upi_id': forms.TextInput(attrs={'placeholder': 'Enter your UPI ID'}),
            'ifsc_code': forms.TextInput(attrs={'placeholder': 'Enter your IFSC Code'}),
        }


class TransferForm(forms.Form):
    receiver_upi = forms.CharField(label="Receiver UPI ID")
    amount = forms.DecimalField(label="Amount (₹)", min_value=1)

class PinUpdateForm(forms.Form):
    upi_pin = forms.CharField(max_length=6, required=False, widget=forms.PasswordInput(attrs={'placeholder': 'New UPI PIN'}))
    tpin = forms.CharField(max_length=6, required=False, widget=forms.PasswordInput(attrs={'placeholder': 'New T-PIN'}))

class DepositForm(forms.Form):
    account_number = forms.CharField(max_length=12)
    amount = forms.DecimalField(max_digits=10, decimal_places=2, label='Amount to Deposit')

class BeneficiaryForm(forms.ModelForm):
    class Meta:
        model = Beneficiary
        exclude = ['user', 'type']  # We set these manually in the view
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Full Name','readonly': 'readonly'}),
            'account_number': forms.TextInput(attrs={'placeholder': 'Account Number','readonly': 'readonly'}),
            'ifsc': forms.TextInput(attrs={'placeholder': 'IFSC Code'}),  
            'upi_id': forms.TextInput(attrs={'placeholder': 'UPI ID','readonly': 'readonly'}),
        }


class BankTransferForm(forms.Form):
    beneficiary = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label="Select Beneficiary (Optional)"
    )
    receiver_account_number = forms.CharField(max_length=20, required=False)
    amount = forms.DecimalField(max_digits=10, decimal_places=2)
    method = forms.ChoiceField(choices=[('NEFT', 'NEFT'), ('IMPS', 'IMPS')])

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            self.fields['beneficiary'].queryset = Beneficiary.objects.filter(user=user)  # ✅ was 'owner'

    def clean(self):
        cleaned_data = super().clean()
        beneficiary = cleaned_data.get('beneficiary')
        receiver_account_number = cleaned_data.get('receiver_account_number')

        if not beneficiary and not receiver_account_number:
            raise forms.ValidationError("You must either select a beneficiary or enter an account number.")

        return cleaned_data

# Beneficiers
class PaymentForm(forms.Form):
    amount = forms.DecimalField(decimal_places=2, max_digits=10, min_value=1)
    method = forms.ChoiceField(choices=[('UPI', 'UPI'), ('NEFT', 'NEFT'), ('IMPS', 'IMPS')])
    account_number = forms.CharField(required=False)
    ifsc = forms.CharField(required=False) 


class ScheduledTransferForm(forms.ModelForm):
    class Meta:
        model = ScheduledTransfer
        exclude = ['user', 'status', 'created_at']
        widgets = {
            'schedule_datetime': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class UPIRequestForm(forms.Form):
    upi_id = forms.CharField(label="Receiver's UPI ID", max_length=100)
    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=1)
    reason = forms.CharField(max_length=255, required=False)

class UPIPinForm(forms.Form):
    upi_pin = forms.CharField(
        widget=forms.PasswordInput(attrs={'maxlength':6, 'minlength':4}),
        label="Enter your UPI PIN"
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def clean_upi_pin(self):
        pin = self.cleaned_data['upi_pin']
        if self.user:
            profile = self.user.userprofile
            # For demo, simple string compare. Use hashing in prod!
            if profile.upi_pin != pin:
                raise forms.ValidationError("Invalid UPI PIN.")
        return pin
    
class FastagForm(forms.Form):
    bank = forms.ChoiceField(choices=[
        ('HDFC', 'HDFC Bank'),
        ('ICICI', 'ICICI Bank'),
        ('AXIS', 'Axis Bank'),
    ])
    vehicle_number = forms.CharField(max_length=15)

class MetroForm(forms.Form):
    card_provider = forms.ChoiceField(choices=[
        ('AIRTEL_NCMC', 'Airtel NCMC'),
        ('HDFC_NCMC', 'HDFC NCMC'),
        ('PUNE_NCMC', 'Pune MCMC'),
        ('MUFINPAY_NCMC', 'MufinPay NCMC'),
        ('SBI_NCMC', 'SBI NCMC'),
    ])
    mobile_number = forms.CharField(max_length=15)
    last_4_digits = forms.CharField(max_length=4)
    nickname = forms.CharField(max_length=50, required=False)   