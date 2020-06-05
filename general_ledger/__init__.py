from trytond.pool import Pool
from . import general_ledger


def register(module):
    Pool.register(
        general_ledger.PrintGeneralLedgerStart,
        module=module, type_='model')
    Pool.register(
        general_ledger.PrintGeneralLedger,
        module=module, type_='wizard')
    Pool.register(
        general_ledger.GeneralLedgerReport,
        module=module, type_='report')
