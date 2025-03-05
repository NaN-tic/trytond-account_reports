# The COPYRIGHT filei at the top level of this repository contains the full
# copyright notices and License terms.
import os
from datetime import timedelta, datetime
from decimal import Decimal
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateView, StateReport, Button
from trytond.pyson import Eval, Bool, If
from trytond.rpc import RPC
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.modules.account.exceptions import FiscalYearNotFoundError
from trytond.modules.account_reports.common import TimeoutException, TimeoutChecker
from trytond.modules.html_report.html_report import HTMLReport
from collections import defaultdict

_ZERO = Decimal(0)


class PrintTrialBalanceStart(ModelView):
    'Print Trial Balance Start'
    __name__ = 'account_reports.print_trial_balance.start'

    fiscalyear = fields.Many2One('account.fiscalyear', 'Fiscal Year',
            required=True)
    comparison_fiscalyear = fields.Many2One('account.fiscalyear',
            'Fiscal Year')
    show_digits = fields.Integer('Digits')
    with_move_only = fields.Boolean('Only Accounts With Move',
        states={
            'invisible': Bool(Eval('add_initial_balance') &
                Eval('with_move_or_initial'))
        })
    with_move_or_initial = fields.Boolean(
        'Only Accounts With Moves or Initial Balance',
        states={
            'invisible': ~Bool(Eval('add_initial_balance'))
        })
    accounts = fields.Many2Many('account.account', None, None, 'Accounts')
    hide_split_parties = fields.Boolean('Hide Split Parties')
    split_parties = fields.Boolean('Split Parties',
        states={
            'invisible': Bool(Eval('hide_split_parties', False))},
            depends=['hide_split_parties'])
    add_initial_balance = fields.Boolean('Add Initial Balance')
    parties = fields.Many2Many('party.party', None, None, 'Parties',
        states={
            'invisible': ~Bool(Eval('split_parties', False)),
            },
        context={
            'company': Eval('company', -1),
            },
        depends=['company'])
    start_period = fields.Many2One('account.period', 'Start Period',
        domain=[
            ('fiscalyear', '=', Eval('fiscalyear')),
            If(Bool(Eval('end_period')),
                ('start_date', '<=', (Eval('end_period'), 'start_date')),
                (),
                ),
            ])
    end_period = fields.Many2One('account.period', 'End Period',
        domain=[
            ('fiscalyear', '=', Eval('fiscalyear')),
            If(Bool(Eval('start_period')),
                ('start_date', '>=', (Eval('start_period'), 'start_date')),
                (),
                )
            ])

    comparison_start_period = fields.Many2One('account.period', 'Start Period',
        domain=[
            ('fiscalyear', '=', Eval('comparison_fiscalyear')),
            ('start_date', '<=', (Eval('comparison_end_period'),
                    'start_date')),
            ])
    comparison_end_period = fields.Many2One('account.period', 'End Period',
        domain=[
            ('fiscalyear', '=', Eval('comparison_fiscalyear')),
            ('start_date', '>=', (Eval('comparison_start_period'),
                    'start_date'))
            ])
    output_format = fields.Selection([
            ('pdf', 'PDF'),
            ('html', 'HTML'),
            ('xls', 'Excel'),
            ], 'Output Format', required=True)
    company = fields.Many2One('company.company', 'Company', required=True)

    @staticmethod
    def default_fiscalyear():
        pool = Pool()
        FiscalYear = pool.get('account.fiscalyear')
        try:
            fiscalyear = FiscalYear.find(
                Transaction().context.get('company'), test_state=False)
        except FiscalYearNotFoundError:
            return None
        return fiscalyear.id

    @staticmethod
    def default_start_period():
        pool = Pool()
        FiscalYear = pool.get('account.fiscalyear')
        Period = pool.get('account.period')
        try:
            fiscalyear = FiscalYear.find(
                Transaction().context.get('company'), test_state=False)
        except FiscalYearNotFoundError:
            return None

        clause = [
            ('fiscalyear', '=', fiscalyear),
            ]
        periods = Period.search(clause, order=[('start_date', 'ASC')],
            limit=1)
        if periods:
            return periods[0].id

    @staticmethod
    def default_end_period():
        pool = Pool()
        FiscalYear = pool.get('account.fiscalyear')
        Period = pool.get('account.period')
        try:
            fiscalyear = FiscalYear.find(
                Transaction().context.get('company'), test_state=False)
        except FiscalYearNotFoundError:
            return None

        Date = Pool().get('ir.date')
        date = Date.today()

        clause = [
            ('fiscalyear', '=', fiscalyear),
            ('start_date', '<=', date),
            ('end_date', '>=', date),
            ]
        periods = Period.search(clause, order=[('start_date', 'ASC')],
            limit=1)
        if periods:
            return periods[0].id

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_output_format():
        return 'pdf'

    @fields.depends('fiscalyear')
    def on_change_fiscalyear(self):
        self.start_period = None
        self.end_period = None

    @fields.depends('comparison_fiscalyear')
    def on_change_comparison_fiscalyear(self):
        self.comparison_start_period = None
        self.comparison_end_period = None

    @classmethod
    def view_attributes(cls):
        return [('/form//label[@id="all_parties"]', 'states',
                {'invisible': ~Bool(Eval('split_parties'))})]

    @fields.depends('show_digits')
    def on_change_show_digits(self):
        pool = Pool()
        Configuration = pool.get('account.configuration')
        Account = pool.get('account.account')

        config = Configuration(1)

        accounts_digits = None
        if hasattr(config, 'default_account_code_digits'):
            accounts_digits = config.default_account_code_digits
        else:
            accounts = [a.code for a in Account.search([])]
            if accounts:
                accounts_digits = len(max(accounts,
                    key=len))

        if (accounts_digits and self.show_digits and
                self.show_digits != accounts_digits):
            self.hide_split_parties = True
        else:
            self.hide_split_parties = False


