import datetime
import unittest
from decimal import Decimal

from proteus import Model

from trytond.modules.account.tests.tools import (
    create_chart, create_fiscalyear, get_accounts)
from trytond.modules.account_invoice.tests.tools import (
    set_fiscalyear_invoice_sequences)
from trytond.modules.account_reports.common import TimeoutChecker
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestTrialBalanceSplitParties(unittest.TestCase):

    def setUp(self):
        drop_db()
        self.config = activate_modules('account_reports')
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        Journal = Model.get('account.journal', config=self.config)
        Move = Model.get('account.move', config=self.config)
        Party = Model.get('party.party', config=self.config)

        _ = create_company(config=self.config)
        company = get_company(config=self.config)
        create_chart(company, config=self.config)
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(
                company,
                today=(datetime.date(2025, 1, 1),
                    datetime.date(2025, 12, 31)),
                config=self.config),
            config=self.config)
        fiscalyear.click('create_period')
        first_period, second_period = fiscalyear.periods[:2]
        accounts = get_accounts(company, config=self.config)
        expense = accounts['expense']
        payable = accounts['payable']
        journal, = Journal.find([('code', '=', 'EXP')])
        party = Party(name='Party')
        party.save()

        for debit, credit in ((Decimal('100'), Decimal('0')),
                (Decimal('0'), Decimal('100'))):
            move = Move()
            move.company = company
            move.period = first_period
            move.journal = journal
            move.date = first_period.start_date
            line = move.lines.new()
            line.account = expense
            line.debit = credit
            line.credit = debit
            line = move.lines.new()
            line.account = payable
            line.party = party
            line.debit = debit
            line.credit = credit
            move.save()
            move.click('post')

        payable.party_required = False
        payable.save()
        move = Move()
        move.company = company
        move.period = second_period
        move.journal = journal
        move.date = second_period.start_date
        line = move.lines.new()
        line.account = expense
        line.debit = Decimal('50')
        line = move.lines.new()
        line.account = payable
        line.credit = Decimal('50')
        move.save()
        move.click('post')

        with Transaction().start(self.config.database_name, 0):
            Company = Pool().get('company.company')
            FiscalYear = Pool().get('account.fiscalyear')
            Period = Pool().get('account.period')
            PrintTrialBalance = Pool().get(
                'account_reports.print_trial_balance', type='wizard')
            TrialBalanceReport = Pool().get(
                'account_reports.trial_balance', type='report')
            company = Company(company.id)
            fiscalyear = FiscalYear(fiscalyear.id)
            second_period = Period(second_period.id)
            session_id, _, _ = PrintTrialBalance.create()
            wizard = PrintTrialBalance(session_id)
            wizard.start.company = company
            wizard.start.fiscalyear = fiscalyear
            wizard.start.start_period = second_period
            wizard.start.end_period = second_period
            wizard.start.comparison_fiscalyear = None
            wizard.start.comparison_start_period = None
            wizard.start.comparison_end_period = None
            wizard.start.show_digits = 0
            wizard.start.only_moves = False
            wizard.start.moves_or_initial = False
            wizard.start.hide_split_parties = False
            wizard.start.split_parties = True
            wizard.start.add_initial_balance = False
            wizard.start.accounts = []
            wizard.start.parties = []
            wizard.start.output_format = 'pdf'
            wizard.start.timeout = 30
            _, data = wizard.do_print_(None)
            checker = TimeoutChecker(30, TrialBalanceReport.timeout_exception)
            records, _ = TrialBalanceReport.prepare(data, checker)

        record = next(record for record in records
            if record['code'] == payable.code)
        self.assertEqual(record['name'], payable.name)
        self.assertEqual(record['period_credit'], Decimal('50'))
