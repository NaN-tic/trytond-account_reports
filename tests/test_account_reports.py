# This file is part of the account_reports module for Tryton.
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal
from dateutil.relativedelta import relativedelta
import unittest
from trytond.pool import Pool
import trytond.tests.test_tryton
from trytond.tests.test_tryton import ModuleTestCase, with_transaction
from trytond.transaction import Transaction
from trytond.modules.company.tests import create_company, set_company
from trytond.modules.account.tests import create_chart, get_fiscalyear
from trytond.modules.account_invoice.tests import set_invoice_sequences


class AccountReportsTestCase(ModuleTestCase):
    'Test Account Reports module'
    module = 'account_reports'

    def setUp(self):
        super(AccountReportsTestCase, self).setUp()

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
                ])
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

        # TODO
        cash, = Account.search([
        #        ('kind', '=', 'other'),
                ('name', '=', 'Main Cash'),
                ('company', '=', company.id),
                ])
        accounts['cash'] = cash
        tax, = Account.search([
        #        ('kind', '=', 'other'),
                ('name', '=', 'Main Tax'),
                ('company', '=', company.id),
                ])
        accounts['tax'] = tax
        views = Account.search([
                ('name', '=', 'View'),
                ('company', '=', company.id),
                ])
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

    # @with_transaction()
    # def test_journal(self):
    #     'Test journal'
    #     pool = Pool()
    #     PrintJournal = pool.get('account_reports.print_journal',
    #         type='wizard')
    #     JournalReport = pool.get('account_reports.journal',
    #         type='report')
    #     company = create_company()
    #     fiscalyear = self.create_moves(company)
    #     period = fiscalyear.periods[0]
    #     last_period = fiscalyear.periods[-1]
    #     journals = self.get_journals()
    #     journal_revenue = journals['REV']
    #     journal_expense = journals['EXP']
    #     session_id, _, _ = PrintJournal.create()
    #     print_journal = PrintJournal(session_id)
    #     print_journal.start.company = company
    #     print_journal.start.fiscalyear = fiscalyear
    #     print_journal.start.start_period = period
    #     print_journal.start.end_period = last_period
    #     print_journal.start.journals = []
    #     print_journal.start.output_format = 'pdf'
    #     print_journal.start.open_close_account_moves = False
    #     print_journal.start.open_move_description = 'Open'
    #     print_journal.start.close_move_description = 'Close'
    #
    #     _, data = print_journal.do_print_(None)
    #     # Full Journall
    #     self.assertEqual(data['company'], company.id)
    #     self.assertEqual(data['fiscalyear'], fiscalyear.id)
    #     self.assertEqual(data['start_period'], period.id)
    #     self.assertEqual(data['end_period'], last_period.id)
    #     self.assertEqual(len(data['journals']), 0)
    #     self.assertEqual(data['output_format'], 'pdf')
    #     records, parameters = JournalReport.prepare(data)
    #     self.assertEqual(len(records), 12)
    #     self.assertEqual(parameters['start_period'], period.name)
    #     self.assertEqual(parameters['end_period'], last_period.name)
    #     self.assertEqual(parameters['fiscal_year'], fiscalyear.name)
    #     self.assertEqual(parameters['journals'], '')
    #     credit = sum([m['credit'] for m in records])
    #     debit = sum([m['debit'] for m in records])
    #     self.assertEqual(credit, debit)
    #     self.assertEqual(credit, Decimal('730.0'))
    #     with_party = [m for m in records if m['party_name']]
    #     self.assertEqual(len(with_party), 6)
    #     # Filtering periods
    #     session_id, _, _ = PrintJournal.create()
    #     print_journal = PrintJournal(session_id)
    #     print_journal.start.company = company
    #     print_journal.start.fiscalyear = fiscalyear
    #     print_journal.start.start_period = period
    #     print_journal.start.end_period = period
    #     print_journal.start.journals = []
    #     print_journal.start.output_format = 'pdf'
    #     print_journal.start.open_close_account_moves = False
    #     print_journal.start.open_move_description = 'Open'
    #     print_journal.start.close_move_description = 'Close'
    #
    #     _, data = print_journal.do_print_(None)
    #     records, parameters = JournalReport.prepare(data)
    #     self.assertEqual(len(records), 8)
    #     credit = sum([m['credit'] for m in records])
    #     debit = sum([m['debit'] for m in records])
    #     self.assertEqual(credit, debit)
    #     self.assertEqual(credit, Decimal('380.0'))
    #     # Filtering journals
    #     journals = self.get_journals()
    #     journal_revenue = journals['REV']
    #     journal_expense = journals['EXP']
    #     session_id, _, _ = PrintJournal.create()
    #     print_journal = PrintJournal(session_id)
    #     print_journal.start.company = company
    #     print_journal.start.fiscalyear = fiscalyear
    #     print_journal.start.start_period = period
    #     print_journal.start.end_period = period
    #     print_journal.start.journals = [journal_revenue, journal_expense]
    #     print_journal.start.output_format = 'pdf'
    #     print_journal.start.open_close_account_moves = False
    #     print_journal.start.open_move_description = 'Open'
    #     print_journal.start.close_move_description = 'Close'
    #     _, data = print_journal.do_print_(None)
    #     records, parameters = JournalReport.prepare(data)
    #     self.assertNotEqual(parameters['journals'], '')
    #     self.assertEqual(len(records), 8)
    #     credit = sum([m['credit'] for m in records])
    #     debit = sum([m['debit'] for m in records])
    #     self.assertEqual(credit, debit)
    #     self.assertEqual(credit, Decimal('380.0'))

    # @with_transaction()
    # def test_abreviated_journal(self):
    #     'Test journal'
    #     pool = Pool()
    #     PrintAbreviatedJournal = pool.get(
    #         'account_reports.print_abreviated_journal', type='wizard')
    #     AbreviatedJournalReport = pool.get(
    #         'account_reports.abreviated_journal', type='report')
    #     company = create_company()
    #     fiscalyear = self.create_moves(company)
    #     period = fiscalyear.periods[0]
    #     session_id, _, _ = PrintAbreviatedJournal.create()
    #     print_abreviated_journal = PrintAbreviatedJournal(
    #         session_id)
    #     print_abreviated_journal.start.company = company
    #     print_abreviated_journal.start.fiscalyear = fiscalyear
    #     print_abreviated_journal.start.display_account = 'bal_all'
    #     print_abreviated_journal.start.level = 1
    #     print_abreviated_journal.start.output_format = 'pdf'
    #     _, data = print_abreviated_journal.do_print_(None)
    #     self.assertEqual(data['company'], company.id)
    #     self.assertEqual(data['fiscalyear'], fiscalyear.id)
    #     self.assertEqual(data['display_account'], 'bal_all')
    #     self.assertEqual(data['level'], 1)
    #     self.assertEqual(data['output_format'], 'pdf')
    #     records, parameters = AbreviatedJournalReport.prepare(data)
    #     self.assertEqual(len(records), 3 * 12)
    #     self.assertEqual(parameters['fiscal_year'], fiscalyear.name)
    #     credit = sum([m['credit'] for m in records])
    #     debit = sum([m['debit'] for m in records])
    #     self.assertEqual(debit, 130.0)
    #     self.assertEqual(credit, 600.0)
    #     credit = sum([m['credit'] for m in records
    #             if m['month'] == period.rec_name])
    #     debit = sum([m['debit'] for m in records
    #             if m['month'] == period.rec_name])
    #     self.assertEqual(debit, 80.0)
    #     self.assertEqual(credit, 300.0)
    #     # Only with moves
    #     print_abreviated_journal = PrintAbreviatedJournal(
    #         session_id)
    #     print_abreviated_journal.start.company = company
    #     print_abreviated_journal.start.fiscalyear = fiscalyear
    #     print_abreviated_journal.start.display_account = 'bal_movement'
    #     print_abreviated_journal.start.level = 1
    #     print_abreviated_journal.start.output_format = 'pdf'
    #     _, data = print_abreviated_journal.do_print_(None)
    #     records, parameters = AbreviatedJournalReport.prepare(data)
    #     self.assertEqual(len(records), 4)
    #     # With two digits
    #     session_id, _, _ = PrintAbreviatedJournal.create()
    #     print_abreviated_journal = PrintAbreviatedJournal(
    #         session_id)
    #     print_abreviated_journal.start.company = company
    #     print_abreviated_journal.start.fiscalyear = fiscalyear
    #     print_abreviated_journal.start.display_account = 'bal_all'
    #     print_abreviated_journal.start.level = 2
    #     print_abreviated_journal.start.output_format = 'pdf'
    #     _, data = print_abreviated_journal.do_print_(None)
    #     records, parameters = AbreviatedJournalReport.prepare(data)
    #     self.assertEqual(len(records), 4 * 12)
    #     # With two digits and movements
    #     session_id, _, _ = PrintAbreviatedJournal.create()
    #     print_abreviated_journal = PrintAbreviatedJournal(
    #         session_id)
    #     print_abreviated_journal.start.company = company
    #     print_abreviated_journal.start.fiscalyear = fiscalyear
    #     print_abreviated_journal.start.display_account = 'bal_movement'
    #     print_abreviated_journal.start.level = 2
    #     print_abreviated_journal.start.output_format = 'pdf'
    #     _, data = print_abreviated_journal.do_print_(None)
    #     records, parameters = AbreviatedJournalReport.prepare(data)
    #     self.assertEqual(len(records), 4 * 2)

    @with_transaction()
    def test_general_ledger(self):
        'Test General Ledger'
        pool = Pool()
        Account = pool.get('account.account')
        PrintGeneralLedger = pool.get(
            'account_reports.print_general_ledger', type='wizard')
        GeneralLedgerReport = pool.get(
            'account_reports.general_ledger', type='report')
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
        print_general_ledger.start.parties = []
        print_general_ledger.start.accounts = []
        print_general_ledger.start.output_format = 'pdf'
        print_general_ledger.start.all_accounts = False
        _, data = print_general_ledger.do_print_(None)

        # Full general_ledger
        self.assertEqual(data['company'], company.id)
        self.assertEqual(data['fiscalyear'], fiscalyear.id)
        self.assertEqual(data['start_period'], period.id)
        self.assertEqual(data['end_period'], last_period.id)
        self.assertEqual(len(data['accounts']), 0)
        self.assertEqual(len(data['parties']), 0)
        self.assertEqual(data['output_format'], 'pdf')
        records, parameters = GeneralLedgerReport.prepare(data)
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

        # Filtered by periods
        session_id, _, _ = PrintGeneralLedger.create()
        print_general_ledger = PrintGeneralLedger(session_id)
        print_general_ledger.start.company = company
        print_general_ledger.start.fiscalyear = fiscalyear
        print_general_ledger.start.start_period = period
        print_general_ledger.start.end_period = period
        print_general_ledger.start.parties = []
        print_general_ledger.start.accounts = []
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.output_format = 'pdf'
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data)
        self.assertEqual(len(records), 6)
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines']])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines']])
        self.assertEqual(credit, debit)
        self.assertEqual(credit, Decimal('380.0'))

        # Filtered by accounts
        expense, = Account.search([
                ('type.expense', '=', True),
                ])
        session_id, _, _ = PrintGeneralLedger.create()
        print_general_ledger = PrintGeneralLedger(session_id)
        print_general_ledger.start.company = company
        print_general_ledger.start.fiscalyear = fiscalyear
        print_general_ledger.start.start_period = period
        print_general_ledger.start.end_period = last_period
        print_general_ledger.start.parties = []
        print_general_ledger.start.accounts = [expense.id]
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.output_format = 'pdf'
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data)
        self.assertEqual(parameters['accounts'], expense.code)
        self.assertEqual(len(records), 1)
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines']])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines']])
        self.assertEqual(credit, Decimal('0.0'))
        self.assertEqual(debit, Decimal('130.0'))

        # Filter by parties
        customer1 = self.get_parties()[0]
        session_id, _, _ = PrintGeneralLedger.create()
        print_general_ledger = PrintGeneralLedger(session_id)
        print_general_ledger.start.company = company
        print_general_ledger.start.fiscalyear = fiscalyear
        print_general_ledger.start.start_period = period
        print_general_ledger.start.end_period = last_period
        print_general_ledger.start.parties = [customer1.id]
        print_general_ledger.start.accounts = []
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.output_format = 'pdf'
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data)
        self.assertEqual(parameters['parties'], customer1.rec_name)
        self.assertEqual(len(records), 1)
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines']])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines']])
        self.assertEqual(credit, Decimal('0.0'))
        self.assertEqual(debit, Decimal('100.0'))
        parties = [line for k, m in records.items() for line in m['lines'] if not line['line'].party]
        self.assertEqual(len(parties), 0)

        # Filter by parties and accounts
        receivable, = Account.search([
                ('type.receivable', '=', True),
                ])
        session_id, _, _ = PrintGeneralLedger.create()
        print_general_ledger = PrintGeneralLedger(session_id)
        print_general_ledger.start.company = company
        print_general_ledger.start.fiscalyear = fiscalyear
        print_general_ledger.start.start_period = period
        print_general_ledger.start.end_period = last_period
        print_general_ledger.start.parties = [customer1.id]
        print_general_ledger.start.accounts = [receivable.id]
        print_general_ledger.start.output_format = 'pdf'
        print_general_ledger.start.all_accounts = False
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data)
        self.assertEqual(parameters['parties'], customer1.rec_name)
        self.assertEqual(parameters['accounts'], receivable.code)
        self.assertEqual(len(records), 1)
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines']])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines']])
        self.assertEqual(credit, Decimal('0.0'))
        self.assertEqual(debit, Decimal('100.0'))
        self.assertEqual(True, all([line for k, m in records.items() for line in m['lines'] if line['line'].party]))

        # Check balance of full general_ledger
        print_general_ledger = PrintGeneralLedger(session_id)
        print_general_ledger.start.company = company
        print_general_ledger.start.fiscalyear = fiscalyear
        print_general_ledger.start.start_period = None
        print_general_ledger.start.end_period = None
        print_general_ledger.start.parties = []
        print_general_ledger.start.accounts = []
        print_general_ledger.start.output_format = 'pdf'
        print_general_ledger.start.all_accounts = False
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data)
        self.assertEqual(len(records), 6)
        # balance = sum([line['balance'] for k, m in records.items() for line in m['lines']])
        results = [(m['total_balance'], m['account']) for k, m in records.items()]
        balances = [
            (Decimal('-30'), 'Main Payable'),
            (Decimal('-100'), 'Main Payable'),
            (Decimal('100'), 'Main Receivable'),
            (Decimal('500'), 'Main Receivable'),
            (Decimal('130'), 'Main Expense'),
            (Decimal('-600'), 'Main Revenue'),
            ]
        for result, balance in zip(results, balances):
            self.assertEqual(result, balance)

    # @with_transaction()
    # def test_trial_balance(self):
    #     'Test Trial Balance'
    #     pool = Pool()
    #     PrintTrialBalance = pool.get(
    #         'account_reports.print_trial_balance', type='wizard')
    #     TrialBalanceReport = pool.get(
    #         'account_reports.trial_balance', type='report')
    #     company = create_company()
    #     fiscalyear = self.create_moves(company)
    #     period = fiscalyear.periods[0]
    #     last_period = fiscalyear.periods[-1]
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = None
    #     print_trial_balance.start.with_move_only = False
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = False
    #     print_trial_balance.start.add_initial_balance = False
    #     print_trial_balance.start.comparison_fiscalyear = None
    #     print_trial_balance.start.comparison_start_period = None
    #     print_trial_balance.start.comparison_end_period = None
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # Full trial_balance
    #     self.assertEqual(data['company'], company.id)
    #     self.assertEqual(data['fiscalyear'], fiscalyear.id)
    #     self.assertEqual(data['start_period'], period.id)
    #     self.assertEqual(data['end_period'], last_period.id)
    #     self.assertEqual(len(data['accounts']), 0)
    #     self.assertEqual(len(data['parties']), 0)
    #     self.assertEqual(data['output_format'], 'pdf')
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 7)
    #     self.assertEqual(parameters['start_period'], period.name)
    #     self.assertEqual(parameters['end_period'], last_period.name)
    #     self.assertEqual(parameters['fiscalyear'], fiscalyear.name)
    #     self.assertEqual(parameters['accounts'], '')
    #     self.assertEqual(parameters['parties'], '')
    #     self.assertEqual(parameters['digits'], '')
    #     self.assertEqual(parameters['with_moves_only'], '')
    #     self.assertEqual(parameters['split_parties'], '')
    #     self.assertEqual(parameters['SECOND_BALANCE'], False)
    #     self.assertEqual(parameters['comparison_fiscalyear'], '')
    #     self.assertEqual(parameters['comparison_start_period'], '')
    #     self.assertEqual(parameters['comparison_end_period'], '')
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records])
    #     self.assertEqual(credit, debit)
    #     self.assertEqual(credit, Decimal('730.0'))
    #     self.assertEqual(balance, Decimal('0.0'))
    #     # Comparision data
    #     credit = sum([Decimal(str(m['credit'])) for m in records])
    #     debit = sum([Decimal(str(m['debit'])) for m in records])
    #     balance = sum([Decimal(str(m['balance'])) for m in records])
    #     self.assertEqual(credit, debit)
    #     self.assertEqual(credit, balance)
    #     self.assertEqual(balance, Decimal('0.0'))
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = 1
    #     print_trial_balance.start.with_move_only = False
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = False
    #     print_trial_balance.start.add_initial_balance = False
    #     print_trial_balance.start.comparison_fiscalyear = None
    #     print_trial_balance.start.comparison_start_period = None
    #     print_trial_balance.start.comparison_end_period = None
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # With 1 digit
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 3)
    #     self.assertEqual(parameters['digits'], 1)
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records])
    #     self.assertEqual(credit, Decimal('600.0'))
    #     self.assertEqual(debit, Decimal('130.0'))
    #     self.assertEqual(balance, Decimal('-470.0'))
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = 2
    #     print_trial_balance.start.with_move_only = False
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = False
    #     print_trial_balance.start.add_initial_balance = False
    #     print_trial_balance.start.comparison_fiscalyear = None
    #     print_trial_balance.start.comparison_start_period = None
    #     print_trial_balance.start.comparison_end_period = None
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # With 2 digits
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 2)
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records])
    #     self.assertEqual(credit, Decimal('130.0'))
    #     self.assertEqual(debit, Decimal('600.0'))
    #     self.assertEqual(balance, Decimal('470.0'))
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = 1
    #     print_trial_balance.start.with_move_only = True
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = False
    #     print_trial_balance.start.add_initial_balance = False
    #     print_trial_balance.start.comparison_fiscalyear = None
    #     print_trial_balance.start.comparison_start_period = None
    #     print_trial_balance.start.comparison_end_period = None
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # With 1 digits and only with moves
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 2)
    #     self.assertEqual(parameters['with_moves_only'], True)
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records])
    #     self.assertEqual(debit, Decimal('130.0'))
    #     self.assertEqual(credit, Decimal('600.0'))
    #     self.assertEqual(balance, Decimal('-470.0'))
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = 2
    #     print_trial_balance.start.with_move_only = False
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = True
    #     print_trial_balance.start.add_initial_balance = False
    #     print_trial_balance.start.comparison_fiscalyear = None
    #     print_trial_balance.start.comparison_start_period = None
    #     print_trial_balance.start.comparison_end_period = None
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # With 2 digits and splited with parties
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 4)
    #     self.assertEqual(parameters['split_parties'], True)
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records])
    #     self.assertEqual(credit, Decimal('130.0'))
    #     self.assertEqual(debit, Decimal('600.0'))
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = None
    #     print_trial_balance.start.with_move_only = False
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = True
    #     print_trial_balance.start.add_initial_balance = False
    #     print_trial_balance.start.comparison_fiscalyear = None
    #     print_trial_balance.start.comparison_start_period = None
    #     print_trial_balance.start.comparison_end_period = None
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # Full splited with parties
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 9)
    #     self.assertEqual(parameters['split_parties'], True)
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records])
    #     self.assertEqual(credit, Decimal('730.0'))
    #     self.assertEqual(debit, Decimal('730.0'))
    #     customer1 = self.get_parties()[0]
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = [customer1.id]
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = None
    #     print_trial_balance.start.with_move_only = False
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = True
    #     print_trial_balance.start.add_initial_balance = False
    #     print_trial_balance.start.comparison_fiscalyear = None
    #     print_trial_balance.start.comparison_start_period = None
    #     print_trial_balance.start.comparison_end_period = None
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # Customer 1 and splited with parties
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 7)
    #     self.assertEqual(parameters['parties'], customer1.rec_name)
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records
    #             if m['name'] == customer1.rec_name])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records
    #             if m['name'] == customer1.rec_name])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records
    #             if m['name'] == customer1.rec_name])
    #     self.assertEqual(credit, Decimal('0.0'))
    #     self.assertEqual(debit, Decimal('100.0'))
    #     self.assertEqual(balance, Decimal('100.0'))
    #     revenue = self.get_accounts(company)['revenue']
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = [revenue.id]
    #     print_trial_balance.start.show_digits = None
    #     print_trial_balance.start.with_move_only = False
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = False
    #     print_trial_balance.start.add_initial_balance = False
    #     print_trial_balance.start.comparison_fiscalyear = None
    #     print_trial_balance.start.comparison_start_period = None
    #     print_trial_balance.start.comparison_end_period = None
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # Only revenue account
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 1)
    #     self.assertEqual(parameters['accounts'], revenue.code)
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records])
    #     self.assertEqual(credit, Decimal('600.0'))
    #     self.assertEqual(debit, Decimal('0.0'))
    #     self.assertEqual(balance, Decimal('-600.0'))
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = last_period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = None
    #     print_trial_balance.start.with_move_only = True
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = False
    #     print_trial_balance.start.add_initial_balance = True
    #     print_trial_balance.start.comparison_fiscalyear = fiscalyear
    #     print_trial_balance.start.comparison_start_period = last_period
    #     print_trial_balance.start.comparison_end_period = last_period
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # With moves and add initial balance
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 4)
    #     initial = sum([Decimal(str(m['period_initial_balance']))
    #             for m in records])
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records])
    #     self.assertEqual(credit, Decimal('350.0'))
    #     self.assertEqual(debit, Decimal('350.0'))
    #     results = {
    #         '41': (Decimal('-80'), Decimal('-130')),
    #         '43': (Decimal('300'), Decimal('600')),
    #         '6': (Decimal('80'), Decimal('130')),
    #         '7': (Decimal('-300'), Decimal('-600')),
    #         }
    #     for r in records:
    #         initial, balance = results[r['code']]
    #         self.assertEqual(r['period_initial_balance'], initial)
    #         self.assertEqual(r['period_balance'], balance)
    #         self.assertEqual(r['initial_balance'], initial)
    #         self.assertEqual(r['balance'], balance)
    #     for initial, balance in [(m['period_initial_balance'],
    #                 m['period_balance']) for m in records]:
    #         self.assertNotEqual(Decimal(str(initial)), Decimal('0.0'))
    #         self.assertNotEqual(Decimal(str(balance)), Decimal('0.0'))
    #         self.assertNotEqual(Decimal(str(balance)),
    #             Decimal(str(initial)))
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = last_period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = None
    #     print_trial_balance.start.with_move_only = True
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = True
    #     print_trial_balance.start.add_initial_balance = True
    #     print_trial_balance.start.comparison_fiscalyear = fiscalyear
    #     print_trial_balance.start.comparison_start_period = last_period
    #     print_trial_balance.start.comparison_end_period = last_period
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # With moves, split parties and add initial balance
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 4)
    #     results = {
    #         '41': (Decimal('-50'), Decimal('-100')),
    #         '43': (Decimal('200'), Decimal('500')),
    #         '6': (Decimal('80'), Decimal('130')),
    #         '7': (Decimal('-300'), Decimal('-600')),
    #         }
    #     for r in records:
    #         initial, balance = results[r['code']]
    #         self.assertEqual(r['period_initial_balance'], initial)
    #         self.assertEqual(r['period_balance'], balance)
    #         self.assertEqual(r['initial_balance'], initial)
    #         self.assertEqual(r['balance'], balance)
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = last_period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = None
    #     print_trial_balance.start.with_move_only = True
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = False
    #     print_trial_balance.start.add_initial_balance = False
    #     print_trial_balance.start.comparison_fiscalyear = fiscalyear
    #     print_trial_balance.start.comparison_start_period = period
    #     print_trial_balance.start.comparison_end_period = period
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # With moves and comparing period
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(parameters['comparison_fiscalyear'],
    #         fiscalyear.rec_name)
    #     self.assertEqual(parameters['comparison_start_period'],
    #         period.rec_name)
    #     self.assertEqual(parameters['comparison_end_period'],
    #         period.rec_name)
    #     self.assertEqual(len(records), 4)
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records])
    #     self.assertEqual(credit, debit)
    #     self.assertEqual(debit, Decimal('350.0'))
    #     self.assertEqual(balance, Decimal('0.0'))
    #     # Comparision data
    #     credit = sum([Decimal(str(m['credit'])) for m in records])
    #     debit = sum([Decimal(str(m['debit'])) for m in records])
    #     balance = sum([Decimal(str(m['balance'])) for m in records])
    #     self.assertEqual(credit, debit)
    #     self.assertEqual(debit, Decimal('380.0'))
    #     self.assertEqual(balance, Decimal('0.0'))
    #     receivable = self.get_accounts(company)['receivable']
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = last_period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = [receivable.id]
    #     print_trial_balance.start.show_digits = None
    #     print_trial_balance.start.with_move_only = True
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = True
    #     print_trial_balance.start.add_initial_balance = False
    #     print_trial_balance.start.comparison_fiscalyear = None
    #     print_trial_balance.start.comparison_start_period = None
    #     print_trial_balance.start.comparison_end_period = None
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # Splited by parties but move doesn't have any party defined
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 1)
    #     self.assertEqual(parameters['accounts'], receivable.code)
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records])
    #     self.assertEqual(debit, Decimal('300.0'))
    #     self.assertEqual(credit, Decimal('0.0'))
    #     self.assertEqual(balance, Decimal('300.0'))
    #     # Inactive customers should always apear on trial balance
    #     customer1.active = False
    #     customer1.save()
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = None
    #     print_trial_balance.start.with_move_only = False
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = True
    #     print_trial_balance.start.add_initial_balance = False
    #     print_trial_balance.start.comparison_fiscalyear = None
    #     print_trial_balance.start.comparison_start_period = None
    #     print_trial_balance.start.comparison_end_period = None
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     # Full splited with parties
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 9)
    #     self.assertEqual(parameters['split_parties'], True)
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records])
    #     self.assertEqual(credit, Decimal('730.0'))
    #     self.assertEqual(debit, Decimal('730.0'))
    #     # If we do not indicate periods we get the full definition
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = fiscalyear
    #     print_trial_balance.start.start_period = None
    #     print_trial_balance.start.end_period = None
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = None
    #     print_trial_balance.start.with_move_only = False
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = False
    #     print_trial_balance.start.add_initial_balance = False
    #     print_trial_balance.start.comparison_fiscalyear = fiscalyear
    #     print_trial_balance.start.comparison_start_period = None
    #     print_trial_balance.start.comparison_end_period = None
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #     self.assertEqual(data['start_period'], period.id)
    #     self.assertEqual(data['end_period'], last_period.id)
    #     self.assertEqual(data['comparison_start_period'], period.id)
    #     self.assertEqual(data['comparison_end_period'], last_period.id)
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     self.assertEqual(len(records), 7)
    #     self.assertEqual(parameters['start_period'], period.name)
    #     self.assertEqual(parameters['end_period'], last_period.name)
    #     self.assertEqual(parameters['fiscalyear'], fiscalyear.name)
    #     credit = sum([Decimal(str(m['period_credit'])) for m in records])
    #     debit = sum([Decimal(str(m['period_debit'])) for m in records])
    #     balance = sum([Decimal(str(m['period_balance'])) for m in records])
    #     self.assertEqual(credit, debit)
    #     self.assertEqual(credit, Decimal('730.0'))
    #     self.assertEqual(balance, Decimal('0.0'))
    #     credit = sum([Decimal(str(m['credit'])) for m in records])
    #     debit = sum([Decimal(str(m['debit'])) for m in records])
    #     balance = sum([Decimal(str(m['balance'])) for m in records])
    #     self.assertEqual(credit, debit)
    #     self.assertEqual(credit, Decimal('730.0'))
    #     self.assertEqual(balance, Decimal('0.0'))

    # @with_transaction()
    # def test_taxes_by_invoice(self):
    #     'Test taxes by invoice'
    #     pool = Pool()
    #     PaymentTerm = pool.get('account.invoice.payment_term')
    #     TaxCode = pool.get('account.tax.code')
    #     Tax = pool.get('account.tax')
    #     Invoice = pool.get('account.invoice')
    #     InvoiceTax = pool.get('account.invoice.tax')
    #     PrintTaxesByInvoice = pool.get(
    #         'account_reports.print_taxes_by_invoice', type='wizard')
    #     TaxesByInvoiceReport = pool.get(
    #         'account_reports.taxes_by_invoice', type='report')
    #     company = create_company()
    #     fiscalyear = self.create_moves(company)
    #     period = fiscalyear.periods[0]
    #     last_period = fiscalyear.periods[-1]
    #     accounts = self.get_accounts(company)
    #     revenue = accounts['revenue']
    #     receivable = accounts['receivable']
    #     expense = accounts['expense']
    #     payable = accounts['payable']
    #     account_tax = accounts['tax']
    #     journals = self.get_journals()
    #     journal_revenue = journals['REV']
    #     journal_expense = journals['EXP']
    #
    #     term, = PaymentTerm.create([{
    #                 'name': 'Payment term',
    #                 'lines': [
    #                     ('create', [{
    #                                 'type': 'remainder',
    #                                 'relativedeltas': [
    #                                     ('create', [{
    #                                                 'sequence': 0,
    #                                                 'days': 0,
    #                                                 'months': 0,
    #                                                 'weeks': 0,
    #                                                 }])],
    #                                 }])],
    #                 }])
    #
    #     with set_company(company):
    #         tx = TaxCode.create([{
    #                         'name': 'invoice base',
    #                         },
    #                     {
    #                         'name': 'invoice tax',
    #                         },
    #                     {
    #                         'name': 'credit note base',
    #                         },
    #                     {
    #                         'name': 'credit note tax',
    #                     }])
    #         invoice_base, invoice_tax, credit_note_base, credit_note_tax = tx
    #         tax1, tax2 = Tax.create([{
    #                     'name': 'Tax 1',
    #                     'description': 'Tax 1',
    #                     'type': 'percentage',
    #                     'rate': Decimal('.10'),
    #                     'invoice_account': account_tax.id,
    #                     'credit_note_account': account_tax.id,
    #                     },
    #                 {
    #                     'name': 'Tax 2',
    #                     'description': 'Tax 2',
    #                     'type': 'percentage',
    #                     'rate': Decimal('.04'),
    #                     'invoice_account': account_tax.id,
    #                     'credit_note_account': account_tax.id,
    #                     }])
    #         customer, _, supplier, supplier2 = self.get_parties()
    #         customer_address, = customer.addresses
    #         supplier_address, = supplier.addresses
    #         invoices = Invoice.create([{
    #                     'number': '1',
    #                     'invoice_date': period.start_date,
    #                     'company': company.id,
    #                     'type': 'out',
    #                     'currency': company.currency.id,
    #                     'party': customer.id,
    #                     'invoice_address': customer_address.id,
    #                     'journal': journal_revenue.id,
    #                     'account': receivable.id,
    #                     'payment_term': term.id,
    #                     'lines': [
    #                         ('create', [{
    #                                     'invoice_type': 'out',
    #                                     'type': 'line',
    #                                     'sequence': 0,
    #                                     'description': 'invoice_line',
    #                                     'account': revenue.id,
    #                                     'quantity': 1,
    #                                     'unit_price': Decimal('50.0'),
    #                                     'taxes': [
    #                                         ('add', [tax1.id, tax2.id])],
    #                                     }])],
    #                     },
    #                 {
    #                     'number': '2',
    #                     'invoice_date': period.start_date,
    #                     'company': company.id,
    #                     'type': 'in',
    #                     'currency': company.currency.id,
    #                     'party': supplier.id,
    #                     'invoice_address': supplier_address.id,
    #                     'journal': journal_expense.id,
    #                     'account': payable.id,
    #                     'payment_term': term.id,
    #                     'lines': [
    #                         ('create', [{
    #                                     'invoice_type': 'in',
    #                                     'type': 'line',
    #                                     'sequence': 0,
    #                                     'description': 'invoice_line',
    #                                     'account': expense.id,
    #                                     'quantity': 1,
    #                                     'unit_price': Decimal('20.0'),
    #                                     'taxes': [
    #                                         ('add', [tax1.id, tax2.id])],
    #                                     }])],
    #                     },
    #                 ])
    #         Invoice.post(invoices)
    #     invoice1, invoice2 = invoices
    #     session_id, _, _ = PrintTaxesByInvoice.create()
    #     print_taxes_by_invoice = PrintTaxesByInvoice(session_id)
    #     print_taxes_by_invoice.start.company = company
    #     print_taxes_by_invoice.start.fiscalyear = fiscalyear
    #     print_taxes_by_invoice.start.periods = []
    #     print_taxes_by_invoice.start.parties = []
    #     print_taxes_by_invoice.start.partner_type = 'customers'
    #     print_taxes_by_invoice.start.grouping = 'invoice'
    #     print_taxes_by_invoice.start.totals_only = False
    #     print_taxes_by_invoice.start.start_date = None
    #     print_taxes_by_invoice.start.end_date = None
    #     print_taxes_by_invoice.start.tax_type = 'all'
    #     print_taxes_by_invoice.start.output_format = 'pdf'
    #     _, data = print_taxes_by_invoice.do_print_(None)
    #     # Customer data
    #     self.assertEqual(data['company'], company.id)
    #     self.assertEqual(data['fiscalyear'], fiscalyear.id)
    #     self.assertEqual(data['partner_type'], 'customers')
    #     self.assertEqual(data['grouping'], 'invoice')
    #     self.assertEqual(data['totals_only'], False)
    #     self.assertEqual(len(data['periods']), 0)
    #     self.assertEqual(len(data['parties']), 0)
    #     self.assertEqual(data['output_format'], 'pdf')
    #     ids, parameters = TaxesByInvoiceReport.prepare(data)
    #     records = InvoiceTax.browse(ids)
    #     self.assertEqual(len(records), 2)
    #     self.assertEqual(parameters['fiscal_year'], fiscalyear.name)
    #     self.assertEqual(parameters['parties'], '')
    #     self.assertEqual(parameters['periods'], '')
    #     self.assertEqual(parameters['TOTALS_ONLY'], False)
    #     base = sum([m.company_base for m in records])
    #     tax = sum([m.company_amount for m in records])
    #     self.assertEqual(base, Decimal('100.0'))
    #     self.assertEqual(tax, Decimal('7.0'))
    #     for tax in records:
    #         self.assertEqual(tax.invoice, invoice1)
    #     session_id, _, _ = PrintTaxesByInvoice.create()
    #     print_taxes_by_invoice = PrintTaxesByInvoice(session_id)
    #     print_taxes_by_invoice.start.company = company
    #     print_taxes_by_invoice.start.fiscalyear = fiscalyear
    #     print_taxes_by_invoice.start.periods = []
    #     print_taxes_by_invoice.start.parties = []
    #     print_taxes_by_invoice.start.partner_type = 'suppliers'
    #     print_taxes_by_invoice.start.grouping = 'invoice'
    #     print_taxes_by_invoice.start.totals_only = False
    #     print_taxes_by_invoice.start.start_date = None
    #     print_taxes_by_invoice.start.end_date = None
    #     print_taxes_by_invoice.start.tax_type = 'all'
    #     print_taxes_by_invoice.start.output_format = 'pdf'
    #     _, data = print_taxes_by_invoice.do_print_(None)
    #     # Supplier data
    #     ids, parameters = TaxesByInvoiceReport.prepare(data)
    #     records = InvoiceTax.browse(ids)
    #     self.assertEqual(len(records), 2)
    #     base = sum([m.company_base for m in records])
    #     tax = sum([m.company_amount for m in records])
    #     self.assertEqual(base, Decimal('40.0'))
    #     self.assertEqual(tax, Decimal('2.8'))
    #     for tax in records:
    #         self.assertEqual(tax.invoice, invoice2)
    #     session_id, _, _ = PrintTaxesByInvoice.create()
    #     print_taxes_by_invoice = PrintTaxesByInvoice(session_id)
    #     print_taxes_by_invoice.start.company = company
    #     print_taxes_by_invoice.start.fiscalyear = fiscalyear
    #     print_taxes_by_invoice.start.periods = []
    #     print_taxes_by_invoice.start.parties = [supplier2.id]
    #     print_taxes_by_invoice.start.partner_type = 'suppliers'
    #     print_taxes_by_invoice.start.grouping = 'invoice'
    #     print_taxes_by_invoice.start.totals_only = False
    #     print_taxes_by_invoice.start.output_format = 'pdf'
    #     print_taxes_by_invoice.start.start_date = None
    #     print_taxes_by_invoice.start.tax_type = 'all'
    #     print_taxes_by_invoice.start.end_date = None
    #     _, data = print_taxes_by_invoice.do_print_(None)
    #     # Filter by supplier
    #     ids, parameters = TaxesByInvoiceReport.prepare(data)
    #     self.assertEqual(parameters['parties'], supplier2.rec_name)
    #     records = InvoiceTax.browse(ids)
    #     self.assertEqual(len(records), 0)
    #     session_id, _, _ = PrintTaxesByInvoice.create()
    #     print_taxes_by_invoice = PrintTaxesByInvoice(session_id)
    #     print_taxes_by_invoice.start.company = company
    #     print_taxes_by_invoice.start.fiscalyear = fiscalyear
    #     print_taxes_by_invoice.start.periods = [last_period.id]
    #     print_taxes_by_invoice.start.parties = []
    #     print_taxes_by_invoice.start.partner_type = 'suppliers'
    #     print_taxes_by_invoice.start.grouping = 'invoice'
    #     print_taxes_by_invoice.start.totals_only = False
    #     print_taxes_by_invoice.start.output_format = 'pdf'
    #     print_taxes_by_invoice.start.start_date = None
    #     print_taxes_by_invoice.start.end_date = None
    #     print_taxes_by_invoice.start.tax_type = 'all'
    #     _, data = print_taxes_by_invoice.do_print_(None)
    #     # Filter by periods
    #     ids, parameters = TaxesByInvoiceReport.prepare(data)
    #     self.assertEqual(parameters['periods'], last_period.rec_name)
    #     records = InvoiceTax.browse(ids)
    #     self.assertEqual(len(records), 0)
    #     # Filter by start/end date
    #     session_id, _, _ = PrintTaxesByInvoice.create()
    #     print_taxes_by_invoice = PrintTaxesByInvoice(session_id)
    #     print_taxes_by_invoice.start.company = company
    #     print_taxes_by_invoice.start.fiscalyear = fiscalyear
    #     print_taxes_by_invoice.start.periods = []
    #     print_taxes_by_invoice.start.parties = []
    #     print_taxes_by_invoice.start.partner_type = 'customers'
    #     print_taxes_by_invoice.start.grouping = 'invoice'
    #     print_taxes_by_invoice.start.totals_only = False
    #     print_taxes_by_invoice.start.start_date = period.start_date
    #     print_taxes_by_invoice.start.end_date = period.end_date
    #     print_taxes_by_invoice.start.output_format = 'pdf'
    #     print_taxes_by_invoice.start.tax_type = 'all'
    #     _, data = print_taxes_by_invoice.do_print_(None)
    #     ids, parameters = TaxesByInvoiceReport.prepare(data)
    #     self.assertEqual(parameters['start_date'], period.start_date.strftime('%d/%m/%Y'))
    #     self.assertEqual(parameters['end_date'], period.end_date.strftime('%d/%m/%Y'))
    #     records = InvoiceTax.browse(ids)
    #     self.assertEqual(len(records), 2)
    #
    # @with_transaction()
    # def test_fiscalyear_not_closed(self):
    #     'Test fiscalyear not closed'
    #     pool = Pool()
    #     FiscalYear = pool.get('account.fiscalyear')
    #     PrintGeneralLedger = pool.get(
    #         'account_reports.print_general_ledger', type='wizard')
    #     GeneralLedgerReport = pool.get(
    #         'account_reports.general_ledger', type='report')
    #     PrintTrialBalance = pool.get(
    #         'account_reports.print_trial_balance', type='wizard')
    #     TrialBalanceReport = pool.get(
    #         'account_reports.trial_balance', type='report')
    #     company = create_company()
    #
    #     fiscalyear = self.create_moves(company)
    #     fiscalyear.save()
    #     with set_company(company):
    #         next_fiscalyear = set_invoice_sequences(get_fiscalyear(company,
    #             today=fiscalyear.end_date + relativedelta(days=1)))
    #     next_fiscalyear.save()
    #     FiscalYear.create_period([next_fiscalyear])
    #     self.create_moves(company, next_fiscalyear, False)
    #
    #     # General ledger for the next year
    #     period = next_fiscalyear.periods[0]
    #     last_period = next_fiscalyear.periods[-1]
    #     session_id, _, _ = PrintGeneralLedger.create()
    #     print_general_ledger = PrintGeneralLedger(session_id)
    #     print_general_ledger.start.company = company
    #     print_general_ledger.start.fiscalyear = next_fiscalyear
    #     print_general_ledger.start.start_period = period
    #     print_general_ledger.start.end_period = last_period
    #     print_general_ledger.start.parties = []
    #     print_general_ledger.start.accounts = []
    #     print_general_ledger.start.all_accounts = True
    #     print_general_ledger.start.output_format = 'pdf'
    #     _, data = print_general_ledger.do_print_(None)
    #     records, parameters = GeneralLedgerReport.prepare(data)
    #     self.assertEqual(len(records), 12)
    #     self.assertEqual(parameters['start_period'], period.name)
    #     self.assertEqual(parameters['end_period'], last_period.name)
    #     self.assertEqual(parameters['fiscal_year'], next_fiscalyear.name)
    #     self.assertEqual(parameters['accounts'], '')
    #     self.assertEqual(parameters['parties'], '')
    #     credit = sum([m['credit'] for m in records])
    #     debit = sum([m['debit'] for m in records])
    #     self.assertEqual(credit, debit)
    #     self.assertEqual(credit, Decimal('730.0'))
    #     with_party = [m for m in records if m['party_name'] != '']
    #     self.assertEqual(len(with_party), 6)
    #     dates = sorted(set([r['date'] for r in records]))
    #     for date, expected_value in zip(dates, [period.start_date,
    #                 last_period.end_date]):
    #         self.assertEqual(date, expected_value.strftime('%d/%m/%Y'))
    #     balances = [
    #         Decimal('30'),            # Expense
    #         Decimal('80'),            # Expense
    #         Decimal('130'),            # Expense
    #         Decimal('-60'),            # Payable Party 1
    #         Decimal('-150'),           # Payable Party 2
    #         Decimal('-200'),           # Payable Party 2
    #         Decimal('200'),            # Receivable Party 1
    #         Decimal('700'),            # Receivable Party 2
    #         Decimal('1000'),           # Receivable Party 2
    #         Decimal('-100'),           # Revenue
    #         Decimal('-300'),           # Revenue
    #         Decimal('-600'),          # Revenue
    #         ]
    #     for record, balance in zip(records, balances):
    #         self.assertEqual(record['balance'], balance)
    #
    #     # Trial for the next year
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = next_fiscalyear
    #     print_trial_balance.start.start_period = period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = None
    #     print_trial_balance.start.with_move_only = False
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = True
    #     print_trial_balance.start.add_initial_balance = True
    #     print_trial_balance.start.comparison_fiscalyear = next_fiscalyear
    #     print_trial_balance.start.comparison_start_period = period
    #     print_trial_balance.start.comparison_end_period = last_period
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #
    #     # Full trial_balance
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     balances = {
    #         'Main Cash': Decimal('0'),
    #         'Main Tax': Decimal('0'),
    #         'View': Decimal('0'),
    #         'supplier1': Decimal('-30'),
    #         'supplier2': Decimal('-100'),
    #         'customer1': Decimal('100'),
    #         'customer2': Decimal('500'),
    #         'Main Expense': Decimal('130'),
    #         'Main Revenue': Decimal('-600'),
    #         }
    #     for record in records:
    #         self.assertEqual(record['period_initial_balance'],
    #             balances[record['name']])
    #         self.assertEqual(record['initial_balance'],
    #             balances[record['name']])
    #
    #     # Create another fiscalyear and test it cumulates correctly
    #     with set_company(company):
    #         future_fiscalyear = set_invoice_sequences(get_fiscalyear(company,
    #             today=fiscalyear.end_date + relativedelta(days=1, years=1)))
    #         future_fiscalyear.save()
    #     FiscalYear.create_period([future_fiscalyear])
    #     self.create_moves(company, future_fiscalyear, False)
    #
    #     period = future_fiscalyear.periods[0]
    #     last_period = future_fiscalyear.periods[-1]
    #     session_id, _, _ = PrintTrialBalance.create()
    #     print_trial_balance = PrintTrialBalance(session_id)
    #     print_trial_balance.start.company = company
    #     print_trial_balance.start.fiscalyear = future_fiscalyear
    #     print_trial_balance.start.start_period = period
    #     print_trial_balance.start.end_period = last_period
    #     print_trial_balance.start.parties = []
    #     print_trial_balance.start.accounts = []
    #     print_trial_balance.start.show_digits = None
    #     print_trial_balance.start.with_move_only = False
    #     print_trial_balance.start.with_move_or_initial = False
    #     print_trial_balance.start.split_parties = True
    #     print_trial_balance.start.add_initial_balance = True
    #     print_trial_balance.start.comparison_fiscalyear = future_fiscalyear
    #     print_trial_balance.start.comparison_start_period = period
    #     print_trial_balance.start.comparison_end_period = last_period
    #     print_trial_balance.start.output_format = 'pdf'
    #     _, data = print_trial_balance.do_print_(None)
    #
    #     # Full trial_balance
    #     records, parameters = TrialBalanceReport.prepare(data)
    #     balances = {
    #         'Main Cash': Decimal('0'),
    #         'Main Tax': Decimal('0'),
    #         'View': Decimal('0'),
    #         'supplier1': Decimal('-60'),
    #         'supplier2': Decimal('-200'),
    #         'customer1': Decimal('200'),
    #         'customer2': Decimal('1000'),
    #         'Main Expense': Decimal('260'),
    #         'Main Revenue': Decimal('-1200'),
    #         }
    #     for record in records:
    #         self.assertEqual(record['period_initial_balance'],
    #             balances[record['name']])
    #         self.assertEqual(record['initial_balance'],
    #             balances[record['name']])


def suite():
    suite = trytond.tests.test_tryton.suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        AccountReportsTestCase))
    return suite
