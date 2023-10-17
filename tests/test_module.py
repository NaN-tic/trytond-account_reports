
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


class AccountReportsTestCase(CompanyTestMixin, ModuleTestCase):
    'Test AccountReports module'
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
        print_general_ledger.start.start_date = None
        print_general_ledger.start.end_date = None
        print_general_ledger.start.parties = []
        print_general_ledger.start.accounts = []
        print_general_ledger.start.output_format = 'pdf'
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.final_accounts = False
        print_general_ledger.start.show_description = True
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
        print_general_ledger.start.final_accounts = False
        print_general_ledger.start.show_description = True
        print_general_ledger.start.output_format = 'pdf'
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data)
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
        print_general_ledger.start.final_accounts = False
        print_general_ledger.start.show_description = True
        print_general_ledger.start.output_format = 'pdf'
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data)
        self.assertEqual(len(records), 6)
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines']])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines']])
        self.assertEqual(credit, debit)
        self.assertEqual(credit, Decimal('380.0'))
        dates = sorted(set([line['line'].date for k, m in records.items() for line in m['lines']]))
        for date in dates:
            self.assertEqual(date, period.start_date)

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
        print_general_ledger.start.start_date = None
        print_general_ledger.start.end_date = None
        print_general_ledger.start.parties = []
        print_general_ledger.start.accounts = [expense.id]
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.final_accounts = False
        print_general_ledger.start.show_description = True
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
        print_general_ledger.start.start_date = None
        print_general_ledger.start.end_date = None
        print_general_ledger.start.parties = [customer1.id]
        print_general_ledger.start.accounts = []
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.final_accounts = False
        print_general_ledger.start.show_description = True
        print_general_ledger.start.output_format = 'pdf'
        _, data = print_general_ledger.do_print_(None)
        records, parameters = GeneralLedgerReport.prepare(data)
        self.assertEqual(parameters['parties'], customer1.rec_name)
        self.assertEqual(len(records), 1)
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines']])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines']])
        self.assertEqual(credit, Decimal('0.0'))
        self.assertEqual(debit, Decimal('100.0'))
        credit = sum([line['credit'] for k, m in records.items() for line in m['lines'] if m['party'] == ''])
        debit = sum([line['debit'] for k, m in records.items() for line in m['lines'] if m['party'] == ''])
        self.assertEqual(credit, Decimal('0.0'))
        self.assertEqual(debit, Decimal('0.0'))
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
        print_general_ledger.start.start_date = None
        print_general_ledger.start.end_date = None
        print_general_ledger.start.parties = [customer1.id]
        print_general_ledger.start.accounts = [receivable.id]
        print_general_ledger.start.output_format = 'pdf'
        print_general_ledger.start.all_accounts = False
        print_general_ledger.start.final_accounts = False
        print_general_ledger.start.show_description = True
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
        

del ModuleTestCase
