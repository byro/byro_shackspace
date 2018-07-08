import csv
import os.path
import re
from datetime import datetime
from decimal import Decimal

from django.dispatch import receiver
from django.utils.timezone import now
from django.conf import settings

from byro.bookkeeping.models import (
    Account, AccountCategory, RealTransaction,
    TransactionChannel, VirtualTransaction,
)
from byro.bookkeeping.signals import (
    derive_virtual_transactions, process_csv_upload,
)
from byro.members.models import Member


@receiver(process_csv_upload)
def process_bank_csv(sender, signal, **kwargs):
    source = sender
    filename = os.path.join(settings.MEDIA_ROOT, source.source_file.name)
    reader = csv.DictReader(open(filename, encoding='iso-8859-1'), delimiter=';', quotechar='"')
    booking_timestamp = now()

    for line in reader:
        if not line:
            continue
        reference = ''
        for key in line.keys():
            if key.startswith('VWZ'):
                reference += line[key] + ' '

        RealTransaction.objects.get_or_create(
            channel=TransactionChannel.BANK,
            value_datetime=datetime.strptime(line.get('Buchungstag'), '%d.%m.%Y'),
            amount=Decimal(line.get('Betrag').replace('.', '').replace(',', '.')),
            purpose=reference,
            originator=line.get('Auftraggeber/Empfänger', '<leer>'),
            importer='shack_bank_csv_importer',
            defaults={'source': source, 'booking_datetime': booking_timestamp, 'data': line},
        )
    return True


@receiver(derive_virtual_transactions)
def match_transaction(sender, signal, **kwargs):
    transaction = sender
    uid, score = reference_parser(reference=transaction.purpose)
    member = None
    try:
        member = Member.objects.get(number=uid)
    except Member.DoesNotExist:
        return

    account = Account.objects.get(account_category=AccountCategory.MEMBER_FEES)
    data = {
        'amount': transaction.amount,
        'destination_account': account,
        'value_datetime': transaction.value_datetime,
        'member': member,
    }
    virtual_transaction = VirtualTransaction.objects.filter(**data).first()
    if virtual_transaction and virtual_transaction.real_transaction != transaction:
        raise Exception('RealTransaction {transaction.id} cannot be matched! There is already a VirtualTransaction ({virtual_transaction.id}) that is too similar. It is matched to RealTransaction {virtual_transaction.real_transaction.id}.'.format(transaction=transaction, virtual_transaction=virtual_transaction))
    if not virtual_transaction:
        data['real_transaction'] = transaction
        virtual_transaction = VirtualTransaction.objects.create(**data)
    return [virtual_transaction]


def reference_parser(reference):
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