class PrintTrialBalance(Wizard):
    'Print TrialBalance'
    __name__ = 'account_reports.print_trial_balance'
    start = StateView('account_reports.print_trial_balance.start',
        'account_reports.print_trial_balance_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Print', 'print_', 'tryton-print', default=True),
            ])
    print_ = StateReport('account_reports.trial_balance')

    def do_print_(self, action):
        start_period = self.start.fiscalyear.periods[0].id
        if self.start.start_period:
            start_period = self.start.start_period.id
        end_period = self.start.fiscalyear.periods[-1].id
        if self.start.end_period:
            end_period = self.start.end_period.id
        comparison_start_period = None
        if self.start.comparison_start_period:
            comparison_start_period = self.start.comparison_start_period.id
        elif (self.start.comparison_fiscalyear
                and self.start.comparison_fiscalyear.periods):
            comparison_start_period = (
                self.start.comparison_fiscalyear.periods[0].id)
        comparison_end_period = None
        if self.start.comparison_end_period:
            comparison_end_period = self.start.comparison_end_period.id
        elif (self.start.comparison_fiscalyear
                and self.start.comparison_fiscalyear.periods):
            comparison_end_period = (
                self.start.comparison_fiscalyear.periods[-1].id)
        data = {
            'company': self.start.company.id,
            'fiscalyear': self.start.fiscalyear.id,
            'comparison_fiscalyear': (self.start.comparison_fiscalyear and
                self.start.comparison_fiscalyear.id or None),
            'start_period': start_period,
            'end_period': end_period,
            'comparison_start_period': comparison_start_period,
            'comparison_end_period': comparison_end_period,
            'digits': self.start.show_digits or None,
            'add_initial_balance': self.start.add_initial_balance,
            'with_move_only': self.start.with_move_only,
            'with_move_or_initial': self.start.with_move_or_initial,
            'hide_split_parties': self.start.hide_split_parties,
            'split_parties': self.start.split_parties,
            'accounts': [x.id for x in self.start.accounts],
            'parties': [x.id for x in self.start.parties],
            'output_format': self.start.output_format,
            }

        return action, data

    def transition_print_(self):
        return 'end'

    def default_start(self, fields):
        Party = Pool().get('party.party')
        account_ids = []
        party_ids = []
        if Transaction().context.get('model') == 'party.party':
            for party in Party.browse(Transaction().context.get('active_ids')):
                if party.account_payable:
                    account_ids.append(party.account_payable.id)
                if party.account_receivable:
                    account_ids.append(party.account_receivable.id)
                party_ids.append(party.id)
        return {
            'accounts': account_ids,
            'parties': party_ids,
            }

