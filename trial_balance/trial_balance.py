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
    show_digits = fields.Integer('Digits', required=True)
    only_moves = fields.Boolean('Only Accounts With Move',
        states={
            'invisible': Bool(Eval('moves_or_initial'))
        })
    moves_or_initial = fields.Boolean(
        'Only Accounts With Moves or Initial Balance',
        states={
            'invisible': Bool(Eval('only_moves'))
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

    timeout = fields.Integer('Timeout (s)', required=True, help='If report '
        'calculation should take more than the specified timeout (in seconds) '
        'the process will be stopped automatically.')

    @staticmethod
    def default_show_digits():
        pool = Pool()
        Configuration = pool.get('account.configuration')

        config = Configuration(1)

        accounts_digits = None
        if hasattr(config, 'default_account_code_digits'):
            accounts_digits = config.default_account_code_digits
        return accounts_digits

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

    @staticmethod
    def default_timeout():
        Config = Pool().get('account.configuration')
        config = Config(1)
        return config.default_timeout or 30

    @fields.depends('only_moves')
    def on_change_only_moves(self):
        if self.only_moves:
            self.moves_or_initial = False

    @fields.depends('moves_or_initial')
    def on_change_moves_or_initial(self):
        if self.moves_or_initial:
            self.only_moves = False

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

    @fields.depends('show_digits', 'parties')
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
            self.split_parties = False
            if self.parties:
                self.parties = set()
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
            'only_moves': self.start.only_moves,
            'moves_or_initial': self.start.moves_or_initial,
            'split_parties': self.start.split_parties,
            'accounts': [x.id for x in self.start.accounts],
            'parties': [x.id for x in self.start.parties],
            'output_format': self.start.output_format,
            'timeout': self.start.timeout,
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
        #
        def build_tree(codes):
            tree = {}
            for code in sorted(codes):
                current = tree
                for part in code:
                    current = current.setdefault(part, {})
            return tree

        def flatten_tree(tree, prefix=""):
            result = []
            for key in sorted(tree.keys()):
                result.append(prefix + key)
                result.extend(flatten_tree(tree[key], prefix + key))
            return result

        def get_account_type(account):
            account_type = 'other'
            if account.type and account.type.receivable:
                account_type = 'receivable'
            elif account.type and account.type.payable:
                account_type = 'payable'
            return account_type

        def get_account_parent_name(account, digits):
            while account and len(account.code) > digits and account.parent:
                account = account.parent
            return account.name

        def get_account_values(values, digits):
            '''
            Obtain the values of the accounts and their parents
            and group by digits.
            '''
            def get_parents_account_values(tree, account, credit, debit,
                    balance):
                while account and account.parent and account.parent.parent:
                    account = account.parent
                    tree[account.code]['name'] = account.name
                    tree[account.code]['credit'] += credit
                    tree[account.code]['debit'] += debit
                    tree[account.code]['balance'] += balance
                    tree[account.code]['type'] = get_account_type(account)

            if digits:
                tree = {}
                for account_id in values:
                    account = Account(account_id)
                    if account.code[:digits] not in tree.keys():
                        tree[account.code[:digits]] = {
                            'name': get_account_parent_name(account, digits),
                            'credit': _ZERO,
                            'debit': _ZERO,
                            'balance': _ZERO,
                            'type': get_account_type(account)}
                    tree[account.code[:digits]]['credit'] += values[account_id]['credit']
                    tree[account.code[:digits]]['debit'] += values[account_id]['debit']
                    tree[account.code[:digits]]['balance'] += values[account_id]['balance']
            else:
                tree = defaultdict(lambda: {'credit': _ZERO, 'debit': _ZERO,
                    'balance': _ZERO})
                for account_id, account_values in values.items():
                    account = Account(account_id)
                    tree[account.code] = {
                        'name': account.name,
                        'credit': account_values.get('credit', _ZERO),
                        'debit': account_values.get('debit', _ZERO),
                        'balance': account_values.get('balance', _ZERO),
                        'type': get_account_type(account),
                    }
                    get_parents_account_values(tree, account,
                        values[account_id]['credit'],
                        values[account_id]['debit'],
                        values[account_id]['balance'])
            return tree

        def get_account_party_values(values):
            """
            Convert the account ID of the main dict to the account number.
            Convert the party ID of the sub dict to the combination of the
            party name and its TAX Identifier. To ensure that if some party
            is repeated, group them in the same register whenever the TAX
            Identifier is the same.
            """
            tree = {}
            for account_id, account_values in values.items():
                account = Account(account_id)
                party_tree = {}
                for party_id, value in account_values.items():
                    party = Party(party_id)
                    key = party.name + (" [" + party.tax_identifier.code + "]"
                        if party.tax_identifier else '')
                    if key in party_tree:
                        party_tree[key]['debit'] += value.get('debit')
                        party_tree[key]['credit'] += value.get('credit')
                        party_tree[key]['balance'] += value.get('balance')
                    else:
                        party_tree[key] = value
                tree[account.code] = party_tree
            return tree

        # Fiscalyear
        fiscalyear = (FiscalYear(data['fiscalyear']) if data.get('fiscalyear')
            else None)
        if not fiscalyear:
            raise UserError(gettext(
                'account_reports.msg_missing_fiscalyear'))

        comparison_fiscalyear = (FiscalYear(data['comparison_fiscalyear'])
            if data.get('comparison_fiscalyear') else None)

        # Company
        if data.get('company'):
            company = Company(data['company'])
        elif fiscalyear:
            company = fiscalyear.company
        else:
            company = Company(Transaction().context.get('company'))

        # Periods main and possible comparison
        start_period = (Period(data['start_period'])
            if data.get('start_period') else None)
        end_period = (Period(data['end_period']) if data.get('end_period')
            else None)
        if not start_period:
            start_period = Period.find(company, fiscalyear.start_date,
                test_state=True)
        if not end_period:
            end_period = Period.find(company, fiscalyear.end_date,
                test_state=True)
        initial_balance_date = start_period.start_date - timedelta(days=1)
        periods = [x.id for x in fiscalyear.get_periods(start_period,
            end_period)]

        if comparison_fiscalyear:
            comparison_start_period = (Period(data['comparison_start_period'])
                if data.get('comparison_start_period') else None)
            comparison_end_period = (Period(data['comparison_end_period'])
                if data.get('comparison_end_period') else None)
            if not comparison_start_period:
                comparison_start_period = Period.find(company,
                    comparison_fiscalyear.start_date, test_state=True)
            if not comparison_end_period:
                comparison_end_period = Period.find(company,
                    comparison_fiscalyear.end_date, test_state=True)
            init_comparison_date = (comparison_start_period.start_date -
                timedelta(days=1))
            comparison_periods = [x.id for x in
                comparison_fiscalyear.get_periods(
                    comparison_start_period, comparison_end_period)]

        # Possible parties selected
        split_parties = data.get('split_parties', False)
        party_ids = data.get('parties', [])

        with Transaction().set_context(active_test=False):
            # If some party are selected is not necessary to search all
            # accounts, only those that are related with that parties.
            # Even if are some accounts selected or there are not accounts
            # selected, only get the final accounts. And, after, calculate
            # the parents values of the accounts with get_account_values
            # function.
            account_ids = data.get('accounts', None)
            domain = [
                ('company', '=', company),
                ('parent', '!=', None)
            ]
            all_accounts = Account.search([domain])
            all_parent_ids = [a.parent.id for a in all_accounts]
            domain += [('id', 'not in', all_parent_ids)]
            if account_ids:
                # If we have accounts, we filter by these accounts,
                # otherwise we get all the final accounts
                domain += [('id', 'in', account_ids)]
            accounts = Account.search(domain, order=[('code', 'ASC')])
            accounts_subtitle = ''
            if account_ids:
                accounts_subtitle = []
                for x in accounts:
                    if len(accounts_subtitle) > 0:
                        accounts_subtitle.append('...')
                        break
                    accounts_subtitle.append(x.code)
                accounts_subtitle = ', '.join(accounts_subtitle)

            parties = []
            parties_subtitle = ''
            if split_parties:
                # Search by party selected or all, as we have ensured, with an
                # on_change, that not exist partis if there are digits selected
                # and they are not the last account. It's not filtered by
                # comapny, so it's needed any aprty that could have an account
                # move.
                domain = []
                if party_ids:
                    domain.append(('id', 'in', party_ids))
                parties = Party.search(domain)
                parties_subtitle = []

                for x in parties:
                    if len(parties_subtitle) > 0:
                        parties_subtitle.append('...')
                        break
                    parties_subtitle.append(x.name)
                parties_subtitle = ', '.join(parties_subtitle)

        digits = data.get('digits', None)
        max_digits = max(len(a.code) for a in accounts) if accounts else None
        add_initial_balance = data.get('add_initial_balance', False)
        with_moves = data.get('only_moves', False)
        with_moves_or_initial = data.get('moves_or_initial', False)
        if with_moves_or_initial:
            with_moves = True

        exclude_party_moves = True if party_ids else False
        # Obtain main fiscal year values based on accounts and digits.
        with Transaction().set_context(periods=periods):
            values = Account.html_read_account_vals(accounts,
                fiscalyear.company, with_moves=with_moves,
                exclude_party_moves=exclude_party_moves)
        with Transaction().set_context(date=initial_balance_date):
            init_values = Account.html_read_account_vals(accounts,
                fiscalyear.company, with_moves=with_moves,
                exclude_party_moves=exclude_party_moves)

        init_main_tree = get_account_values(init_values, digits)
        main_tree = get_account_values(values, digits)

        # Obtain comparison fiscal year values based on accounts and
        # digits.
        init_comparison_tree = {}
        comparison_tree = {}
        if comparison_fiscalyear:
            with Transaction().set_context(periods=comparison_periods):
                comparison_values = Account.html_read_account_vals(
                    accounts, fiscalyear.company, with_moves=with_moves,
                    exclude_party_moves=exclude_party_moves)
            with Transaction().set_context(date=init_comparison_date):
                init_comparison_values = Account.html_read_account_vals(
                    accounts, fiscalyear.company, with_moves=with_moves,
                    exclude_party_moves=exclude_party_moves)
            init_comparison_tree = get_account_values(
                init_comparison_values, digits)
            comparison_tree = get_account_values(comparison_values, digits)

        init_party_tree = {}
        party_tree = {}
        init_comparison_party_tree = {}
        comparison_party_tree = {}
        party_names = {}
        if split_parties:
            with Transaction().set_context(date=initial_balance_date):
                init_party_values = Party.html_get_account_values_by_party(
                    parties, accounts, fiscalyear.company)
            with Transaction().set_context(fiscalyear=fiscalyear.id,
                    periods=periods):
                party_values = Party.html_get_account_values_by_party(parties,
                    accounts, fiscalyear.company)

            init_party_tree = get_account_party_values(init_party_values)
            party_tree = get_account_party_values(party_values)

            if comparison_fiscalyear:
                with Transaction().set_context(date=init_comparison_date):
                    init_comparison_party_values = (
                        Party.html_get_account_values_by_party(parties,
                            accounts, fiscalyear.company))
                with Transaction().set_context(
                        fiscalyear=comparison_fiscalyear.id,
                        periods=comparison_periods):
                    comparison_party_values = (
                        Party.html_get_account_values_by_party(parties,
                            accounts, comparison_fiscalyear.company))
                init_comparison_party_tree = get_account_party_values(
                    init_comparison_party_values)
                comparison_party_tree = get_account_party_values(
                    comparison_party_values)

        def remove_registers(tree, initial=False):
            if initial:
                return {
                    key: value for key, value in tree.items()
                        if value.get('balance', _ZERO) != _ZERO
                }
            return {
                key: value for key, value in tree.items()
                    if value.get('debit', _ZERO) != _ZERO
                    or value.get('credit', _ZERO) != _ZERO
            }

        # Only need the registers with init balance
        init_main_tree = remove_registers(init_main_tree, initial=True)
        for code, value in init_party_tree.items():
            init_party_tree[code] = remove_registers(value, initial=True)
        if comparison_fiscalyear:
            init_comparison_tree = (
                remove_registers(init_comparison_tree, initial=True))
            for code, value in init_comparison_party_tree.items():
                init_comparison_party_tree[code] = remove_registers(value,
                    initial=True)
        if with_moves:
            main_tree = remove_registers(main_tree)
            for code, value in party_tree.items():
                party_tree[code] = remove_registers(value)
            if comparison_fiscalyear:
                comparison_tree = (
                    remove_registers(comparison_tree))
                comparison_party_tree = (
                    remove_registers(comparison_party_tree))

        # Get all the account codes to print in the report.
        all_codes = set(init_main_tree.keys()).union(main_tree.keys())
        if comparison_fiscalyear:
            # if comaprission fiscalyear is selected, need to add the possible
            # extra accounts in the comparision.
            comparison_all_codes = set(init_comparison_tree.keys()).union(
                comparison_tree.keys())
            all_codes = all_codes.union(comparison_all_codes)

        account_codes_parties = set(
            list(init_party_tree.keys()) + list(party_tree.keys()))
        all_parties = {}
        for code, value in init_party_tree.items():
            if code not in all_parties:
                all_parties[code] = []
            for party in value.keys():
                all_parties[code].append(party)
        for code, value in party_tree.items():
            if code not in all_parties:
                all_parties[code] = []
            for party in value.keys():
                all_parties[code].append(party)
        if comparison_fiscalyear:
            # if comaprission fiscalyear is selected, need to add the possible
            # extra accounts in the comparision.
            for code, value in init_comparison_party_tree.items():
                if code not in all_parties:
                    all_parties[code] = []
                for party in value.keys():
                    all_parties[code].append(party)
            for code,value in comparison_party_tree.items():
                if code not in all_parties:
                    all_parties[code] = []
                for party in value.keys():
                    all_parties[code].append(party)

        # Order codes and parties.
        tree = build_tree(all_codes)
        ordered_codes = flatten_tree(tree)
        accounts_codes = [code for code in ordered_codes if code in all_codes]
        party_names = {}
        for code, value in all_parties.items():
            party_names[code] = sorted(set(value))

        def _record(code, name, _type, init_vals, vals, init_comp, comp,
                add_initial_balance):
            init_balance = init_vals.get('balance', _ZERO)
            balance = (vals.get('balance', _ZERO) + init_balance
                if add_initial_balance else vals.get('balance', _ZERO))
            init_comp_balance = init_comp.get('balance', _ZERO)
            comp_balance = (comp.get('balance', _ZERO) + init_balance
                if add_initial_balance else comp.get('balance', _ZERO))

            return {
                'code': code,
                'name': name,
                'type': _type,
                'period_initial_balance': init_balance,
                'period_credit': vals.get('credit', _ZERO),
                'period_debit': vals.get('debit', _ZERO),
                'period_balance': balance,
                'initial_balance': init_comp_balance,
                'credit': comp.get('credit', _ZERO),
                'debit': comp.get('debit', _ZERO),
                'balance': comp_balance,
            }

        with Transaction().set_context(active_test=False):
            records = []
            for code in accounts_codes:
                if (with_moves and not with_moves_or_initial
                        and not main_tree.get(code, {})
                        and not comparison_tree.get(code, {})):
                    continue
                init_main_name = init_main_tree.get(code, {}).get(
                    'name', None)
                init_main_type = init_main_tree.get(code, {}).get(
                    'type', None)
                main_name = main_tree.get(code, {}).get('name', None)
                main_type = main_tree.get(code, {}).get('type', None)
                init_comp_name = init_comparison_tree.get(code, {}).get(
                    'name', None)
                init_comp_type = init_comparison_tree.get(code, {}).get(
                    'type', None)
                comp_name = comparison_tree.get(code, {}).get('name', None)
                comp_type = comparison_tree.get(code, {}).get('type', None)
                _type = (init_main_type or main_type or init_comp_type
                    or comp_type)
                if code in party_names.keys():
                    for party_name in party_names[code]:
                        if (with_moves and not with_moves_or_initial
                                and not party_tree.get(code, {}).get(
                                    party_name, {})
                                and not comparison_party_tree.get(
                                    code, {}).get(party_name, {})):
                            continue
                        record = _record(code, party_name, _type,
                            init_party_tree.get(code, {}).get(party_name, {}),
                            party_tree.get(code, {}).get(party_name, {}),
                            init_comparison_party_tree.get(code, {}).get(
                                party_name, {}),
                            comparison_party_tree.get(code, {}).get(
                                party_name, {}),
                            add_initial_balance)
                        records.append(record)
                else:
                    name = (init_main_name or main_name or init_comp_name
                        or comp_name)
                    record = _record(code, name, _type,
                        init_main_tree.get(code, {}), main_tree.get(code, {}),
                        init_comparison_tree.get(code, {}),
                        comparison_tree.get(code, {}), add_initial_balance)
                    records.append(record)
            if not accounts_codes and party_ids:
                for code in account_codes_parties:
                    main_type = party_tree.get(code, {}).get('type', None)
                    comp_type = comparison_party_tree.get(code, {}).get(
                        'type', None)
                    _type = main_type or comp_type
                    for party_name in party_names[code]:
                        credit = party_tree.get(code, {}).get(
                            party_name, {}).get('credit', _ZERO)
                        debit = party_tree.get(code, {}).get(
                            party_name, {}).get('debit', _ZERO)
                        initial_balance = init_party_tree.get(code, {}).get(
                            party_name, {}).get('balance', _ZERO)
                        if with_moves and not credit and not debit:
                            continue
                        if (with_moves_or_initial and not credit
                                and not debit and not initial_balance):
                            continue
                        record = _record(code, party_name, _type,
                            init_party_tree.get(code, {}).get(party_name, {}),
                            party_tree.get(code, {}).get(party_name, {}),
                            init_comparison_party_tree.get(code, {}).get(
                                party_name, {}),
                            comparison_party_tree.get(code, {}).get(
                                party_name, {}),
                            add_initial_balance)
                        records.append(record)
        parameters = {}
        parameters['second_balance'] = comparison_fiscalyear and True or False
        parameters['fiscalyear'] = fiscalyear.name
        parameters['comparison_fiscalyear'] = (comparison_fiscalyear and
            comparison_fiscalyear.name or '')
        parameters['start_period'] = start_period and start_period.name or ''
        parameters['end_period'] = end_period and end_period.name or ''
        parameters['comparison_start_period'] = (comparison_start_period.name
            if comparison_fiscalyear else '')
        parameters['comparison_end_period'] = (comparison_end_period.name
            if comparison_fiscalyear else '')
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
        totals_gropued = {}
        for record in records:
            if not digits and len(record.get('code', '')) != max_digits:
                continue

            digit = record.get('code', '')[0]
            if digit not in totals_gropued:
                totals_gropued[digit] = {
                    'initial': 0,
                    'debit': 0,
                    'credit': 0,
                    'balance': 0
                    }
            totals_gropued[digit]['initial'] += record.get('period_initial_balance')
            totals_gropued[digit]['debit'] += record.get('period_debit')
            totals_gropued[digit]['credit'] += record.get('period_credit')
            totals_gropued[digit]['balance'] += record.get('period_balance')

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
