from datetime import datetime, timedelta
from itertools import chain
import logging
from urllib import request
import uuid
from django.db.models import Value, CharField
from django.dispatch import receiver
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout,authenticate,login as auth_login
from django.conf import settings
from bank1.utils import update_pending_transactions
from .forms import BeneficiaryForm, DepositForm, FastagForm, MetroForm, PaymentForm, PinUpdateForm, ScheduledTransferForm, TransferForm, UPIForm, UPIPinForm, UPIRequestForm, UserForm
from .models import BankTransferForm, Beneficiary, Notification, Recharge, SavedNumber, ScheduledTransfer, Transaction, UPIRequest, UserAccount, UserProfile
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.core.paginator import Paginator,PageNotAnInteger,EmptyPage
from django.utils.dateparse import parse_date
from django.db.models import Q,Sum
from django.db import models
from django.views.decorators.http import require_GET, require_POST
import requests
from django.db import transaction
from django.utils.safestring import mark_safe
import json


#Admin panel
def admin_panel(request):
    selected = None
    users = []
    pending_users = []

    if request.method == 'POST':
        if 'option' in request.POST:
            selected = request.POST.get('option')

        # Approving a user
        if 'approve_user' in request.POST:
            user_id = request.POST.get('approve_user')
            acc_number = request.POST.get('account_number')
            try:
                user = User.objects.get(id=user_id)
                profile = user.userprofile
                profile.account_number = acc_number
                profile.is_approved = True
                profile.save()
            except:
                pass
            selected = 'add'

        # Deposit Money
        if 'account_number' in request.POST and 'amount' in request.POST and 'approve_user' not in request.POST:
           acc_number = request.POST.get('account_number')
           amount = Decimal(request.POST.get('amount'))
           try:
                profile = UserProfile.objects.get(account_number=acc_number)
                profile.balance += amount
                profile.save()

                # ✅ ADD THIS BLOCK
                Transaction.objects.create(
                    sender=None,
                    receiver=profile.user,
                    amount=amount,
                    method='Deposit',
                    status='completed'
                )

                # Notification
                Notification.objects.create(
                    user=profile.user,
                    message=f"₹{amount} credited to your account."
                )
                messages.success(request, f"✅ ₹{amount} credited to {profile.user.get_full_name()} (Account {acc_number}).")

           except UserProfile.DoesNotExist:
                 messages.error(request, "❌ Account not found.")
                 selected = 'deposit'

    if selected == 'users':
        users = User.objects.filter(userprofile__is_approved=True)

    if selected == 'add':
        pending_users = User.objects.filter(userprofile__is_approved=False)

    return render(request, 'bank1/admin_dashboard.html', {
        'selected': selected,
        'users': users,
        'pending_users': pending_users
    })



