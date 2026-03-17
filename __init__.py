# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import common
from . import abreviated_journal
from . import general_ledger
from . import taxes_by_invoice
from . import trial_balance
from . import journal


def register():
    module = 'account_reports'
    Pool.register(
        common.Configuration,
        common.Account,
        common.Party,
        common.FiscalYear,
        abreviated_journal.PrintAbreviatedJournalStart,
        general_ledger.PrintGeneralLedgerStart,
        taxes_by_invoice.PrintTaxesByInvoiceAndPeriodStart,
        trial_balance.PrintTrialBalanceStart,
        journal.PrintJournalStart,
        module=module, type_='model')
    Pool.register(
        abreviated_journal.PrintAbreviatedJournal,
        general_ledger.PrintGeneralLedger,
        taxes_by_invoice.PrintTaxesByInvoiceAndPeriod,
        trial_balance.PrintTrialBalance,
        journal.PrintJournal,
        module=module, type_='wizard')
    Pool.register(
        abreviated_journal.AbreviatedJournalReport,
        abreviated_journal.AbreviatedJournalXlsxReport,
        journal.JournalReport,
        journal.JournalXlsxReport,
        general_ledger.GeneralLedgerReport,
        general_ledger.GeneralLedgerXlsxReport,
        taxes_by_invoice.TaxesByInvoiceReport,
        taxes_by_invoice.TaxesByInvoiceXlsxReport,
        trial_balance.TrialBalanceReport,
        trial_balance.TrialBalanceXlsxReport,
        module=module, type_='report')
