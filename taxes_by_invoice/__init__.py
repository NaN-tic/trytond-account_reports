from trytond.pool import Pool
from . import taxes_by_invoice


def register(module):
    Pool.register(
        taxes_by_invoice.PrintTaxesByInvoiceAndPeriodStart,
        module=module, type_='model')
    Pool.register(
        taxes_by_invoice.PrintTaxesByInvoiceAndPeriod,
        module=module, type_='wizard')
    Pool.register(
        taxes_by_invoice.TaxesByInvoiceReport,
        module=module, type_='report')