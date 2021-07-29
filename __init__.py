# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from .common import *
# from .general_ledger import *
from . import general_ledger
from . import taxes_by_invoice


def register():
    module = 'account_reports'
    Pool.register(
        Account,
        Party,
        # PrintGeneralLedgerStart,
        FiscalYear,
        module=module, type_='model')
    # Pool.register(
    #     PrintGeneralLedger,
    #     module='account_reports', type_='wizard')
    # Pool.register(
    #     GeneralLedgerReport,
    #     module='account_reports', type_='report')

    general_ledger.register(module)
    taxes_by_invoice.register(module)