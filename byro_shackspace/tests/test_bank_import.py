import os.path

import pytest
from byro_shackspace.utils import process_bank_csv
from django.core.files.uploadedfile import InMemoryUploadedFile

from byro.bookkeeping.models import RealTransactionSource


@pytest.fixture
def bank_transaction_csv_file():
    filename = os.path.join(os.path.dirname(__file__), 'fixtures/transactions.csv')
    actual_file = open(filename, encoding='iso-8859-1')
    f = InMemoryUploadedFile(
        file=actual_file,
        field_name=None,
        name='transactions.csv',
        content_type='text',
        size=len(actual_file.read()),
        charset='iso-8859-1',
    )
    return RealTransactionSource.objects.create(source_file=f)


@pytest.mark.django_db
def test_bank_import(bank_transaction_csv_file):
    assert bank_transaction_csv_file.bookings.count() == 0
    process_bank_csv(bank_transaction_csv_file, None)
    bank_transaction_csv_file.refresh_from_db()
    assert bank_transaction_csv_file.bookings.count() == 6


@pytest.mark.django_db
def test_bank_import_no_duplicates(bank_transaction_csv_file):
    assert bank_transaction_csv_file.bookings.count() == 0
    process_bank_csv(bank_transaction_csv_file, None)
    bank_transaction_csv_file.refresh_from_db()
    assert bank_transaction_csv_file.bookings.count() == 6
    process_bank_csv(bank_transaction_csv_file, None)
    bank_transaction_csv_file.refresh_from_db()
    assert bank_transaction_csv_file.bookings.count() == 6
