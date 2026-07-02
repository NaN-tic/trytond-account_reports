from trytond.pool import Pool
from . import invoice_payment_dates


def register(module):
    Pool.register(
        invoice_payment_dates.PrintInvoicePaymentDatesStart,
        module=module, type_='model')
    Pool.register(
        invoice_payment_dates.PrintInvoicePaymentDates,
        module=module, type_='wizard')
    Pool.register(
        invoice_payment_dates.InvoicePaymentDatesReport,
        module=module, type_='report')