def register(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        email = request.POST["email"]
        user = User.objects.create_user(username=username, password=password, email=email)
        messages.success(request, "Registered successfully. Await admin approval.")
        return redirect("login")
    return render(request, "register.html")

def pending_users(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden()
    pending = UserProfile.objects.filter(is_approved=False)
    return render(request, "admin_pending_users.html", {"pending_users": pending})

def approve_user(request, pk):
    profile = UserProfile.objects.get(pk=pk)
    if request.method == "POST":
        acc_no = request.POST["account_number"]
        profile.account_number = acc_no
        profile.is_approved = True
        profile.save()
        messages.success(request, "User approved successfully.")
        return redirect("pending_users")
    return render(request, "approve_user.html", {"profile": profile})

def main(request,pk):
    user = User.objects.get(pk=pk)
    return render(request, 'bank1/home.html')
     


@login_required
def home(request):
    upi_id = None
    try:
        upi_id = request.user.userprofile.upi_id
    except UserProfile.DoesNotExist:
        pass

    users = User.objects.all()
    notifications = request.user.notifications.all().order_by('-created_at')[:5]
     
    pending_requests = UPIRequest.objects.filter(
        requestee=request.user, 
        status='pending'
    )

    return render(request, 'bank1/home.html', {
        'users': users,
        'upi_id': upi_id,
        'notifications': notifications,
        'pending_requests': pending_requests
    })



# def list(request):
#     users = User.objects.all()
#     return render(request,'bank1/user_list.html',{'users': users})

def create(request):
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.save()
            UserProfile.objects.get_or_create(user=user)
            return redirect('login')
    else:
        form = UserForm()
    return render(request, 'bank1/create.html', {'form': form})




def logout_view(request):
    logout(request)
    return redirect('home')

@login_required
def delete(request):
    user = request.user
    logout(request)
    user.delete()
    return redirect('main')

def user_update(request,pk):
    user = get_object_or_404(User, pk = pk)
    if request.method == "POST":
        form = UserForm(request.POST, instance = user)
        if form.is_valid():
            form.save()
            return redirect('user_list')
    else:
        form = UserForm(instance = user)
    return  render(request, 'bank1/create.html',{'form':form})

def deletes(request,pk):
    user =get_object_or_404(User, pk =pk)
    if request.method == "POST":
        user.delete()
        return redirect('list')
    return render(request, 'bank1/deletes.html', {'user':user}) 

def user_login(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(username=username, password=password)
        if user:
            if user.userprofile.is_approved:
                login(request, user)
                return redirect("home")
            else:
                messages.error(request, "Wait for admin approval.")
        else:
            messages.error(request, "Invalid credentials.")
    return render(request, "bank1/login.html")

# Services started

def upi(request):
    return render(request,'bank1/upi.html')


#Upi
@login_required
def set_upi(request):
    # Ensure profile exists
    profile, created = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        upi = request.POST.get("upi_id")
        ifsc = request.POST.get("ifsc_code")
        profile.upi_id = upi
        profile.ifsc_code = ifsc
        profile.save()
        return redirect('home')
    return render(request, 'bank1/set_upi.html')

@login_required
def edit_upi_pin(request):
    if request.method == 'POST':
        new_pin = request.POST.get('new_upi_pin')
        confirm_pin = request.POST.get('confirm_upi_pin')
        if new_pin and new_pin == confirm_pin:
            profile = request.user.userprofile
            profile.upi_pin = new_pin
            profile.save()
            messages.success(request, "UPI PIN updated successfully.")
            return redirect('home')
        else:
            messages.error(request, "Pins do not match.")
    return render(request, 'bank1/edit_pins.html')


@login_required
def edit_tpin(request):
    if request.method == 'POST':
        new_pin = request.POST.get('new_tpin')
        confirm_pin = request.POST.get('confirm_tpin')
        if new_pin and new_pin == confirm_pin:
            profile = request.user.userprofile
            profile.tpin = new_pin
            profile.save()
            messages.success(request, "T-PIN updated successfully.")
            return redirect('profile')
        else:
            messages.error(request, "Pins do not match.")
    return render(request, 'bank1/edit_tpin.html')


@login_required
def transfer(request):
    profile = request.user.userprofile
    if not profile.upi_id:
        return redirect('set_upi')
    
@login_required
def profile_view(request):
    upi_id = None
    if hasattr(request.user, 'userprofile'):
        upi_id = request.user.userprofile.upi_id
    return render(request, 'bank1/home.html', {'upi_id': upi_id}) 

#UPI Transfer
@login_required
def transfer_money(request):
    form = TransferForm()

    if request.method == 'POST':
        form = TransferForm(request.POST)
        if form.is_valid():
            receiver_upi = form.cleaned_data['receiver_upi']
            amount = Decimal(form.cleaned_data['amount'])
            pin = request.POST.get('pin')

            sender_profile = request.user.userprofile

            # Check for missing PIN
            if not sender_profile.upi_pin:
                messages.error(request, "Please set your UPI PIN before making transactions.")
                return redirect('transfer')

            # Validate PIN
            if pin != sender_profile.upi_pin:
                messages.error(request, "Incorrect UPI PIN.")
                return redirect('transfer')

            # Prevent 0 or negative transfers
            if amount <= 0:
                messages.error(request, "Invalid amount.")
                return redirect('transfer')

            # Get receiver
            try:
                receiver_profile = UserProfile.objects.get(upi_id=receiver_upi)
            except UserProfile.DoesNotExist:
                messages.error(request, "No user found with that UPI ID.")
                return redirect('transfer')

            # Prevent sending to self
            if receiver_profile == sender_profile:
                messages.error(request, "You cannot send money to yourself.")
                return redirect('transfer')

            # Check balance
            if sender_profile.balance < amount:
                messages.error(request, "Insufficient balance.")
                return redirect('transfer')

            # Perform transfer
            sender_profile.balance -= amount
            receiver_profile.balance += amount
            sender_profile.save()
            receiver_profile.save()
            
            Transaction.objects.create(
                sender=request.user,
                receiver=receiver_profile.user,
                amount=amount,
                method='UPI',
             )


            # Store transaction info in session
            request.session['payment_success_data'] = {
                'amount': str(amount),
                'receiver_name': receiver_profile.user.get_full_name() or receiver_profile.user.username,
                'sender_name': request.user.get_full_name() or request.user.username,
                'date': timezone.now().strftime("%d %b %Y, %I:%M %p"),
                'method': 'UPI',
            }

            return redirect('payment_success')

    return render(request, 'bank1/transfer.html', {'form': form})


@login_required
def payment_success(request):
    data = request.session.get('payment_success_data')
    if not data:
        return redirect('transfer')

    return render(request, 'bank1/payment_success.html', {'data': data})

def get_upi_name(request):
    upi_id = request.GET.get('receiver_upi', '').strip().lower()
    try:
        profile = UserProfile.objects.get(upi_id__iexact=upi_id)
        return JsonResponse({'name': profile.user.username})
    except UserProfile.DoesNotExist:
        return JsonResponse({'name': None})


#Deposite money by admin
@login_required
def deposit_by_account(request):
    if request.method == 'POST':
        form = DepositForm(request.POST)
        if form.is_valid():
            acc_no = form.cleaned_data['account_number']
            amount = form.cleaned_data['amount']
            try:
                profile = UserProfile.objects.get(account_number=acc_no)
                profile.balance += amount
                profile.save()
                messages.success(request, f"₹{amount} deposited into account {acc_no}")
            except UserProfile.DoesNotExist:
                messages.error(request, "Account number not found.")
    else:
        form = DepositForm()
    return render(request, 'bank1/deposit_account.html', {'form': form})


@login_required
def notifications(request):
    notifications = request.user.notifications.all().order_by('-created_at')
    return render(request, "bank1/notifications.html", {"notifications": notifications})

# NEFT and IMPS
def update_pending_neft_transactions():
    now = timezone.now()
    pending_txns = Transaction.objects.filter(
        method='NEFT',
        status='pending',
        scheduled_time__lte=now
    )
    for tx in pending_txns:
        tx.status = 'completed'
        tx.receiver.userprofile.balance += tx.amount
        tx.receiver.userprofile.save()
        tx.save()

@login_required
def bank_transfer(request):
    update_pending_neft_transactions()
    form = BankTransferForm()

    if request.method == 'POST':
        form = BankTransferForm(request.POST)
        if form.is_valid():
            acc_no = form.cleaned_data['receiver_account_number']
            amount = form.cleaned_data['amount']
            method = form.cleaned_data['method'].upper()
            pin = request.POST.get('pin')

            sender_profile = request.user.userprofile

            # If T-PIN is not set
            if not sender_profile.tpin:
                messages.warning(request, "Please set your T-PIN before making transfers.")
                return redirect('set_tpin')  # Replace with your actual tpin setup URL name

            # Incorrect T-PIN
            if pin != sender_profile.tpin:
                messages.error(request, "Incorrect T-PIN.")
                return redirect('bank_transfer')

            try:
                receiver_profile = UserProfile.objects.get(account_number=acc_no)

                if receiver_profile == sender_profile:
                    messages.error(request, "Cannot transfer to your own account.")
                elif sender_profile.balance < amount:
                    messages.error(request, "Insufficient balance.")
                else:
                    sender_profile.balance -= amount
                    sender_profile.save()

                    if method == 'NEFT':
                        Transaction.objects.create(
                            sender=request.user,
                            receiver=receiver_profile.user,
                            amount=amount,
                            method='NEFT',
                            status='pending',
                            scheduled_time=timezone.now() + timedelta(minutes=30)
                        )
                        messages.success(request, f"NEFT initiated. ₹{amount} will be credited in 30–60 minutes.")
                    else:  # IMPS
                        receiver_profile.balance += amount
                        receiver_profile.save()

                        Transaction.objects.create(
                            sender=request.user,
                            receiver=receiver_profile.user,
                            amount=amount,
                            method='IMPS',
                            status='completed'
                        )
                        messages.success(request, f"IMPS successful. ₹{amount} sent instantly.")

                    return redirect('bank_transfer')

            except UserProfile.DoesNotExist:
                messages.error(request, "Account number not found.")

    # NEFT transactions for display
    neft_transactions = Transaction.objects.filter(
        sender=request.user,
        method='NEFT'
    ).order_by('-scheduled_time')

    return render(request, 'bank1/neft.html', {
        'form': form,
        'neft_transactions': neft_transactions,
    })

def set_tpin(request):
    if request.method == "POST":
        print(request.POST)
        tpin1 = request.POST.get("tpin1")
        tpin2 = request.POST.get("tpin2")

        # Make sure both are provided
        if tpin1 and tpin2:
            if tpin1 == tpin2 and tpin1.isdigit() and len(tpin1) == 4:
                profile = request.user.userprofile
                profile.tpin = tpin1
                profile.save()
                messages.success(request, "T-PIN set successfully.")
            else:
                messages.error(request, "T-PINs do not match or are invalid (must be 4 digits).")
        else:
            messages.error(request, "Both T-PIN fields are required.")
        return redirect('bank_transfer')


def get_account_name(request):
    account_number = request.GET.get('account_number')
    try:
        profile = UserProfile.objects.get(account_number=account_number)
        return JsonResponse({'name': profile.user.get_full_name()}, status=200)
    except UserProfile.DoesNotExist:
        return JsonResponse({'error': 'Account not found'}, status=404)

#Download statement
@login_required
def account_statement(request):
    user = request.user
    
    # 1. Initialize filter parameters from GET request
    from_date_str = request.GET.get('from', '')
    to_date_str = request.GET.get('to', '')
    method = request.GET.get('method', '')
    
    # 2. Get all transactions related to the user, ordered chronologically for balance calculation
    all_transactions = Transaction.objects.filter(
        Q(sender=user) | Q(receiver=user)
    ).order_by('timestamp')

    # 3. Apply date filtering to get the set of transactions for display
    filtered_transactions = all_transactions
    if from_date_str:
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        filtered_transactions = filtered_transactions.filter(timestamp__date__gte=from_date)
    
    if to_date_str:
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        to_date_inclusive = to_date + timedelta(days=1)
        filtered_transactions = filtered_transactions.filter(timestamp__date__lt=to_date_inclusive)

    # 4. Apply method filtering
    if method:
        filtered_transactions = filtered_transactions.filter(method=method)

    # Convert queryset to a list to enable manual running balance calculation
    filtered_transactions_list = list(filtered_transactions)

    # 5. Calculate the **true** opening balance before the filtered period
    opening_balance = 0
    if from_date_str:
        # Get all transactions that occurred strictly before the 'from_date'
        prior_transactions = Transaction.objects.filter(
            Q(sender=user) | Q(receiver=user),
            timestamp__date__lt=from_date
        )
        for txn in prior_transactions:
            if txn.sender == user:
                opening_balance -= txn.amount
            else:
                opening_balance += txn.amount
    else:
        # If no 'from_date' is set, the opening balance is 0
        opening_balance = 0

    # 6. Calculate the running balance for the filtered transactions
    running_balance = opening_balance
    annotated_transactions = []
    for txn in filtered_transactions_list:
        if txn.sender == user:
            running_balance -= txn.amount
        else:
            running_balance += txn.amount
        txn.running_balance = running_balance
        annotated_transactions.append(txn)

    # 7. Reverse the list to display the latest transactions first
    annotated_transactions.reverse()

    # 8. Pagination
    page = request.GET.get('page', 1)
    paginator = Paginator(annotated_transactions, 10)
    try:
        transactions = paginator.page(page)
    except PageNotAnInteger:
        transactions = paginator.page(1)
    except EmptyPage:
        transactions = paginator.page(paginator.num_pages)
    
    # 9. Calculate the closing balance
    closing_balance = running_balance if filtered_transactions_list else opening_balance
    
    # 10. Context for the template
    context = {
        'transactions': transactions,
        'from_date': from_date_str,
        'to_date': to_date_str,
        'method': method,
        'opening_balance': opening_balance,
        'closing_balance': closing_balance,
    }
    return render(request, 'bank1/statement.html', context)


@login_required
def download_statement(request):
    user = request.user
    transactions = Transaction.objects.filter(sender=user) | Transaction.objects.filter(receiver=user)
    transactions = transactions.order_by('-timestamp')

    template_path = 'bank1/statement_pdf.html'
    context = {'transactions': transactions, 'user': user}
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="account_statement.pdf"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response       

# Beneficiaries 
@login_required
def beneficiary_dashboard(request, pk=None):
    # Edit case
    if pk:
        instance = get_object_or_404(Beneficiary, pk=pk, user=request.user)
    else:
        instance = None

    if request.method == "POST":
        form = BeneficiaryForm(request.POST, instance=instance)
        if form.is_valid():
            beneficiary = form.save(commit=False)
            beneficiary.user = request.user

            # Set type based on what is filled
            if form.cleaned_data.get('upi_id'):
                beneficiary.type = 'upi'
            else:
                beneficiary.type = 'bank'

            # 🔍 Try to find a matching user to link
            upi = form.cleaned_data.get('upi_id')
            acc = form.cleaned_data.get('account_number')
            ifsc = form.cleaned_data.get('ifsc')

            from django.contrib.auth.models import User
            matched_user = None

            if upi:
                matched_user = User.objects.filter(userprofile__upi_id=upi).first()
            elif acc and ifsc:
                matched_user = User.objects.filter(
                    userprofile__account_number=acc,
                    userprofile__ifsc=ifsc
                ).first()

            beneficiary.beneficiary_user = matched_user  # may be None
            beneficiary.save()

            messages.success(request, "Beneficiary saved successfully.")
            return redirect('beneficiary_dashboard')
    else:
        form = BeneficiaryForm(instance=instance)

    beneficiaries = Beneficiary.objects.filter(user=request.user)

    return render(request, 'bank1/list_beneficiaries.html', {
        'form': form,
        'beneficiaries': beneficiaries,
        'editing': bool(pk) or request.method == "POST",
    })

@login_required
def edit_beneficiary(request, pk):
    beneficiary = get_object_or_404(Beneficiary, pk=pk, user=request.user)

    if request.method == 'POST':
        if 'delete' in request.POST:
            beneficiary.delete()
            messages.success(request, "Beneficiary deleted.")
            return redirect('beneficiary_dashboard')

        form = BeneficiaryForm(request.POST, instance=beneficiary)
        if form.is_valid():
            beneficiary = form.save(commit=False)
            beneficiary.user = request.user

            # Set type based on filled fields
            if form.cleaned_data.get('upi_id'):
                beneficiary.type = 'upi'
            else:
                beneficiary.type = 'bank'

            # Try to link to a registered user
            upi = form.cleaned_data.get('upi_id')
            acc = form.cleaned_data.get('account_number')
            ifsc = form.cleaned_data.get('ifsc')

            matched_user = None
            if upi:
                matched_user = User.objects.filter(userprofile__upi_id=upi).first()
            elif acc and ifsc:
                matched_user = User.objects.filter(
                    userprofile__account_number=acc,
                    userprofile__ifsc=ifsc
                ).first()

            beneficiary.beneficiary_user = matched_user  # Could be None
            beneficiary.save()

            messages.success(request, "Beneficiary updated successfully.")
            return redirect('beneficiary_dashboard')
        else:
            messages.error(request, "Form is invalid.")
    else:
        form = BeneficiaryForm(instance=beneficiary)

    transactions = Transaction.objects.filter(sender=request.user).order_by('-timestamp')[:5]

    return render(request, 'bank1/edit_overlay.html', {
        'form': form,
        'beneficiary': beneficiary,
        'transactions': transactions,  
    })


@login_required
def pay_beneficiary(request, pk):
    beneficiary = get_object_or_404(Beneficiary, pk=pk)
    sender_profile = request.user.userprofile

    if request.method == 'POST':
        amount_input = request.POST.get('amount')
        method = request.POST.get('method')
        pin = request.POST.get('pin')

        # Input validation
        try:
            amount = Decimal(amount_input)
            if amount <= 0:
                raise ValueError("Invalid amount")
        except (InvalidOperation, ValueError):
            messages.error(request, "Enter a valid amount.")
            return redirect('pay_beneficiary', pk=pk)

        # Validate method
        method = method.upper()
        if method not in ['UPI', 'IMPS', 'NEFT']:
            messages.error(request, "Invalid payment method.")
            return redirect('pay_beneficiary', pk=pk)

        # PIN validation
        if method == 'UPI':
            if not sender_profile.upi_pin:
                messages.error(request, "Please set your UPI PIN first.")
                return redirect('set_upi_pin')
            if pin != sender_profile.upi_pin:
                messages.error(request, "Incorrect UPI PIN.")
                return redirect('pay_beneficiary', pk=pk)
        else:  # IMPS or NEFT
            if not sender_profile.tpin:
                messages.error(request, "Please set your T-PIN first.")
                return redirect('set_tpin')
            if pin != sender_profile.tpin:
                messages.error(request, "Incorrect T-PIN.")
                return redirect('pay_beneficiary', pk=pk)

        # Check balance
        if sender_profile.balance < amount:
            messages.error(request, "Insufficient balance.")
            return redirect('pay_beneficiary', pk=pk)

        # Get receiver profile
        if not hasattr(beneficiary.user, 'userprofile'):
            messages.error(request, "Receiver profile not found.")
            return redirect('pay_beneficiary', pk=pk)

        receiver_profile = beneficiary.user.userprofile

        # Prevent self transfer
        if receiver_profile == sender_profile:
            messages.error(request, "Cannot send money to yourself.")
            return redirect('pay_beneficiary', pk=pk)

        # Deduct from sender only once
        sender_profile.balance -= amount
        sender_profile.save()

        if method == 'NEFT':
            Transaction.objects.create(
                sender=request.user,
                receiver=receiver_profile.user,
                amount=amount,
                method='NEFT',
                status='pending',
                scheduled_time=timezone.now() + timedelta(minutes=30)
            )
            messages.success(request, f"NEFT scheduled. ₹{amount} will be credited in 30–60 minutes.")

        else:
            # IMPS or UPI → Instant transfer
            receiver_profile.balance += amount
            receiver_profile.save()

            Transaction.objects.create(
                sender=request.user,
                receiver=receiver_profile.user,
                amount=amount,
                method=method,
                status='completed'
            )
            messages.success(request, f"{method} successful. ₹{amount} sent instantly.")

        return redirect('payment_success')

    return render(request, 'bank1/pay_beneficiary.html', {'beneficiary': beneficiary})


@login_required
def schedule_transfer(request):
    update_pending_transactions()  # renamed for all methods
    form = BankTransferForm()

    if request.method == 'POST':
        form = BankTransferForm(request.POST)
        if form.is_valid():
            acc_no = form.cleaned_data['receiver_account_number']
            amount = form.cleaned_data['amount']
            method = form.cleaned_data['method'].upper()
            pin = request.POST.get('pin')

            sender_profile = request.user.userprofile

            # If T-PIN is not set
            if not sender_profile.tpin:
                messages.warning(request, "Please set your T-PIN before making transfers.")
                return redirect('set_tpin')

            # Incorrect T-PIN
            if pin != sender_profile.tpin:
                messages.error(request, "Incorrect T-PIN.")
                return redirect('bank_transfer')

            try:
                receiver_profile = UserProfile.objects.get(account_number=acc_no)

                if receiver_profile == sender_profile:
                    messages.error(request, "Cannot transfer to your own account.")
                elif sender_profile.balance < amount:
                    messages.error(request, "Insufficient balance.")
                else:
                    # Deduct from sender immediately
                    sender_profile.balance -= amount
                    sender_profile.save()

                    scheduled_time = timezone.now() + timedelta(minutes=30)

                    # Create ScheduledTransfer
                    ScheduledTransfer.objects.create(
                        user=request.user,
                        receiver_name=receiver_profile.user.get_full_name() or receiver_profile.user.username,
                        amount=amount,
                        payment_method=method,
                        status='Pending',
                        schedule_datetime=scheduled_time
                    )

                    # Create Transaction (pending)
                    Transaction.objects.create(
                        sender=request.user,
                        receiver=receiver_profile.user,
                        amount=amount,
                        method=method,
                        status='pending',
                        scheduled_time=scheduled_time
                    )

                    messages.success(
                        request,
                        f"{method} scheduled to {receiver_profile.user.get_full_name() or receiver_profile.user.username}. "
                        f"₹{amount} will be credited on {scheduled_time.strftime('%Y-%m-%d %H:%M:%S')}."
                    )
                    return redirect('bank_transfer')

            except UserProfile.DoesNotExist:
                messages.error(request, "Account number not found.")

    # Show all pending scheduled transactions
    scheduled_transactions = ScheduledTransfer.objects.filter(
        user=request.user
    ).order_by('-schedule_datetime')

    return render(request, 'bank1/scheduled_transfers.html', {
        'form': form,
        'scheduled_transactions': scheduled_transactions,
    })

def get_beneficiary_name(request):
    upi = request.GET.get('upi')
    account_number = request.GET.get('account_number')

    # Search by UPI
    if upi:
        # Check in real user profiles
        try:
            profile = UserProfile.objects.get(upi_id=upi)
            return JsonResponse({"name": profile.user.get_full_name() or profile.user.username})
        except UserProfile.DoesNotExist:
            pass

        # Check in demo accounts
        try:
            account = UserAccount.objects.get(upi_id=upi)
            return JsonResponse({"name": account.name})
        except UserAccount.DoesNotExist:
            return JsonResponse({"name": None})

    # Search by Account Number
    if account_number:
        try:
            profile = UserProfile.objects.get(account_number=account_number)
            return JsonResponse({"name": profile.user.get_full_name() or profile.user.username})
        except UserProfile.DoesNotExist:
            pass

        try:
            account = UserAccount.objects.get(account_number=account_number)
            return JsonResponse({"name": account.name})
        except UserAccount.DoesNotExist:
            return JsonResponse({"name": None})

    return JsonResponse({"name": None, "error": "No search parameter provided"})


@login_required
def request_money_upi(request):
    if request.method == 'POST':
        form = UPIRequestForm(request.POST)
        if form.is_valid():
            upi_id = form.cleaned_data['upi_id']
            amount = form.cleaned_data['amount']
            reason = form.cleaned_data['reason']
            try:
                receiver_profile = UserProfile.objects.get(upi_id=upi_id)
                UPIRequest.objects.create(
                    requester=request.user,
                    requestee=receiver_profile.user,
                    amount=amount,
                    reason=reason,
                    status='pending'
                )
                messages.success(request, f"Money request of ₹{amount} sent to {receiver_profile.user.username}.")
                return redirect('upi_requests_received')
            except UserProfile.DoesNotExist:
                messages.error(request, "UPI ID not found.")
    else:
        form = UPIRequestForm()
    return render(request, 'bank1/upi_requests_received.html', {'form': form})

@login_required
def upi_requests_received(request):
    pending_requests = UPIRequest.objects.filter(
        requestee=request.user,
        status__in=['pending', 'later']
    ).order_by('-created_at')

    last_request = UPIRequest.objects.filter(
        requester=request.user
    ).order_by('-created_at').first()

    return render(request, 'bank1/upi_requests_received.html', {
        'form': UPIRequestForm(),
        'pending_requests': pending_requests,
        'last_request': last_request,
    })

@login_required
def handle_upi_request(request, request_id, action):
    upi_request = get_object_or_404(UPIRequest, id=request_id, requestee=request.user)

    if action == 'approve':
        if request.method == 'POST':
            form = UPIPinForm(request.POST, user=request.user)
            if form.is_valid():
                sender_profile = upi_request.requestee.userprofile
                receiver_profile = upi_request.requester.userprofile

                if sender_profile.balance < upi_request.amount:
                    messages.error(request, "Insufficient balance to approve request.")
                else:
                    sender_profile.balance -= upi_request.amount
                    receiver_profile.balance += upi_request.amount
                    sender_profile.save()
                    receiver_profile.save()

                    Transaction.objects.create(
                        sender=upi_request.requestee,
                        receiver=upi_request.requester,
                        amount=upi_request.amount,
                        method='UPI',
                        status='completed'
                    )

                    upi_request.status = 'approved'
                    upi_request.save()

                    messages.success(request, f"₹{upi_request.amount} sent to {receiver_profile.user.username} via UPI.")
                return redirect('upi_requests_received')
            else:
                messages.error(request, "Invalid UPI PIN.")
                return redirect('upi_requests_received')

        # GET request - redirect
        return redirect('upi_requests_received')

    elif action == 'decline':
        upi_request.status = 'declined'
        upi_request.save()
        messages.info(request, "Request declined.")
    elif action == 'later':
        upi_request.status = 'later'
        upi_request.save()
        messages.info(request, "You chose to handle this request later.")

    return redirect('upi_requests_received')


# pay EWG bill
MOCK_BILLER_DB = {
    # consumer_number: (name, outstanding_amount)
    "CUST1001": ("Amit Verma", "845.00"),
    "CUST2002": ("Priya Sharma", "1250.50"),
    "CUST3003": ("Ramesh Gupta", "450.00"),
}

@require_GET
def verify_biller(request):
    consumer_no = request.GET.get("consumer_no", "").strip()
    bill_type = request.GET.get("bill_type", "").strip()

    if not consumer_no:
        return JsonResponse({"status": "error", "message": "consumer_no required"}, status=400)

    # If you have a real API configured, call it:
    if getattr(settings, "BILLER_VERIFY_KEY", None):
        try:
            payload = {"consumer_number": consumer_no, "bill_type": bill_type}
            headers = {"Authorization": f"Bearer {settings.BILLER_VERIFY_KEY}"}
            r = requests.post(settings.BILLER_VERIFY_URL, json=payload, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            # adapt mapping depending on provider response
            return JsonResponse({"status": "success", "name": data.get("name"), "amount_due": data.get("amount_due")})
        except Exception as e:
            return JsonResponse({"status": "error", "message": "external API error", "detail": str(e)}, status=500)

    # FALLBACK (mock) for demo/testing:
    if consumer_no in MOCK_BILLER_DB:
        name, amt = MOCK_BILLER_DB[consumer_no]
        return JsonResponse({"status": "success", "name": name, "amount_due": amt})
    return JsonResponse({"status": "error", "message": "consumer number not found"}, status=404)

@login_required
def demo_payment(request):
    if request.method == "POST":
        # Get form data
        consumer_no = request.POST.get("consumer_no", "").strip()
        bill_type = request.POST.get("bill_type", "").strip()
        amount = request.POST.get("amount", "").strip()
        tpin = request.POST.get("tpin", "").strip()

        # Check required fields
        if not (consumer_no and bill_type and amount and tpin):
            return JsonResponse({"status": "error", "message": "Missing fields"}, status=400)

        # Validate amount
        try:
            amount = Decimal(amount)
        except:
            return JsonResponse({"status": "error", "message": "Invalid amount"}, status=400)

        profile = request.user.userprofile

        # Check T-PIN
        if not profile.tpin:
            return JsonResponse({"status": "error", "message": "T-PIN not set"}, status=403)
        if tpin != profile.tpin:
            return JsonResponse({"status": "error", "message": "Invalid T-PIN"}, status=403)

        # Check balance
        if profile.balance < amount:
            return JsonResponse({"status": "error", "message": "Insufficient balance"}, status=400)

        # Deduct balance (sandbox simulation)
        profile.balance -= amount
        profile.save()

        # Save transaction
        tx = Transaction.objects.create(
            sender=request.user,
            receiver=None,
            amount=amount,
            method="Bill Payment",
            tx_type="debit",
            status="completed",
            timestamp=timezone.now()
        )

        # Success response
        return JsonResponse({
            "status": "success",
            "transaction_id": f"DEMO-{tx.id}",
            "message": "Demo payment successful"
        })

    # If GET request → show payment form
    return render(request, "bank1/pay_bill.html")

# Mobile/DTH Recharge
logger = logging.getLogger(__name__)

# ---- Demo operators & plans ----
DEMO_MOBILE_OPERATORS = ["Airtel", "Jio", "Vi", "BSNL"]
DEMO_DTH_OPERATORS = ["TataSky", "DishTV"]

MOBILE_OPERATOR_KEYS = {
    "Airtel": "airtel",
    "Jio": "jio",
    "Vi": "vi",
    "BSNL": "bsnl",
}
DTH_OPERATOR_KEYS = {
    "TataSky": "tatasky",
    "DishTV": "dishtv",
}

DEMO_PLANS = {
    'mobile': {
        'airtel': {
            'Popular': [
                {"amount": 149, "validity": "28D", "description": "1.5GB/day + unlimited calls"},
                {"amount": 249, "validity": "28D", "description": "2GB/day + unlimited calls"},
                {"amount": 249, "validity": "28D", "description": "2GB/day + unlimited calls"},
                {"amount": 249, "validity": "28D", "description": "2GB/day + unlimited calls"},
            ],
            'Truely Unlimited': [
                {"amount": 399, "validity": "56 days", "description": "Unlimited 5G + calls"},
                {"amount": 599, "validity": "84 days", "description": "Unlimited 5G + OTT"},
                {"amount": 399, "validity": "56 days", "description": "Unlimited 5G + calls"},
            ],
            'Data': [
                {"amount": 399, "validity": "56 days", "description": "Unlimited 5G + calls"},
                {"amount": 599, "validity": "84 days", "description": "Unlimited 5G + OTT"},
                {"amount": 399, "validity": "56 days", "description": "Unlimited 5G + calls"},
            ],
            'Talktime': [
                {"amount": 399, "validity": "56 days", "description": "Unlimited 5G + calls"},
                {"amount": 599, "validity": "84 days", "description": "Unlimited 5G + OTT"},
                {"amount": 399, "validity": "56 days", "description": "Unlimited 5G + calls"},
            ],
            'internationl Roaming': [
                {"amount": 399, "validity": "56 days", "description": "Unlimited 5G + calls"},
                {"amount": 599, "validity": "84 days", "description": "Unlimited 5G + OTT"},
                {"amount": 399, "validity": "56 days", "description": "Unlimited 5G + calls"},
            ],
            'Entertainment': [
                {"amount": 399, "validity": "56 days", "description": "Unlimited 5G + calls"},
                {"amount": 599, "validity": "84 days", "description": "Unlimited 5G + OTT"},
                {"amount": 399, "validity": "56 days", "description": "Unlimited 5G + calls"},
            ],
        },
        'jio': {
            'Popular': [
                {"amount": 149, "validity": "28 days", "description": "1GB/day + unlimited calls"},
                {"amount": 299, "validity": "56 days", "description": "1.5GB/day + unlimited calls"},
            ],
            'Unlimited 5G Plans': [
                {"amount": 399, "validity": "56 days", "description": "Unlimited 5G calls"},
                {"amount": 699, "validity": "84 days", "description": "Unlimited 5G + OTT"},
            ],
        },
        'vi': {
            'Popular': [
                {"amount": 199, "validity": "28 days", "description": "1.5GB/day + calls"},
                {"amount": 299, "validity": "28 days", "description": "2GB/day + calls"},
            ],
        },
        'bsnl': {
            'Popular': [
                {"amount": 107, "validity": "28 days", "description": "1GB/day + calls"},
                {"amount": 197, "validity": "56 days", "description": "1.5GB/day + calls"},
            ],
        },
    },
    'dth': {
        'tatasky': {
            'Basic Packs': [
                {"amount": 120, "validity": "1 month", "description": "TataSky basic SD pack"},
                {"amount": 250, "validity": "1 month", "description": "TataSky entertainment pack"},
                {"amount": 250, "validity": "1 month", "description": "TataSky entertainment pack"},
            ],
            'Premium Packs': [
                {"amount": 450, "validity": "2 months", "description": "Movies + sports add-on"},
                {"amount": 999, "validity": "6 months", "description": "Semi-annual HD pack"},
            ],
        },
        'dishtv': {
            'Basic Packs': [
                {"amount": 110, "validity": "1 month", "description": "DishTV base pack (SD)"},
                {"amount": 300, "validity": "1 month", "description": "DishTV HD + entertainment"},
            ],
            'Premium Packs': [
                {"amount": 650, "validity": "3 months", "description": "Quarterly premium"},
            ],
        },
    }
}


@login_required
def recharge_demo(request):
    # --- Read filters from query ---
    plan_type = request.GET.get('type', 'mobile')  # 'mobile' or 'dth'
    operator = request.GET.get('operator')
    selected_category = request.GET.get('category')

    # --- Build operator list and plans map ---
    if plan_type == 'mobile':
        operators = DEMO_MOBILE_OPERATORS
        if operator not in operators:
            operator = operators[0]
        operator_key = MOBILE_OPERATOR_KEYS.get(operator, 'airtel')
        plans_by_category = DEMO_PLANS.get('mobile', {}).get(operator_key, {})
    elif plan_type == 'dth':
        operators = DEMO_DTH_OPERATORS
        if operator not in operators:
            operator = operators[0]
        operator_key = DTH_OPERATOR_KEYS.get(operator, 'tatasky')
        plans_by_category = DEMO_PLANS.get('dth', {}).get(operator_key, {})
    else:
        operators, operator, plans_by_category = [], None, {}

    if not selected_category or selected_category not in plans_by_category:
        selected_category = next(iter(plans_by_category), None)

    plans = plans_by_category.get(selected_category, [])
    categories = list(plans_by_category.keys())

    # --- Handle POST (recharge) ---
    if request.method == 'POST':
        number = request.POST.get('mobile_number') or request.POST.get('dth_number')
        selected_plan_val = request.POST.get('selected_plan')  # "amount|validity|desc"
        pin = request.POST.get('pin')
        post_operator = request.POST.get('operator')
        post_category = request.POST.get('category', '')

        # Basic validation
        if not number or not selected_plan_val or not pin or not post_operator:
            messages.error(request, "Please fill all required fields and enter PIN.")
            return redirect(request.path + f"?type={plan_type}&operator={operator}&category={selected_category or ''}")

        # Parse "amount|validity|desc"
        try:
            amount_str, validity, description = selected_plan_val.split('|', 2)
            amount = Decimal(amount_str)
        except Exception:
            messages.error(request, "Invalid plan selected.")
            return redirect(request.path + f"?type={plan_type}&operator={operator}&category={selected_category or ''}")

        # Load user wallet
        try:
            account = UserProfile.objects.get(user=request.user)
        except UserProfile.DoesNotExist:
            messages.error(request, "User account not found.")
            return redirect(request.path + f"?type={plan_type}&operator={operator}&category={selected_category or ''}")

        # Check PIN
        if not account.check_pin(pin):
            messages.error(request, "Incorrect PIN.")
            return redirect(request.path + f"?type={plan_type}&operator={operator}&category={selected_category or ''}")

        # Check balance
        if account.balance < amount:
            messages.error(request, "Insufficient balance for this recharge.")
            return redirect(request.path + f"?type={plan_type}&operator={operator}&category={selected_category or ''}")

        # Perform atomic wallet deduction + record creation
        try:
            with transaction.atomic():
                account.balance -= amount
                account.save()

                tx = Transaction.objects.create(
                    sender=request.user,
                    amount=amount,
                    method='Recharge',
                    tx_type='debit',
                    status='completed',
                    subscriber=number,
                    operator=post_operator,
                    category=post_category if post_category else None,
                    bill_type='Mobile' if plan_type == 'mobile' else 'DTH'
                )

                Recharge.objects.create(
                    user=request.user,
                    mobile_number=number,
                    operator=post_operator,
                    plan_amount=amount
                )

                SavedNumber.objects.get_or_create(
                    user=request.user,
                    number=number,
                    defaults={'operator': post_operator}
                )

            messages.success(request, f"Recharge successful! ₹{amount} for {number} ({description})")
            return redirect('recharge_success', tx_id=tx.id)

        except Exception as e:
            logger.exception("Recharge transaction failed")
            messages.error(request, f"Recharge failed: {e}")
            return redirect(request.path + f"?type={plan_type}&operator={operator}&category={selected_category or ''}")

    # --- Render form page ---
    my_recharges = SavedNumber.objects.filter(user=request.user)
    context = {
        'plan_type': plan_type,
        'operators': operators,
        'selected_operator': operator,
        'plans': plans,
        'categories': categories,
        'selected_category': selected_category,
        'my_recharges': my_recharges
    }
    return render(request, 'bank1/recharge_form.html', context)


# Dummy API Simulation
FASTAG_BANKS = [
    {"name": "Airtel Payments Bank FASTag", "logo": "banks/airtel.png"},
    {"name": "AU Small Finance Bank FASTag", "logo": "banks/au.png"},
    {"name": "Axis Bank FASTag", "logo": "banks/axis.png"},
    {"name": "Bandhan Bank FASTag", "logo": "banks/bandhan.png"},
    {"name": "Bank of Baroda FASTag", "logo": "banks/bob.png"},
    {"name": "Bank of Maharashtra FASTag", "logo": "banks/bom.png"},
    {"name": "Canara Bank FASTag", "logo": "banks/canara.png"},
    {"name": "Central Bank of India FASTag", "logo": "banks/central.png"},
    {"name": "City Union Bank FASTag", "logo": "banks/cityunion.png"},
    {"name": "Cosmos Bank FASTag", "logo": "banks/cosmos.png"},
    {"name": "Dombivli Nagari Sahakari Bank FASTag", "logo": "banks/dnsb.png"},
    {"name": "Equitas Small Finance Bank FASTag", "logo": "banks/equitas.png"},
    {"name": "Federal Bank FASTag", "logo": "banks/federal.png"},
    {"name": "Fino Payments Bank FASTag", "logo": "banks/fino.png"},
    {"name": "HDFC Bank FASTag", "logo": "banks/hdfc.png"},
    {"name": "ICICI Bank FASTag", "logo": "banks/icici.png"},
    {"name": "IDBI Bank FASTag", "logo": "banks/idbi.png"},
    {"name": "IDFC First Bank FASTag", "logo": "banks/idfc.png"},
    {"name": "Indian Bank FASTag", "logo": "banks/indian.png"},
    {"name": "Indian Overseas Bank FASTag", "logo": "banks/iob.png"},
    {"name": "IndusInd Bank FASTag", "logo": "banks/indusind.png"},
    {"name": "Jammu and Kashmir Bank FASTag", "logo": "banks/jkbank.png"},
    {"name": "Karnataka Bank FASTag", "logo": "banks/karnataka.png"},
    {"name": "Karur Vysya Bank FASTag", "logo": "banks/kvb.png"},
    {"name": "Kotak Mahindra Bank FASTag", "logo": "banks/kotak.png"},
    {"name": "Nagpur Nagarik Sahakari Bank FASTag", "logo": "banks/nnsb.png"},
    {"name": "Punjab National Bank FASTag", "logo": "banks/pnb.png"},
    {"name": "Saraswat Bank FASTag", "logo": "banks/saraswat.png"},
    {"name": "South Indian Bank FASTag", "logo": "banks/southindian.png"},
    {"name": "State Bank of India FASTag", "logo": "banks/sbi.png"},
    {"name": "UCO Bank FASTag", "logo": "banks/uco.png"},
    {"name": "Union Bank of India FASTag", "logo": "banks/union.png"},
    {"name": "Yes Bank FASTag", "logo": "banks/yes.png"},
    {"name": "LivQuik / QuikWallet FASTag", "logo": "banks/liv.png"},
    {"name": "Bajaj Finance FASTag", "logo": "banks/bajaj.png"},
]

# Vehicle types & demo plans (amount in INR)
FASTAG_VEHICLE_TYPES = [
    {"name": "Car/Jeep/Van", "image": "vehicles/car.png"},
    {"name": "LCV", "image": "vehicles/lcv.png"},
    {"name": "Truck/Bus", "image": "vehicles/truck.png"},
    {"name": "Two-Wheeler (Private Road)", "image": "vehicles/bycicle.png"},
    {"name": "Tractor", "image": "vehicles/tractor.png"},
]
FASTAG_PLANS = {
    "Car/Jeep/Van": [
        {"name": "Monthly Pass", "amount": 500, "validity": "30 days", "desc": "Unlimited local plaza crossings"},
        {"name": "Annual Pass",  "amount": 3000, "validity": "200 trips or 1 year", "desc": "Private vehicles only"},
        {"name": "Top-up ₹1000", "amount": 1000, "validity": "Balance top-up", "desc": "Regular usage"}
    ],
    "LCV": [
        {"name": "Monthly Pass", "amount": 900, "validity": "30 days", "desc": "Light commercial vehicle"},
        {"name": "Top-up ₹1500", "amount": 1500, "validity": "Balance top-up", "desc": "Frequent intercity"}
    ],
    "Truck/Bus": [
        {"name": "Monthly Pass", "amount": 1800, "validity": "30 days", "desc": "National corridors"},
        {"name": "Top-up ₹3000", "amount": 3000, "validity": "Balance top-up", "desc": "Fleet use"}
    ],
    "Two-Wheeler (Private Road)": [
        {"name": "Top-up ₹300", "amount": 300, "validity": "Balance top-up", "desc": "Private roads/parking"},
    ],
    "Tractor": [
        {"name": "Top-up ₹600", "amount": 600, "validity": "Balance top-up", "desc": "Rural tolls"},
    ],
}

# Metro NCMC billers (exactly 4 as you asked)
METRO_BILLERS = [
    {"name": "Airtel NCMC", "image": "banks/airtel.png"},
    {"name": "HDFC NCMC (Pune Metro)", "image": "banks/hdfc.png"},
    {"name": "MufinPay NCMC", "image": "banks/mufin.png"},
    {"name": "SBI NCMC", "image": "banks/sbi.png"},
]
METRO_MAX = Decimal("2000.00")  # max ₹2000, no minimum

# --- Fake “fetch” (demo) lookups ---
def demo_fetch_fastag_details(bank: str, vehicle_no: str):
    """Pretend to talk to issuer/biller and return owner & type guess."""
    vehicle_no = vehicle_no.strip().upper()
    if len(vehicle_no) < 6:
        return None
    # Very simple demo rule:
    last_digit = vehicle_no[-1]
    guessed_type = "Car/Jeep/Van" if last_digit.isdigit() and int(last_digit) % 2 == 0 else "LCV"
    return {
        "owner_name": "Demo Owner",
        "issuer": bank,
        "vehicle_no": vehicle_no,
        "vehicle_type": guessed_type,
    }

def demo_validate_ncmc(mobile: str, last4: str):
    """Pretend to validate NCMC details."""
    return len(mobile) == 10 and len(last4) == 4 and last4.isdigit()

# ----------------- VIEWS -----------------

@login_required
def fastag_home(request):
    bank_names = [b["name"] for b in FASTAG_BANKS]

    ctx = {
        "banks": FASTAG_BANKS,
        "vehicle_types": FASTAG_VEHICLE_TYPES,
        "plans_by_type": mark_safe(json.dumps(FASTAG_PLANS)),
    }

    if request.method == "POST":
        step = request.POST.get("step")

        # Step 1: Bank selected
        if step == "1":
            bank = request.POST.get("bank")
            if bank not in bank_names:
                ctx["error"] = "Invalid bank"
            else:
                ctx["selected_bank"] = bank
                ctx["step"] = 2  # move to vehicle details step
            return render(request, "bank1/Ftopup.html", ctx)

        # Step 2: Vehicle details entered
        if step == "2":
            bank = request.POST.get("bank")
            vehicle_type = request.POST.get("vehicle_type")
            vehicle_number = request.POST.get("vehicle_number")

            ctx.update({
                "selected_bank": bank,
                "vehicle_type": vehicle_type,
                "vehicle_number": vehicle_number,
                "step": 2,
            })

            if not vehicle_number:
                ctx["error"] = "Please enter vehicle number"
                return render(request, "bank1/Ftopup.html", ctx)

            if not vehicle_type:
                ctx["error"] = "Please select vehicle type"
                return render(request, "bank1/Ftopup.html", ctx)

            plans = FASTAG_PLANS.get(vehicle_type, [])
            if plans:
                ctx["plans"] = plans
            else:
                ctx["error"] = "No plans available for this vehicle type"
            return render(request, "bank1/Ftopup.html", ctx)

    # Default GET → show only banks step
    ctx["step"] = 1
    return render(request, "bank1/Ftopup.html", ctx)





@login_required
def fastag_verify(request):
    if request.method == "POST":
        pin = request.POST.get("pin")
        profile = request.user.userprofile  # logged-in user's profile

        if pin != profile.upi_pin:
            return render(request, "bank1/Ftopup.html", {"error": "Incorrect UPI PIN"})

        # Create FASTag transaction
        Transaction.objects.create(
            sender=request.user,
            amount=Decimal(request.session["fastag_amount"]),
            method="UPI",
            tx_type="debit",
            status="completed",
            service_type="FASTAG",
            bank_name=request.session["fastag_bank"],
            vehicle_or_card_number=request.session["fastag_vehicle_type"]
        )

        # Cleanup session
        for key in ["fastag_bank", "fastag_vehicle_type", "fastag_amount"]:
            request.session.pop(key, None)

        return redirect("payment_success")

    return render(request, "bank1/Ftopup.html")

@login_required
def metro_home(request):
    if request.method == "POST":
        biller = request.POST.get("biller")
        mobile = request.POST.get("mobile")
        last4 = request.POST.get("last4")
        amount = request.POST.get("amount")

        # validation
        if not biller or not mobile or not last4 or not amount:
            return render(request, "bank1/Mtopup.html", {
                "error": "All fields are required",
                "billers": METRO_BILLERS
            })

        # numeric check
        if not last4.isdigit() or len(last4) != 4:
            return render(request, "bank1/Mtopup.html", {
                "error": "Invalid last 4 digits of NCMC card",
                "billers": METRO_BILLERS
            })

        try:
            amount = Decimal(amount)
        except:
            return render(request, "bank1/Mtopup.html", {
                "error": "Invalid amount",
                "billers": METRO_BILLERS
            })

        if amount > METRO_MAX:
            return render(request, "bank1/Mtopup.html", {
                "error": f"Max recharge is ₹{METRO_MAX}",
                "billers": METRO_BILLERS
            })

        # ✅ save correctly
        request.session["metro_biller"] = biller
        request.session["metro_mobile"] = mobile
        request.session["metro_card_number"] = last4
        request.session["metro_amount"] = str(amount)

        return redirect("metro_verify")

    return render(request, "bank1/Mtopup.html", {"billers": METRO_BILLERS})

@login_required
def metro_verify(request):
    if request.method == "POST":
        pin = request.POST.get("pin")
        profile = request.user.userprofile

        if pin != profile.upi_pin:
            return render(request, "bank1/Mverify.html", {"error": "Incorrect UPI PIN"})

        # create transaction
        Transaction.objects.create(
            sender=request.user,
            amount=Decimal(request.session["metro_amount"]),
            method="UPI",
            tx_type="debit",
            status="completed",
            service_type="METRO",
            bank_name=request.session["metro_biller"],
            vehicle_or_card_number=request.session["metro_card_number"]
        )

        # clear session
        for key in ["metro_biller", "metro_card_number", "metro_amount"]:
            request.session.pop(key, None)

        return redirect("payment_success")

    # show verify page
    return render(request, "bank1/Mverify.html", {
        "biller": request.session.get("metro_biller"),
        "card_number": request.session.get("metro_card_number"),
        "amount": request.session.get("metro_amount"),
    })


def luhn_ok(card_number: str) -> bool:
    s = card_number.replace(" ", "")
    if not s.isdigit() or len(s) < 12 or len(s) > 19:
        return False
    total = 0
    reverse = s[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0

def verify_tpin(user, tpin: str) -> bool:
    profile = getattr(user, "userprofile", None)
    if not profile:
        return False
    stored = getattr(profile, "tpin_plain_demo", None)  # replace with hash in real app
    return stored and tpin == stored

@login_required
def credit_card_bill_payment(request):
    issuers = [
        {"name": "HDFC", "logo": "hdfc.png"},
        {"name": "ICICI", "logo": "icici.png"},
        {"name": "SBI", "logo": "sbi.png"},
        {"name": "Axis", "logo": "axis.png"},
        {"name": "Kotak", "logo": "kotak.png"},
        {"name": "BOB", "logo": "bob.png"},
        {"name": "YES", "logo": "yes.png"},
        {"name": "IndusInd", "logo": "indusind.png"},
    ]

    context = {"issuers": issuers}

    if request.method == "GET":
        return render(request, "bank1/creditcard_payment.html", context)

    # POST
    issuer = (request.POST.get("issuer") or "").strip()
    card_number_raw = (request.POST.get("card_number") or "").strip()
    cardholder = (request.POST.get("cardholder") or "").strip()
    amount_str = (request.POST.get("amount") or "").strip()
    remarks = (request.POST.get("remarks") or "").strip()
    tpin = (request.POST.get("tpin") or "").strip()

    # Basic validation
    if issuer not in issuers:
        messages.error(request, "Please select a valid card issuer.")
        return render(request, "bank1/creditcard_payment.html", context)

    # normalize and Luhn check
    card_number = "".join(ch for ch in card_number_raw if ch.isdigit())
    if not luhn_ok(card_number):
        messages.error(request, "Invalid card number (Luhn check failed).")
        return render(request, "bank1/creditcard_payment.html", context)

    if len(cardholder) < 3:
        messages.error(request, "Enter the cardholder name.")
        return render(request, "payments/creditcard_payment.html", context)

    # amount
    try:
        amount = float(amount_str)
    except ValueError:
        amount = 0.0
    if amount <= 0:
        messages.error(request, "Enter a valid amount greater than 0.")
        return render(request, "payments/creditcard_payment.html", context)

    # T-PIN validation
    if not tpin or len(tpin) != 4 or not tpin.isdigit():
        messages.error(request, "Please enter a valid 4-digit T‑PIN.")
        return render(request, "bank1/creditcard_payment.html", context)
    if not verify_tpin(request.user, tpin):
        messages.error(request, "Incorrect T‑PIN.")
        return render(request, "bank1/creditcard_payment.html", context)

    
    try:
        profile = request.user.userprofile
    except Exception:
        messages.error(request, "User profile not found.")
        return render(request, "bank1/creditcard_payment.html", context)

    if profile.balance < amount:
        messages.error(request, "Insufficient balance.")
        return render(request, "bank1/creditcard_payment.html", context)

    last4 = card_number[-4:]

    with profile.balance.atomic():
        # Deduct balance
        profile.balance -= amount
        profile.save(update_fields=["balance"])

    

        try:
            Transaction.objects.create(
                user=request.user,
                txn_type="Debit",
                method="Account",       
                mode="CC_BILL",         
                amount=amount,
                description=f"Credit Card Bill • {issuer} • **** **** **** {last4}",
                meta={
                    "issuer": issuer,
                    "card_last4": last4,
                    "cardholder": cardholder,
                    "remarks": remarks,
                },
                status="Success",
                created_at=timezone.now(),
            )
        except Exception:
            # If your model doesn't have a JSONField 'meta', you can fold details into description
            pass

    # Success
    request.session["payment_summary"] = {
        "title": "Credit Card Bill Paid",
        "line1": f"Issuer: {issuer}",
        "line2": f"Card ending {last4}",
        "amount": amount,
    }
    messages.success(request, "Credit card bill paid successfully.")
    return redirect("payment_success")  # make sure this URL name exists

BANK_RATES = {
    "SBI": 6.0,
    "HDFC": 6.5,
    "ICICI": 6.2,
    "Axis": 6.7,
}

def fd_rd_calculator(request):
    result = None
    bank = amount = invest_type = None

    if request.method == "POST":
        bank = request.POST.get("bank")
        invest_type = request.POST.get("type")  # FD or RD
        amount = float(request.POST.get("amount", 0))  # For FD → lump sum, for RD → monthly deposit
        rate = BANK_RATES.get(bank, 6.0) / 100

        result = {}
        for years in [5, 10, 15, 20, 25]:
            if invest_type == "FD":
                # FD = Lump sum compounded annually
                principal = amount
                maturity = round(principal * ((1 + rate) ** years), 2)

            else:  # RD = Monthly installments compounded monthly
                months = years * 12
                monthly_rate = rate / 12
                # RD Formula: M = P * [(1 + r)^n - 1] / (1 - (1 + r)^(-1/12))
                # Simplified: M = P * [((1 + r/12)^n - 1) / (1 - (1 + r/12)^(-1))]
                maturity = round(amount * ((1 + monthly_rate) ** months - 1) / (1 - (1 + monthly_rate) ** -1), 2)
                principal = amount * months

            result[years] = {
                "principal": round(principal, 2),
                "maturity": maturity,
                "interest": round(maturity - principal, 2),
            }

    return render(request, "bank1/calculator.html", {
        "result": result,
        "bank": bank,
        "type": invest_type,
        "amount": amount,
    })