class TrialBalanceReport(HTMLReport):
    __name__ = 'account_reports.trial_balance'
    side_margin = 0

    @classmethod
    def __setup__(cls):
        super(TrialBalanceReport, cls).__setup__()
        cls.__rpc__['execute'] = RPC(False)
        cls.side_margin = 0.3

    @classmethod
    def prepare(cls, data, checker):
        pool = Pool()
        Company = pool.get('company.company')
        FiscalYear = pool.get('account.fiscalyear')
        Period = pool.get('account.period')
        Account = pool.get('account.account')
        Party = pool.get('party.party')
        #TODO: add the "checker.check()" function after and before every
        # function where we make some big calculations

        def get_account_values(values, digits):
            def get_parents_account_values(tree, account, credit, debit,
                    balance):
                while account and account.parent:
                    account = account.parent
                    tree[account.id]['credit'] += credit
                    tree[account.id]['debit'] += debit
                    tree[account.id]['balance'] += balance

            if digits:
                tree = {}
                for account_id in values:
                    account = Account(account_id)
                    if not account.code[:digits] in tree.keys():
                        tree[account.code[:digits]] = {'credit': Decimal(0),
                            'debit': Decimal(0), 'balance': Decimal(0)}
                    tree[account.code[:digits]]['credit'] += values[account_id]['credit']
                    tree[account.code[:digits]]['debit'] += values[account_id]['debit']
                    tree[account.code[:digits]]['balance'] += values[account_id]['balance']
            else:
                tree = defaultdict(lambda: {'credit': Decimal(0),
                    'debit': Decimal(0), 'balance': Decimal(0)}, values)
                for account_id in values:
                    account = Account(account_id)
                    get_parents_account_values(tree, account,
                        values[account_id]['credit'],
                        values[account_id]['debit'],
                        values[account_id]['balance'])
            return tree

        # Fiscalyear
        fiscalyear = (FiscalYear(data['fiscalyear']) if data.get('fiscalyear')
            else None)

        comparison_fiscalyear = (FiscalYear(data['comparison_fiscalyear'])
            if data.get('comparison_fiscalyear') else None)

        # Periods
        start_period = (Period(data['start_period']) if data.get('start_period')
            else None)
        end_period = (Period(data['end_period']) if data.get('end_period')
            else None)
        comparison_start_period = (Period(data['comparison_start_period'])
            if data.get('comparison_start_period') else None)
        comparison_end_period = (Period(data['comparison_end_period'])
            if data.get('comparison_end_period') else None)

        with Transaction().set_context(active_test=False):
            domain = [('parent', '!=', None)]
            if data.get('accounts'):
                # If we have accounts, we filter by these accounts
                domain += [('id', 'in', data.get('accounts', []))]
            else:
                # otherwise we start from the farthest accounts to the root of
                # accounts
                domain += [('type', '!=', None)]

            accounts = Account.search(domain, order=[('code', 'ASC')])
            accounts_subtitle = ''
            if data.get('accounts'):
                accounts_subtitle = []
                for x in accounts:
                    if len(accounts_subtitle) > 0:
                        accounts_subtitle.append('...')
                        break
                    accounts_subtitle.append(x.code)
                accounts_subtitle = ', '.join(accounts_subtitle)
            else:
                accounts_subtitle = ''

            parties = Party.browse(data.get('parties', []))
            parties_subtitle = []

            split_parties = data['split_parties']
            hide_split_parties = data['hide_split_parties']
            if hide_split_parties:
                split_parties = False

            if parties and split_parties:
                for x in parties:
                    if len(parties_subtitle) > 0:
                        parties_subtitle.append('...')
                        break
                    parties_subtitle.append(x.name)
                parties_subtitle = ', '.join(parties_subtitle)

        digits = data['digits']
        add_initial_balance = data['add_initial_balance']
        with_moves = data['with_move_only']

        if not add_initial_balance:
            with_moves_or_initial = False
        else:
            with_moves_or_initial = data['with_move_or_initial']
        if with_moves_or_initial:
            with_moves = True

        periods = [x.id for x in fiscalyear.get_periods(start_period,
            end_period)]
        if comparison_fiscalyear:
            comparison_periods = [x.id for x in comparison_fiscalyear.get_periods(
                comparison_start_period, comparison_end_period)]

        with Transaction().set_context(periods=periods):
            values = Account.html_read_account_vals(accounts,
                fiscalyear.company, with_moves=with_moves)
        init_values = {}
        initial_balance_date = start_period.start_date - timedelta(days=1)
        with Transaction().set_context(date=initial_balance_date):
            init_values = Account.html_read_account_vals(accounts,
                fiscalyear.company, with_moves=with_moves)

        comparison_initial_values = {}.fromkeys(accounts, {'credit': Decimal(0),
            'debit': Decimal(0), 'balance': Decimal(0)})
        comparison_values = {}.fromkeys(accounts, {'credit': Decimal(0),
            'debit': Decimal(0), 'balance': Decimal(0)})

        if comparison_fiscalyear:
            with Transaction().set_context(periods=comparison_periods):
                comparison_values = Account.html_read_account_vals(accounts,
                    fiscalyear.company, with_moves=with_moves)

            initial_comparision_date = (comparison_start_period.start_date -
                timedelta(days=1))
            with Transaction().set_context(date=initial_comparision_date):
                comparison_initial_values.update(
                    Account.html_read_account_vals(accounts,
                        fiscalyear.company, with_moves=with_moves))

        if split_parties:
            init_party_values = {}
            if add_initial_balance:
                with Transaction().set_context(date=initial_balance_date):
                    init_party_values = Party.html_get_account_values_by_party(
                        parties, accounts, fiscalyear.company)

            with Transaction().set_context(fiscalyear=fiscalyear.id,
                    periods=periods):
                party_values = Party.html_get_account_values_by_party(parties,
                    accounts, fiscalyear.company)

            init_comparison_party_values = {}
            comparison_party_values = {}
            if comparison_fiscalyear:
                with Transaction().set_context(date=initial_comparision_date):
                    init_comparison_party_values = (
                        Party.html_get_account_values_by_party(parties,
                            accounts, fiscalyear.company))

                with Transaction().set_context(
                        fiscalyear=comparison_fiscalyear.id,
                        periods=comparison_periods):
                    comparison_party_values = (
                        Party.html_get_account_values_by_party(parties,
                            accounts, comparison_fiscalyear.company))

        accounts = []
        init_final_tree = get_account_values(init_values, digits)
        final_tree = get_account_values(values, digits)
        comp_init_final_tree = get_account_values(comparison_initial_values,
            digits)
        comp_final_tree = get_account_values(comparison_values, digits)

        # Get all the codes
        if comparison_fiscalyear:
            accounts_codes = set(list(init_final_tree.keys()) +
                list(final_tree.keys()) + list(comp_init_final_tree.keys()) +
                list(comp_final_tree.keys()))
        else:
            accounts_codes = set(list(init_final_tree.keys()) +
                list(final_tree.keys()))

        def _amounts(account, initial_tree, tree, account_code_accounts=None):
            initial = _ZERO
            credit = _ZERO
            debit = _ZERO
            balance = _ZERO

            account_id = account.id
            if (account_code_accounts and account.id in
                    account_code_accounts.keys()):
                account_id = account_code_accounts[account.id]

            if account_id in initial_tree:
                initial = initial_tree[account_id]['balance']
            if account_id in tree:
                credit = tree[account_id]['credit']
                debit = tree[account_id]['debit']
                balance = tree[account_id]['balance']
            return initial, credit, debit, balance

        def _party_amounts(account, party_id, init_vals, vals,
                account_code_accounts=None):
            account_id = account.id
            iac_vals = init_vals.get(account_id, {})
            ac_vals = vals.get(account_id, {})

            initial = iac_vals.get(party_id, {}).get('balance') or _ZERO
            credit = ac_vals.get(party_id, {}).get('credit') or _ZERO
            debit = ac_vals.get(party_id, {}).get('debit') or _ZERO
            balance = ac_vals.get(party_id, {}).get('balance') or _ZERO
            return initial, credit, debit, balance

        def _record(account, party, vals, comp, add_initial_balance,
                account_code_accounts=None):
            init, credit, debit, balance = vals
            init_comp, credit_comp, debit_comp, balance_comp = comp
            if add_initial_balance:
                balance += init
                balance_comp += init_comp
            account_type = 'other'
            if account.type and account.type.receivable:
                account_type = 'receivable'
            elif account.type and account.type.payable:
                account_type = 'payable'

            code = account.code or ''
            if (account_code_accounts and account.id in
                    account_code_accounts.keys()):
                code = account_code_accounts[account.id]

            return {
                'code': code,
                'name': party and party.name or account.name,
                'type': account_type,
                'period_initial_balance': init,
                'period_credit': credit,
                'period_debit': debit,
                'period_balance': balance,
                'initial_balance': init_comp,
                'credit': credit_comp,
                'debit': debit_comp,
                'balance': balance_comp,
            }

        with Transaction().set_context(active_test=False):
            # Prepare the accounts to the report
            accounts = []
            accounts_account_code = {}

            if digits:
                for account_code in accounts_codes:
                    account = None
                    # We must save the original value we need to save
                    account_code_org = account_code
                    while not account:
                        account = Account.search([('code', '=', account_code)])
                        account_code = account_code[:-1]
                    accounts.append(account[0])
                    accounts_account_code[account[0].id] = account_code_org
                accounts = sorted(accounts, key=lambda a: a.code)
            else:
                domain = [('parent', '!=', None)]
                if data.get('accounts'):
                    domain += [('id', 'in', data.get('accounts', []))]
                accounts = Account.search(domain, order=[('code', 'ASC')])

            records = []
            ok_records = []
            for account in accounts:
                vals = _amounts(account, init_final_tree, final_tree,
                    accounts_account_code)
                initial, credit, debit, balance = vals

                comp_vals = _amounts(account, comp_init_final_tree,
                    comp_final_tree, accounts_account_code)
                comp_initial, comp_credit, comp_debit, comp_balance = (
                    comp_vals)

                empty = False
                comp_empty = False
                if with_moves_or_initial:
                    empty = (credit == 0 and debit == 0 and initial == 0)
                    comp_empty = (comp_credit== 0 and comp_debit == 0 and
                        comp_initial == 0)
                elif with_moves:
                    empty = (credit == 0 and debit == 0)
                    comp_empty = (comp_credit == 0 and comp_debit == 0)

                if empty and (not comparison_fiscalyear or comp_empty):
                    continue

                if split_parties and account.party_required:
                    account_parties = parties
                    if not account_parties:
                        pids = set()
                        if account.id in party_values:
                            pids |= set(party_values[account.id].keys())
                        if account.id in init_party_values:
                            pids |= set(init_party_values[account.id].keys())
                        account_parties = [None] if None in pids else []
                        # Using search insted of browse to get ordered records
                        account_parties += Party.search([
                            ('id', 'in', [p for p in pids if p])
                            ])
                    for party in account_parties:
                        party_key = party.id if party else None
                        party_vals = _party_amounts(account, party_key,
                            init_party_values, party_values,
                            accounts_account_code)
                        party_comp_vals = _party_amounts(account,
                            party_key, init_comparison_party_values,
                            comparison_party_values, accounts_account_code)
                        init, credit, debit, balance = party_vals

                        if with_moves_or_initial:
                            if credit == 0 and debit == 0 and initial == 0:
                                continue
                        elif with_moves and credit == 0 and debit == 0:
                            continue

                        record = _record(account, party,
                            party_vals, party_comp_vals,
                            add_initial_balance, accounts_account_code)

                        records.append(record)
                        ok_records.append(account.code)
                else:
                    record = _record(account, None, vals, comp_vals,
                        add_initial_balance, accounts_account_code)
                    records.append(record)
                    ok_records.append(account.code)

        # Company
        if data.get('company'):
            company = Company(data['company'])
        elif fiscalyear:
            company = fiscalyear.company
        else:
            company = Company(Transaction().context.get('company'))

        parameters = {}
        parameters['second_balance'] = comparison_fiscalyear and True or False
        parameters['fiscalyear'] = fiscalyear.name
        parameters['comparison_fiscalyear'] = (comparison_fiscalyear and
            comparison_fiscalyear.name or '')
        parameters['start_period'] = start_period and start_period.name or ''
        parameters['end_period'] = end_period and end_period.name or ''
        parameters['comparison_start_period'] = (comparison_start_period and
            comparison_start_period.name or '')
        parameters['comparison_end_period'] = (comparison_end_period and
            comparison_end_period.name or '')
        parameters['company_rec_name'] = company and company.rec_name or ''
        parameters['company_vat'] = (company and
            company.party.tax_identifier and
            company.party.tax_identifier.code) or ''
        parameters['with_moves_only'] = with_moves or ''
        parameters['split_parties'] = split_parties or ''
        parameters['digits'] = digits or ''
        parameters['parties'] = parties_subtitle or ''
        parameters['accounts'] = accounts_subtitle or ''
        # Totals
        parameters['total_period_initial_balance'] = 0
        parameters['total_period_debit'] = 0
        parameters['total_period_credit'] = 0
        parameters['total_period_balance'] = 0
        parameters['total_initial_balance'] = 0
        parameters['total_debit'] = 0
        parameters['total_credit'] = 0
        parameters['total_balance'] = 0
        for record in records:
            parameters['total_period_initial_balance'] += (
                record['period_initial_balance'])
            parameters['total_period_debit'] += record['period_debit']
            parameters['total_period_credit'] += record['period_credit']
            parameters['total_period_balance'] += record['period_balance']
            parameters['total_initial_balance'] += record['initial_balance']
            parameters['total_debit'] += record['debit']
            parameters['total_credit'] += record['credit']
            parameters['total_balance'] += record['balance']
        return records, parameters

    @classmethod
    def timeout_exception(cls):
        raise TimeoutException

    @classmethod
    def execute(cls, ids, data):
        pool = Pool()
        Config = pool.get('account.configuration')

        config = Config(1)
        timeout = data.get('timeout') or config.default_timeout or 300
        checker = TimeoutChecker(timeout, cls.timeout_exception)

        start_prepare = datetime.now()
        with Transaction().set_context(active_test=False):
            try:
                records, parameters = cls.prepare(data, checker)
            except TimeoutException:
                raise UserError(gettext(
                    'account_reports.msg_timeout_exception'))
        end_prepare = datetime.now()

        context = Transaction().context.copy()
        context['report_lang'] = Transaction().language
        context['report_translations'] = os.path.join(
                os.path.dirname(__file__), 'translations')
        if timeout:
            context['timeout_report'] = timeout - int(
                (end_prepare - start_prepare).total_seconds())

        with Transaction().set_context(**context):
            return super(TrialBalanceReport, cls).execute(ids, {
                'name': 'account_reports.trial_balance',
                'model': 'account.move.line',
                'records': records,
                'parameters': parameters,
                'output_format': data.get('output_format', 'pdf'),
                })
