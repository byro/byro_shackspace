import json
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytz
from byro_shackspace.models import ShackProfile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.dateparse import parse_date

from byro.bookkeeping.models import (
    Account, AccountCategory, RealTransaction,
    TransactionChannel, VirtualTransaction,
)
from byro.members.models import Member, Membership

TIMEZONE = pytz.timezone('Europe/Berlin')


def localize(date):
    if date:
        return TIMEZONE.localize(datetime.combine(date, time.min))


def _import_sepa(member_data, member):
    sepa_keys = [
        'iban', 'mandate_reason', 'zip_code', 'country',
        'city', 'bic', 'address', 'fullname', 'issue_date',
        'institute', 'mandate_reference',
    ]
    for key in sepa_keys:
        setattr(member.profile_sepa, key, member_data.get(f'sepa__{key}'))
    member.profile_sepa.save()


def _get_main_accounts():
    fee_account, _ = Account.objects.get_or_create(
        account_category=AccountCategory.MEMBER_FEES,
    )
    donation_account, _ = Account.objects.get_or_create(
        account_category=AccountCategory.MEMBER_DONATION,
    )
    liability_account, _ = Account.objects.get_or_create(
        account_category=AccountCategory.LIABILITY,
    )

    return (
        fee_account,
        donation_account,
        liability_account,
    )


def _import_real_transactions(real_transactions):
    ids = []
    for real_transaction in real_transactions:
        if parse_date(real_transaction['booking_date'] or real_transaction['due_date']).year != 2015:
            continue
        rt, _ = RealTransaction.objects.get_or_create(
            channel=TransactionChannel.BANK,
            value_datetime=localize(parse_date(real_transaction['booking_date'] or real_transaction['due_date'])),
            amount=real_transaction['amount'],
            purpose=real_transaction['reference'],
            originator=real_transaction.get('transaction_owner') or 'imported',
            # TODO: reverses?
            importer='shackbureau',
        )
        ids.append(rt.pk)

    return RealTransaction.objects.filter(pk__in=ids)


def _import_inflows(member, virtual_transactions, real_transactions):
    fee_account, donation_account, liability_account = _get_main_accounts()

    inflows = [v for v in virtual_transactions if v['booking_type'] == 'deposit']

    for inflow in inflows:
        if parse_date(inflow['due_date']) is None  or parse_date(inflow['due_date']).year != 2015:
            continue

        account = fee_account if inflow['transaction_type'] == 'membership fee' else donation_account
        possible_real_transaction = real_transactions.filter(
            virtual_transactions__isnull=True,
            amount=abs(Decimal(inflow['amount'])),
            value_datetime=localize(parse_date(inflow['due_date'])),
            purpose=inflow['payment_reference'],
        )

        if possible_real_transaction.count() == 1:
            real_transaction = possible_real_transaction.first()

            VirtualTransaction.objects.get_or_create(
                destination_account=account,
                source_account=None,
                member=member,
                amount=abs(Decimal(inflow['amount'])),
                value_datetime=localize(parse_date(inflow['due_date'])),
                real_transaction=real_transaction,
            )
        elif possible_real_transaction.count() == 0:
            print(f'Found no transaction matching our query: {inflow}')
        elif possible_real_transaction.count() > 1:
            print(f'Found more than one transactions matching our query: {possible_real_transaction.values_list("pk", flat=True)}')


def _import_transactions(member_data, member):
    real_transactions = member_data.get('bank_transactions')
    virtual_transactions = member_data.get('account_transactions')

    real_transactions = _import_real_transactions(real_transactions)

    # _import_fee_claims(member, virtual_transactions)
    _import_inflows(member, virtual_transactions, real_transactions)


def import_member(member_data):
    member, _ = Member.objects.update_or_create(
        number=member_data['number'],
        defaults={
            'name': member_data['name'],
            'address': member_data['address'],
            'email': member_data['email'],
        })
    profile, _ = ShackProfile.objects.update_or_create(
        member=member,
        defaults={
            'has_loeffelhardt_account': member_data.get('has_loeffelhardt_account', False),
            'has_matomat_key': member_data.get('has_matomat_key', False),
            'has_metro_card': member_data.get('has_metro_card', False),
            'has_safe_key': member_data.get('has_safe_key', False),
            'has_selgros_card': member_data.get('has_selgros_card', False),
            'has_shack_iron_key': member_data.get('has_shack_iron_key', False),
            'has_snackomat_key': member_data.get('has_snackomat_key', False),
            'is_keyholder': member_data.get('is_keyholder', False),
            'signed_DSV': member_data.get('signed_DSV', False),
            'ssh_public_key': member_data.get('ssh_public_key', False),
            })
    memberships = member_data.get('memberships')
    last = None
    for membership in sorted(memberships, key=lambda m: m['membership_start']):
        obj, _ = Membership.objects.update_or_create(
            member=member,
            start=parse_date(membership['membership_start']),
            defaults={
                'amount': Decimal(membership['membership_fee_monthly'])*membership['membership_fee_interval'],
                'interval': membership['membership_fee_interval'],
            })
        if last:
            last.end = obj.start - timedelta(days=1)
            last.save(update_fields=['end'])
        last = obj

    if member_data['leave_date']:
        last.end = parse_date(member_data['leave_date'])
        last.save(update_fields=['end'])

    if member_data['payment_type'].lower() == 'sepa':
        _import_sepa(member_data, member)

    for key in ['birth_date', 'nick', 'phone_number']:
        value = member_data.get(f'profile__{key}')
        if not value and key == 'birth_date':
            value = '1970-1-1'
        if value:
            setattr(member.profile_profile, key, value)
    member.profile_profile.save()
    _import_transactions(member_data, member)


def import_members(data):
    for member in data:
        import_member(member)


class Command(BaseCommand):
    help = 'Imports a shackbureau json export'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str)

    @transaction.atomic
    def handle(self, *args, **options):
        path = options.get('path')
        with open(path) as export:
            data = json.load(export)

        import_members(data['members'])
        _import_real_transactions(data['unresolved_bank_transactions'])
