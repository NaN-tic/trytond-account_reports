from trytond.pool import Pool
from . import trial_balance


def register(module):
    Pool.register(
        trial_balance.PrintTrialBalanceStart,
        module=module, type_='model')
    Pool.register(
        trial_balance.PrintTrialBalance,
        module=module, type_='wizard')
    Pool.register(
        trial_balance.TrialBalanceReport,
        module=module, type_='report')
