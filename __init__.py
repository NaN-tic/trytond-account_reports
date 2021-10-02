# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import common
from . import general_ledger
from . import taxes_by_invoice


def register():
    module = 'account_reports'
    Pool.register(
        common.Account,
        common.Party,
        common.FiscalYear,
        module=module, type_='model')

    general_ledger.register(module)
    taxes_by_invoice.register(module)
