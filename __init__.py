# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import common
from . import abreviated_journal
from . import general_ledger
from . import journal
from . import open_move_lines
from . import taxes_by_invoice
from . import trial_balance
from .invoice_payment_dates.invoice_payment_dates import (
    InvoicePaymentDatesReport,
    PrintInvoicePaymentDates,
    PrintInvoicePaymentDatesStart,
    )


def register():
    module = 'account_reports'
    Pool.register(
        common.Configuration,
        common.Account,
        common.Party,
        common.FiscalYear,
        abreviated_journal.PrintAbreviatedJournalStart,
        general_ledger.PrintGeneralLedgerStart,
        journal.PrintJournalStart,
        open_move_lines.PrintOpenMoveLinesStart,
        taxes_by_invoice.PrintTaxesByInvoiceAndPeriodStart,
        trial_balance.PrintTrialBalanceStart,
        PrintInvoicePaymentDatesStart,
        module=module, type_='model')
    Pool.register(
        abreviated_journal.PrintAbreviatedJournal,
        general_ledger.PrintGeneralLedger,
        journal.PrintJournal,
        open_move_lines.PrintOpenMoveLines,
        taxes_by_invoice.PrintTaxesByInvoiceAndPeriod,
        trial_balance.PrintTrialBalance,
        PrintInvoicePaymentDates,
        module=module, type_='wizard')
    Pool.register(
        abreviated_journal.AbreviatedJournalReport,
        abreviated_journal.AbreviatedJournalXlsxReport,
        general_ledger.GeneralLedgerReport,
        general_ledger.GeneralLedgerXlsxReport,
        journal.JournalReport,
        journal.JournalXlsxReport,
        open_move_lines.OpenMoveLinesReport,
        open_move_lines.OpenMoveLinesXlsxReport,
        taxes_by_invoice.TaxesByInvoiceReport,
        taxes_by_invoice.TaxesByInvoiceXlsxReport,
        trial_balance.TrialBalanceReport,
        trial_balance.TrialBalanceXlsxReport,
        InvoicePaymentDatesReport,
        module=module, type_='report')
