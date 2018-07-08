import csv
import os.path
import re
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.dispatch import receiver
from django.utils.timezone import now

from byro.bookkeeping.models import (
    Account, AccountCategory, Booking, Transaction,
)
from byro.bookkeeping.signals import process_csv_upload, process_transaction
from byro.bookkeeping.special_accounts import SpecialAccounts
from byro.common.models import Configuration
from byro.members.models import Member


@receiver(process_csv_upload)
def process_bank_csv(sender, signal, **kwargs):
    source = sender
    filename = os.path.join(settings.MEDIA_ROOT, source.source_file.name)
    reader = csv.DictReader(open(filename, encoding='iso-8859-1'), delimiter=';', quotechar='"')
    booking_timestamp = now()
    account = SpecialAccounts.bank

    for line in reader:
        if not line:
            continue
        reference = ''
        for key in reader.fieldnames:
            if key.startswith('VWZ'):
                reference += line[key] + ' '

        amount = Decimal(line.get('Betrag').replace('.', '').replace(',', '.'))
        if amount < 0:
            amount = -amount
            booking_type = 'c'
        else:
            booking_type = 'd'

        params = dict(
            memo=reference,
            amount=amount,
            importer='shack_bank_csv_importer',
        )
        data = {
            'csv_line': line,
            'other_party': "{}".format(line.get('Auftraggeber/Empfänger', '<leer>')),
        }

        if booking_type == 'c':
            params['credit_account'] = account
        else:
            params['debit_account'] = account

        booking = account.bookings.filter(
            transaction__value_datetime=datetime.strptime(line.get('Buchungstag'), '%d.%m.%Y'),
            **params
        ).first()

        if not booking:
            t = Transaction.objects.create(
                value_datetime=datetime.strptime(line.get('Buchungstag'), '%d.%m.%Y'),
            )
            Booking.objects.create(
                transaction=t,
                booking_datetime=booking_timestamp,
                source=source,
                data=data,
                **params
            )
    return True


@receiver(process_transaction)
def match_transaction(sender, signal, **kwargs):
    transaction = sender
    if transaction.is_read_only:
        return False
    if transaction.is_balanced:
        return False

    uid, score = reference_parser(reference=transaction.find_memo())
    member = None
    try:
        member = Member.objects.get(number=uid)
    except Member.DoesNotExist:
        return False

    balances = transaction.balances
    data = {
        'amount': abs(balances['debit'] - balances['credit']),
        'account': SpecialAccounts.fees_receivable,
        'member': member,
    }

    if balances['debit'] > balances['credit']:
        transaction.credit(**data)
    else:
        transaction.debit(**data)

    return True


def reference_parser(reference):
    if not reference:
        return (False, 99)
    reference = reference.lower()

    regexes = (
        r'.*mitgliedsbeitrag\s+id\s+(?P<ID>\d{1,4})\s.*',
        r'.*id\s+(?P<ID>\d{1,4})\smitgliedsbeitrag.*',
        # r'.*id\s+(?P<ID>\d{1,4})\s.*',
        r'.*mitgliedsbeitrag.*id\s+(?P<ID>\d{1,4})\s.*',
        r'.*mitgliedsbeitrag\s+(?P<ID>\d{1,4})\s.*',
        r'.*beitrag\s+mitglied\s+(?P<ID>\d{1,4})\s.*',
        r'.*mitgliedsbeitrag.*\s+(?P<ID>\d{1,4})[^\d].*',
        # r'.*id(?P<ID>\d{1,4})\s+zr\d+.*',
        # r'.*id\s+(?P<ID>\d{1,4}),\s+zr\s+\d+.*',
        r'.*mitgliedsbeitrag\s+id[.:-_](?P<ID>\d{1,4})\s.*',
    )

    for score, regex in enumerate(regexes, 1):
        hit = re.match(regex, reference)
        if hit:
            return (int(hit.groupdict().get('ID')), score)

    return (False, 99)
