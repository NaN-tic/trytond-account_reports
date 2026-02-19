
# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.modules.company.tests import CompanyTestMixin
from trytond.tests.test_tryton import ModuleTestCase, with_transaction

from decimal import Decimal
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.modules.company.tests import create_company, set_company
from trytond.modules.account.tests import create_chart, get_fiscalyear
from trytond.modules.account_invoice.tests import set_invoice_sequences
from trytond.modules.account_reports.common import TimeoutChecker

class AccountReportsTestCase(CompanyTestMixin, ModuleTestCase):
    'Test AccountReports module'
    module = 'account_reports'

    def setUp(self):
        super(AccountReportsTestCase, self).setUp()

    def assert_report_rendered(self, Report, data, expected_ext):
        result = Report.execute([], data)
        self.assertEqual(result[0], expected_ext)
        self.assertTrue(result[1])

    def assert_xlsx_report_rendered(self, Report, data):
        content = Report.get_content([], data)
        self.assertTrue(content)

    def create_fiscalyear_and_chart(self, company=None, fiscalyear=None,
            chart=True):
        'Test fiscalyear'
        pool = Pool()
        FiscalYear = pool.get('account.fiscalyear')
        if not company:
            company = create_company()
        with set_company(company):
            if chart:
                create_chart(company)
            if not fiscalyear:
                fiscalyear = set_invoice_sequences(get_fiscalyear(company))
                fiscalyear.save()
                FiscalYear.create_period([fiscalyear])
                self.assertEqual(len(fiscalyear.periods), 12)
            return fiscalyear

    def get_journals(self):
        pool = Pool()
        Journal = pool.get('account.journal')
        return dict((j.code, j) for j in Journal.search([]))

    def get_accounts(self, company):
        pool = Pool()
        Account = pool.get('account.account')
        accounts_search = Account.search(['OR',
                ('type.receivable', '=', True),
                ('type.payable', '=', True),
                ('type.revenue', '=', True),
                ('type.expense', '=', True),
                ('company', '=', company.id),
                ])

        accounts = {}
        for kind in ('receivable', 'payable', 'revenue', 'expense' ):
            accounts.update({kind:a for a in accounts_search if a.type and getattr(a.type, kind)})

        root, = Account.search([
                ('parent', '=', None),
                ('company', '=', company.id),
                ], limit=1)
        accounts['root'] = root
        if not accounts['revenue'].code:
            accounts['revenue'].parent = root
            accounts['revenue'].code = '7'
            accounts['revenue'].save()
        if not accounts['receivable'].code:
            accounts['receivable'].parent = root
            accounts['receivable'].code = '43'
            accounts['receivable'].save()
        if not accounts['expense'].code:
            accounts['expense'].parent = root
            accounts['expense'].code = '6'
            accounts['expense'].save()
        if not accounts['payable'].code:
            accounts['payable'].parent = root
            accounts['payable'].code = '41'
            accounts['payable'].save()

        views = Account.search([
                ('name', '=', 'View'),
                ('company', '=', company.id),
                ], limit=1)
        if views:
            view, = views
        else:
            with set_company(company):
                view, = Account.create([{
                            'name': 'View',
                            'code': '1',
                            'parent': root.id,
                            }])
        accounts['view'] = view
        return accounts

    def create_parties(self, company):
        pool = Pool()
        Party = pool.get('party.party')
        with set_company(company):
            return Party.create([{
                        'name': 'customer1',
                        'addresses': [('create', [{}])],
                    }, {
                        'name': 'customer2',
                        'addresses': [('create', [{}])],
                    }, {
                        'name': 'supplier1',
                        'addresses': [('create', [{}])],
                    }, {
                        'name': 'supplier2',
                        'addresses': [('create', [{'active': False}])],
                        'active': False,
                    }])

    def get_parties(self):
        pool = Pool()
        Party = pool.get('party.party')
        customer1, = Party.search([
                ('name', '=', 'customer1'),
                ])
        customer2, = Party.search([
                ('name', '=', 'customer2'),
                ])
        supplier1, = Party.search([
                ('name', '=', 'supplier1'),
                ])
        with Transaction().set_context(active_test=False):
            supplier2, = Party.search([
                    ('name', '=', 'supplier2'),
                    ])
        return customer1, customer2, supplier1, supplier2

    def create_moves(self, company, fiscalyear=None, create_chart=True):
        'Create moves some moves for the test'
        pool = Pool()
        Move = pool.get('account.move')
        fiscalyear = self.create_fiscalyear_and_chart(company, fiscalyear,
            create_chart)
        period = fiscalyear.periods[0]
        last_period = fiscalyear.periods[-1]
        journals = self.get_journals()
        journal_revenue = journals['REV']
        journal_expense = journals['EXP']
        accounts = self.get_accounts(company)
        revenue = accounts['revenue']
        receivable = accounts['receivable']
        expense = accounts['expense']
        payable = accounts['payable']
        # Create some parties
        if create_chart:
            customer1, customer2, supplier1, supplier2 = self.create_parties(
                company)
        else:
            customer1, customer2, supplier1, supplier2 = self.get_parties()
        # Create some moves
        vlist = [
            {
                'company': company.id,
                'period': period.id,
                'journal': journal_revenue.id,
                'date': period.start_date,
                'lines': [
                    ('create', [{
                                'account': revenue.id,
                                'credit': Decimal(100),
                                }, {
                                'party': customer1.id,
                                'account': receivable.id,
                                'debit': Decimal(100),
                                }]),
                    ],
                },
            {
                'company': company.id,
                'period': period.id,
                'journal': journal_revenue.id,
                'date': period.start_date,
                'lines': [
                    ('create', [{
                                'account': revenue.id,
                                'credit': Decimal(200),
                                }, {
                                'party': customer2.id,
                                'account': receivable.id,
                                'debit': Decimal(200),
                                }]),
                    ],
                },
            {
                'company': company.id,
                'period': period.id,
                'journal': journal_expense.id,
                'date': period.start_date,
                'lines': [
                    ('create', [{
                                'account': expense.id,
                                'debit': Decimal(30),
                                }, {
                                'party': supplier1.id,
                                'account': payable.id,
                                'credit': Decimal(30),
                                }]),
                    ],
                },
            {
                'company': company.id,
                'period': period.id,
                'journal': journal_expense.id,
                'date': period.start_date,
                'lines': [
                    ('create', [{
                                'account': expense.id,
                                'debit': Decimal(50),
                                }, {
                                'party': supplier2.id,
                                'account': payable.id,
                                'credit': Decimal(50),
                                }]),
                    ],
                },
            {
                'company': company.id,
                'period': last_period.id,
                'journal': journal_expense.id,
                'date': last_period.end_date,
                'lines': [
                    ('create', [{
                                'account': expense.id,
                                'debit': Decimal(50),
                                }, {
                                'party': supplier2.id,
                                'account': payable.id,
                                'credit': Decimal(50),
                                }]),
                    ],
                },
            {
                'company': company.id,
                'period': last_period.id,
                'journal': journal_revenue.id,
                'date': last_period.end_date,
                'lines': [
                    ('create', [{
                                'account': revenue.id,
                                'credit': Decimal(300),
                                }, {
                                'party': customer2.id,
                                'account': receivable.id,
                                'debit': Decimal(300),
                                }]),
                    ],
                },
            ]
        moves = Move.create(vlist)
        Move.post(moves)
        # Set account inactive
        expense.active = False
        expense.save()
        return fiscalyear

    @with_transaction()
    def test_general_ledger(self):
        'Test General Ledger'
        pool = Pool()
        Account = pool.get('account.account')
        PrintGeneralLedger = pool.get(
            'account_reports.print_general_ledger', type='wizard')
        GeneralLedgerReport = pool.get(
            'account_reports.general_ledger', type='report')
        GeneralLedgerXlsxReport = pool.get(
            'account_reports.general_ledger_xlsx', type='report')
        company = create_company()
        fiscalyear = self.create_moves(company)
        period = fiscalyear.periods[0]
        last_period = fiscalyear.periods[-1]
        session_id, _, _ = PrintGeneralLedger.create()
        print_general_ledger = PrintGeneralLedger(session_id)
        print_general_ledger.start.company = company
        print_general_ledger.start.fiscalyear = fiscalyear
        print_general_ledger.start.start_period = period
        print_general_ledger.start.end_period = last_period
        print_general_ledger.start.start_date = None
        print_general_ledger.start.end_date = None
        print_general_ledger.start.parties = []
        print_general_ledger.start.accounts = []
        print_general_ledger.start.output_format = 'pdf'
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.show_description = True
        print_general_ledger.start.timeout = 30
        checker = TimeoutChecker(print_general_ledger.start.timeout, GeneralLedgerReport.timeout_exception)
        _, data = print_general_ledger.do_print_(None)
        self.assert_report_rendered(GeneralLedgerReport, data, 'pdf')
        data_html = data.copy()
        data_html['output_format'] = 'html'
        self.assert_report_rendered(GeneralLedgerReport, data_html, 'html')
        data_xlsx = data.copy()
        data_xlsx['output_format'] = 'xlsx'
        self.assert_xlsx_report_rendered(GeneralLedgerXlsxReport, data_xlsx)

        # Full general_ledger
        self.assertEqual(data['company'], company.id)
        self.assertEqual(data['fiscalyear'], fiscalyear.id)
        self.assertEqual(data['start_period'], period.id)
        self.assertEqual(data['end_period'], last_period.id)
        self.assertEqual(len(data['accounts']), 0)
        self.assertEqual(len(data['parties']), 0)
        self.assertEqual(data['output_format'], 'pdf')
        records, parameters = GeneralLedgerReport.prepare(data, checker)
        self.assertEqual(len(records), 6)
        self.assertEqual(parameters['start_period'].name, period.name)
        self.assertEqual(parameters['end_period'].name, last_period.name)
        self.assertEqual(parameters['fiscal_year'], fiscalyear.name)
        self.assertEqual(parameters['accounts'], '')
        self.assertEqual(parameters['parties'], '')
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines']])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines']])
        self.assertEqual(credit, debit)
        self.assertEqual(credit, Decimal('730.0'))
        with_party = [line for k, m in records.items() for line in m['lines'] if not line['line'].party]
        self.assertEqual(len(with_party), 6)
        dates = sorted(set([line['line'].date for k, m in records.items() for line in m['lines']]))
        for date, expected_value in zip(dates, [period.start_date,
                    last_period.end_date]):
            self.assertEqual(date, expected_value)

        # Filtered by periods
        session_id, _, _ = PrintGeneralLedger.create()
        print_general_ledger = PrintGeneralLedger(session_id)
        print_general_ledger.start.company = company
        print_general_ledger.start.fiscalyear = fiscalyear
        print_general_ledger.start.start_period = period
        print_general_ledger.start.end_period = period
        print_general_ledger.start.start_date = None
        print_general_ledger.start.end_date = None
        print_general_ledger.start.parties = []
        print_general_ledger.start.accounts = []
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.show_description = True
        print_general_ledger.start.output_format = 'pdf'
        print_general_ledger.start.timeout = 30
        checker = TimeoutChecker(print_general_ledger.start.timeout, GeneralLedgerReport.timeout_exception)
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data, checker)
        self.assertEqual(len(records), 6)
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines']])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines']])
        self.assertEqual(credit, debit)
        self.assertEqual(credit, Decimal('380.0'))
        dates = sorted(set([line['line'].date for k, m in records.items() for line in m['lines']]))
        for date in dates:
            self.assertEqual(date, period.start_date)

        # Filtered by dates
        session_id, _, _ = PrintGeneralLedger.create()
        print_general_ledger = PrintGeneralLedger(session_id)
        print_general_ledger.start.company = company
        print_general_ledger.start.fiscalyear = None
        print_general_ledger.start.start_period = None
        print_general_ledger.start.end_period = None
        print_general_ledger.start.start_date = period.start_date
        print_general_ledger.start.end_date = period.end_date
        print_general_ledger.start.parties = []
        print_general_ledger.start.accounts = []
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.show_description = True
        print_general_ledger.start.output_format = 'pdf'
        print_general_ledger.start.timeout = 30
        checker = TimeoutChecker(print_general_ledger.start.timeout, GeneralLedgerReport.timeout_exception)
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data, checker)
        self.assertEqual(len(records), 6)
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines']])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines']])
        self.assertEqual(credit, debit)
        self.assertEqual(credit, Decimal('380.0'))
        dates = sorted(set([line['line'].date for k, m in records.items() for line in m['lines']]))
        for date in dates:
            self.assertEqual(date, period.start_date)

        # Filtered by accounts
        expenses = Account.search([
                ('type.expense', '=', True),
                ('closed', '!=', True),
                ])
        session_id, _, _ = PrintGeneralLedger.create()
        print_general_ledger = PrintGeneralLedger(session_id)
        print_general_ledger.start.company = company
        print_general_ledger.start.fiscalyear = fiscalyear
        print_general_ledger.start.start_period = period
        print_general_ledger.start.end_period = last_period
        print_general_ledger.start.start_date = None
        print_general_ledger.start.end_date = None
        print_general_ledger.start.parties = []
        print_general_ledger.start.accounts = [e.id for e in expenses]
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.show_description = True
        print_general_ledger.start.output_format = 'pdf'
        print_general_ledger.start.timeout = 30
        checker = TimeoutChecker(print_general_ledger.start.timeout, GeneralLedgerReport.timeout_exception)
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data, checker)
        self.assertEqual(parameters['accounts'], ', '.join([e.code for e in expenses]))
        self.assertEqual(len(records), 1)
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines']])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines']])
        self.assertEqual(credit, Decimal(0))
        self.assertEqual(debit, Decimal('130.0'))

        # Filter by parties
        customer1 = self.get_parties()[0]
        session_id, _, _ = PrintGeneralLedger.create()
        print_general_ledger = PrintGeneralLedger(session_id)
        print_general_ledger.start.company = company
        print_general_ledger.start.fiscalyear = fiscalyear
        print_general_ledger.start.start_period = period
        print_general_ledger.start.end_period = last_period
        print_general_ledger.start.start_date = None
        print_general_ledger.start.end_date = None
        print_general_ledger.start.parties = [customer1.id]
        print_general_ledger.start.accounts = []
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.show_description = True
        print_general_ledger.start.output_format = 'pdf'
        print_general_ledger.start.timeout = 30
        checker = TimeoutChecker(print_general_ledger.start.timeout, GeneralLedgerReport.timeout_exception)
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data, checker)
        self.assertEqual(parameters['parties'], customer1.rec_name)
        self.assertEqual(len(records), 1)
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines']])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines']])
        self.assertEqual(credit, Decimal(0))
        self.assertEqual(debit, Decimal('100.0'))
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines'] if m['party'] == ''])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines'] if m['party'] == ''])
        self.assertEqual(credit, Decimal(0))
        self.assertEqual(debit, Decimal(0))
        parties = [line for k, m in records.items() for line in m['lines'] if not line['line'].party]
        self.assertEqual(len(parties), 0)

        # Filter by parties and accounts
        receivables = Account.search([
                ('type.receivable', '=', True),
                ('closed', '!=', True),
                ])
        session_id, _, _ = PrintGeneralLedger.create()
        print_general_ledger = PrintGeneralLedger(session_id)
        print_general_ledger.start.company = company
        print_general_ledger.start.fiscalyear = fiscalyear
        print_general_ledger.start.start_period = period
        print_general_ledger.start.end_period = last_period
        print_general_ledger.start.start_date = None
        print_general_ledger.start.end_date = None
        print_general_ledger.start.parties = [customer1.id]
        print_general_ledger.start.accounts = [r.id for r in receivables]
        print_general_ledger.start.output_format = 'pdf'
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.show_description = True
        print_general_ledger.start.timeout = 30
        checker = TimeoutChecker(print_general_ledger.start.timeout, GeneralLedgerReport.timeout_exception)
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data, checker)
        self.assertEqual(parameters['parties'], customer1.rec_name)
        self.assertEqual(parameters['accounts'], ', '.join([r.code for r in receivables]))
        self.assertEqual(len(records), 1)
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines']])
        self.assertEqual(True, all([line for k, m in records.items() for line in m['lines'] if line['line'].party]))

    @with_transaction()
    def test_trial_balance_render(self):
        'Test Trial Balance rendering'
        pool = Pool()
        PrintTrialBalance = pool.get(
            'account_reports.print_trial_balance', type='wizard')
        TrialBalanceReport = pool.get(
            'account_reports.trial_balance', type='report')
        TrialBalanceXlsxReport = pool.get(
            'account_reports.trial_balance_xlsx', type='report')
        company = create_company()
        fiscalyear = self.create_moves(company)
        period = fiscalyear.periods[0]
        last_period = fiscalyear.periods[-1]

        session_id, _, _ = PrintTrialBalance.create()
        print_trial_balance = PrintTrialBalance(session_id)
        print_trial_balance.start.company = company
        print_trial_balance.start.fiscalyear = fiscalyear
        print_trial_balance.start.start_period = period
        print_trial_balance.start.end_period = last_period
        print_trial_balance.start.comparison_fiscalyear = None
        print_trial_balance.start.comparison_start_period = None
        print_trial_balance.start.comparison_end_period = None
        print_trial_balance.start.show_digits = 0
        print_trial_balance.start.only_moves = False
        print_trial_balance.start.moves_or_initial = False
        print_trial_balance.start.hide_split_parties = False
        print_trial_balance.start.split_parties = False
        print_trial_balance.start.add_initial_balance = False
        print_trial_balance.start.accounts = []
        print_trial_balance.start.parties = []
        print_trial_balance.start.output_format = 'pdf'
        print_trial_balance.start.timeout = 30

        _, data = print_trial_balance.do_print_(None)
        self.assert_report_rendered(TrialBalanceReport, data, 'pdf')
        data_html = data.copy()
        data_html['output_format'] = 'html'
        self.assert_report_rendered(TrialBalanceReport, data_html, 'html')
        data_xlsx = data.copy()
        data_xlsx['output_format'] = 'xlsx'
        self.assert_xlsx_report_rendered(TrialBalanceXlsxReport, data_xlsx)

    @with_transaction()
    def test_taxes_by_invoice_render(self):
        'Test Taxes by Invoice rendering'
        pool = Pool()
        PrintTaxesByInvoice = pool.get(
            'account_reports.print_taxes_by_invoice', type='wizard')
        TaxesByInvoiceReport = pool.get(
            'account_reports.taxes_by_invoice', type='report')
        TaxesByInvoiceXlsxReport = pool.get(
            'account_reports.taxes_by_invoice_xlsx', type='report')
        company = create_company()
        fiscalyear = self.create_moves(company)

        session_id, _, _ = PrintTaxesByInvoice.create()
        print_taxes = PrintTaxesByInvoice(session_id)
        print_taxes.start.company = company
        print_taxes.start.fiscalyear = fiscalyear
        print_taxes.start.start_date = None
        print_taxes.start.end_date = None
        print_taxes.start.periods = []
        print_taxes.start.parties = []
        print_taxes.start.excluded_parties = []
        print_taxes.start.partner_type = 'customers'
        print_taxes.start.grouping = 'base_tax_code'
        print_taxes.start.tax_type = 'all'
        print_taxes.start.totals_only = False
        print_taxes.start.taxes = []
        print_taxes.start.output_format = 'pdf'
        print_taxes.start.timeout = 30

        _, data = print_taxes.do_print_(None)
        self.assert_report_rendered(TaxesByInvoiceReport, data, 'pdf')
        data_html = data.copy()
        data_html['output_format'] = 'html'
        self.assert_report_rendered(TaxesByInvoiceReport, data_html, 'html')
        data_xlsx = data.copy()
        data_xlsx['output_format'] = 'xlsx'
        self.assert_xlsx_report_rendered(TaxesByInvoiceXlsxReport, data_xlsx)

    @with_transaction()
    def test_journal(self):
        'Test journal'
        pool = Pool()
        PrintJournal = pool.get('account_reports.print_journal',
            type='wizard')
        JournalReport = pool.get('account_reports.journal',
            type='report')
        company = create_company()
        fiscalyear = self.create_moves(company)
        period = fiscalyear.periods[0]
        last_period = fiscalyear.periods[-1]
        journals = self.get_journals()
        journal_revenue = journals['REV']
        journal_expense = journals['EXP']
        session_id, _, _ = PrintJournal.create()
        print_journal = PrintJournal(session_id)
        print_journal.start.company = company
        print_journal.start.fiscalyear = fiscalyear
        print_journal.start.start_period = period
        print_journal.start.end_period = last_period
        print_journal.start.journals = []
        print_journal.start.output_format = 'html'
        print_journal.start.open_close_account_moves = False
        print_journal.start.open_move_description = 'Open'
        print_journal.start.close_move_description = 'Close'

        _, data = print_journal.do_print_(None)
        print_journal.start.output_format = 'pdf'
        _, data_pdf = print_journal.do_print_(None)
        self.assert_report_rendered(JournalReport, data_pdf, 'pdf')
        # Full Journal
        self.assertEqual(data['company'], company.id)
        self.assertEqual(data['fiscalyear'], fiscalyear.id)
        self.assertEqual(data['start_period'], period.id)
        self.assertEqual(data['end_period'], last_period.id)
        self.assertEqual(len(data['journals']), 0)
        self.assertEqual(data['output_format'], 'html')
        records, parameters = JournalReport.prepare(data)
        self.assertEqual(len(records), 12)
        self.assertEqual(parameters['start_period'], period.name)
        self.assertEqual(parameters['end_period'], last_period.name)
        self.assertEqual(parameters['fiscal_year'], fiscalyear.name)
        self.assertEqual(parameters['journals'], '')
        credit = sum([m['credit'] for m in records])
        debit = sum([m['debit'] for m in records])
        self.assertEqual(credit, debit)
        self.assertEqual(credit, Decimal('730.0'))
        with_party = [m for m in records if m['party_name']]
        self.assertEqual(len(with_party), 6)
        # Filtering periods
        session_id, _, _ = PrintJournal.create()
        print_journal = PrintJournal(session_id)
        print_journal.start.company = company
        print_journal.start.fiscalyear = fiscalyear
        print_journal.start.start_period = period
        print_journal.start.end_period = period
        print_journal.start.journals = []
        print_journal.start.output_format = 'html'
        print_journal.start.open_close_account_moves = False
        print_journal.start.open_move_description = 'Open'
        print_journal.start.close_move_description = 'Close'

        _, data = print_journal.do_print_(None)
        records, parameters = JournalReport.prepare(data)
        self.assertEqual(len(records), 8)
        credit = sum([m['credit'] for m in records])
        debit = sum([m['debit'] for m in records])
        self.assertEqual(credit, debit)
        self.assertEqual(credit, Decimal('380.0'))
        # Filtering journals
        journals = self.get_journals()
        journal_revenue = journals['REV']
        journal_expense = journals['EXP']
        session_id, _, _ = PrintJournal.create()
        print_journal = PrintJournal(session_id)
        print_journal.start.company = company
        print_journal.start.fiscalyear = fiscalyear
        print_journal.start.start_period = period
        print_journal.start.end_period = period
        print_journal.start.journals = [journal_revenue, journal_expense]
        print_journal.start.output_format = 'html'
        print_journal.start.open_close_account_moves = False
        print_journal.start.open_move_description = 'Open'
        print_journal.start.close_move_description = 'Close'
        _, data = print_journal.do_print_(None)
        records, parameters = JournalReport.prepare(data)
        self.assertNotEqual(parameters['journals'], '')
        self.assertEqual(len(records), 8)
        credit = sum([m['credit'] for m in records])
        debit = sum([m['debit'] for m in records])
        self.assertEqual(credit, debit)
        self.assertEqual(credit, Decimal('380.0'))


del ModuleTestCase
