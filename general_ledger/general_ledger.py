# This file is part of account_reports for tryton.  The COPYRIGHT file
# at the top level of this repository contains the full copyright notices and
# license terms.
import os
from datetime import timedelta, datetime
from decimal import Decimal
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateView, StateReport, Button
from trytond.pyson import Eval, Bool, If
from trytond.tools import grouped_slice
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.modules.account_reports.common import TimeoutException, TimeoutChecker
from trytond.modules.html_report.html_report import HTMLReport
from trytond.rpc import RPC
from trytond.modules.account.exceptions import FiscalYearNotFoundError

_ZERO = Decimal(0)


class PrintGeneralLedgerStart(ModelView):
    'Print General Ledger'
    __name__ = 'account_reports.print_general_ledger.start'
    fiscalyear = fields.Many2One('account.fiscalyear', 'Fiscal Year',
        states={
            'invisible': Eval('start_date') | Eval('end_date'),
            'required': ~Eval('start_date') & ~Eval('end_date'),
            })
    start_period = fields.Many2One('account.period', 'Start Period',
        states={
            'invisible': Eval('start_date') | Eval('end_date'),
            'required': ~Eval('start_date') & ~Eval('end_date'),
            },
        domain=[
            ('fiscalyear', '=', Eval('fiscalyear')),
            If(Bool(Eval('end_period')),
                ('start_date', '<=', (Eval('end_period'), 'start_date')),
                (),
                ),
            ])
    end_period = fields.Many2One('account.period', 'End Period',
        states={
            'invisible': Eval('start_date') | Eval('end_date'),
            'required': ~Eval('start_date') & ~Eval('end_date'),
            },
        domain=[
            ('fiscalyear', '=', Eval('fiscalyear')),
            If(Bool(Eval('start_period')),
                ('start_date', '>=', (Eval('start_period'), 'start_date')),
                (),
                ),
            ])
    start_date = fields.Date('Initial Posting Date',
        domain=[
            If(Eval('start_date') & Eval('end_date'),
                ('start_date', '<=', Eval('end_date', None)),
                ()),
            ],
        states={
            'invisible': Eval('start_period') | Eval('end_period'),
            'required': ((Eval('start_date') | Eval('end_date')) &
                ~Bool(Eval('start_period') | Eval('end_period'))),
            })
    end_date = fields.Date('Final Posting Date',
        domain=[
            If(Eval('start_date') & Eval('end_date'),
                ('end_date', '>=', Eval('start_date', None)),
                ()),
            ],
        states={
            'invisible': Eval('start_period') | Eval('end_period'),
            'required': ((Eval('end_date') | Eval('start_date')) &
                ~Bool(Eval('start_period') | Eval('end_period')))
            })
    accounts = fields.Many2Many('account.account', None, None, 'Accounts')
    all_accounts = fields.Boolean('All accounts with and without balance',
        states={
            'readonly': Bool(Eval('accounts')),
            },
        help='If unchecked only print accounts with previous balance different'
        ' from 0 or with moves')
    final_accounts = fields.Boolean('Only final accounts',
        help='If unchecked print all tree accounts from 1 to all digits')
    parties = fields.Many2Many('party.party', None, None, 'Parties',
        context={
            'company': Eval('company', -1),
            },
        depends=['company'])
    output_format = fields.Selection([
            ('pdf', 'PDF'),
            ('html', 'HTML'),
            ('xls', 'Excel'),
            ], 'Output Format', required=True)
    company = fields.Many2One('company.company', 'Company', required=True)
    timeout = fields.Integer('Timeout (s)', required=True, help='If report '
        'calculation should take more than the specified timeout (in seconds) '
        'the process will be stopped automatically.')
    show_description = fields.Boolean('Show Description',
        help='If checked show description from Account Move Line')

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
    def default_all_accounts():
        return True

    @staticmethod
    def default_final_accounts():
        return True

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

    def default_show_description():
        return True

    @fields.depends('fiscalyear')
    def on_change_fiscalyear(self):
        self.start_period = None
        self.end_period = None

    @fields.depends('accounts')
    def on_change_accounts(self):
        if self.accounts:
            self.all_accounts = False


class PrintGeneralLedger(Wizard):
    'Print General Ledger'
    __name__ = 'account_reports.print_general_ledger'
    start = StateView('account_reports.print_general_ledger.start',
        'account_reports.print_general_ledger_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Print', 'print_', 'tryton-print', default=True),
            ])
    print_ = StateReport('account_reports.general_ledger')

    def do_print_(self, action):
        start_period = None
        if self.start.start_period:
            start_period = self.start.start_period.id
        end_period = None
        if self.start.end_period:
            end_period = self.start.end_period.id
        data = {
            'company': self.start.company.id,
            'fiscalyear': self.start.fiscalyear.id if self.start.fiscalyear else None,
            'start_period': start_period,
            'end_period': end_period,
            'start_date': self.start.start_date,
            'end_date': self.start.end_date,
            'accounts': [x.id for x in self.start.accounts],
            'all_accounts': self.start.all_accounts,
            'final_accounts': self.start.final_accounts,
            'parties': [x.id for x in self.start.parties],
            'output_format': self.start.output_format,
            'timeout': self.start.timeout,
            'show_description': self.start.show_description,
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


class GeneralLedgerReport(HTMLReport):
    __name__ = 'account_reports.general_ledger'

    @classmethod
    def __setup__(cls):
        super(GeneralLedgerReport, cls).__setup__()
        cls.__rpc__['execute'] = RPC(False)
        cls.side_margin = 0.3

    @classmethod
    def _ref_origin_invoice_line(cls, line):
        if not line.origin or not line.origin.invoice:
            return ''
        ref = []
        if line.origin.invoice.number:
            ref.append('%s' % line.origin.invoice.number)
        if line.origin.invoice.reference:
            ref.append('[%s]' % line.origin.invoice.reference)
        if line.origin.invoice.party.rec_name:
            ref.append('%s' % line.origin.invoice.party.rec_name)
        return ' '.join(ref)

    @classmethod
    def _ref_origin_invoice(cls, line):
        ref = []
        if line.move_origin.number:
            ref.append('%s' % line.move_origin.number)
        if line.move_origin.reference:
            ref.append('[%s]' % line.move_origin.reference)
        if line.move_origin.party.rec_name:
            ref.append('%s' % line.move_origin.party.rec_name)
        return ' '.join(ref)

    @classmethod
    def _ref_origin_bank_line(cls, line):
        if line.origin.description:
            ref = '%s' % line.origin.description
        else:
            ref = (line.origin.rec_name if line.origin
                and hasattr(line.origin, 'rec_name') else None)
        return ref

    @classmethod
    def _ref_origin_statement_origin(cls, line):
        if line.origin.description and not line.description:
            ref = '%s' % line.origin.description
        else:
            ref = (line.origin.rec_name if line.origin
                and hasattr(line.origin, 'rec_name') else None)
        return ref

    @classmethod
    def _ref_origin(cls, line):
        return (line.origin.rec_name if line.origin
            and hasattr(line.origin, 'rec_name') else None)

    @classmethod
    def _ref_move_origin(cls, line):
        return (line.move_origin.rec_name if line.move_origin
            and hasattr(line.move_origin, 'rec_name') else None)

    @classmethod
    def prepare(cls, data, checker):
        pool = Pool()
        Company = pool.get('company.company')
        FiscalYear = pool.get('account.fiscalyear')
        Period = pool.get('account.period')
        Account = pool.get('account.account')
        Party = pool.get('party.party')
        Line = pool.get('account.move.line')
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')
        try:
            Origin = pool.get('account.bank.statement.line')
        except:
            Origin = None
        try:
            BankLine = pool.get('account.bank.statement.line')
        except:
            BankLine = None

        def _get_key(currentKey):
            party = (currentKey[1].name if len(currentKey) > 1
                and currentKey[1] else 'None')
            return (currentKey[0].code, party)

        fiscalyear = (FiscalYear(data['fiscalyear']) if data.get('fiscalyear')
            else None)
        start_period = None
        if data['start_period']:
            start_period = Period(data['start_period'])
        end_period = None
        if data['end_period']:
            end_period = Period(data['end_period'])
        start_date = data.get('start_date', None)
        end_date = data.get('end_date', None)
        with Transaction().set_context(active_test=False):
            accounts = Account.browse(data.get('accounts', []))
            parties = Party.browse(data.get('parties', []))
            if accounts:
                accounts_subtitle = []
                for x in accounts:
                    if len(accounts_subtitle) > 4:
                        accounts_subtitle.append('...')
                        break
                    accounts_subtitle.append(x.code)
                accounts_subtitle = ', '.join(accounts_subtitle)
            else:
                accounts_subtitle = ''

            if parties:
                parties_subtitle = []
                for x in parties:
                    if len(parties_subtitle) > 4:
                        parties_subtitle.append('...')
                        break
                    parties_subtitle.append(x.name)
                parties_subtitle = '; '.join(parties_subtitle)
            else:
                parties_subtitle = ''

        if data['company']:
            company = Company(data['company'])
        elif fiscalyear:
            company = fiscalyear.company
        else:
            company = Company(Transaction().context.get('company', -1))

        parameters = {}
        parameters['company'] = company.rec_name
        parameters['company_vat'] = (company.party.tax_identifier
            and company.party.tax_identifier.code) or ''
        parameters['start_period'] = start_period and start_period or ''
        parameters['end_period'] = end_period and end_period or ''
        parameters['start_date'] = (start_date.strftime('%d/%m/%Y')
            if start_date else '')
        parameters['end_date'] = (end_date.strftime('%d/%m/%Y')
            if end_date else '')
        parameters['fiscal_year'] = fiscalyear.rec_name if fiscalyear else ''
        parameters['accounts'] = accounts_subtitle
        parameters['parties'] = parties_subtitle
        parameters['show_description'] = data.get('show_description', True)

        where = ''
        if accounts:
            where += "aml.account in (%s) " % (
                ",".join([str(a.id) for a in accounts]))
        else:
            where += "aa.parent is not null "

        if start_date:
            where += "and am.company = %s " % company.id
            where += "and am.date >= '%s' " % start_date
            where += "and am.date <= '%s' " % end_date
        else:
            filter_periods = fiscalyear.get_periods(start_period, end_period)
            where += "and am.period in (%s) " % (
                ",".join([str(a.id) for a in filter_periods]))

        if parties:
            where += " and aml.party in (%s)" % (
                ",".join([str(a.id) for a in parties]))

        cursor = Transaction().connection.cursor()
        cursor.execute("""
            SELECT
                aml.id
            FROM
                account_move_line aml,
                account_move am,
                account_account aa,
                account_account_type aat
            WHERE
                am.id = aml.move AND
                aa.id = aml.account AND
                aa.type = aat.id AND
                %s
            ORDER BY
                aml.account,
                -- Sort by party only when account is of
                -- type 'receivable' or 'payable'
                -- or party_requierd is True
                CASE WHEN aat.receivable or aat.payable or
                    aa.party_required THEN aml.party ELSE 0 END,
                am.date,
                am.id,
                am.description,
                aml.id
            """ % where)
        line_ids = [x[0] for x in cursor.fetchall()]

        if not start_date:
            start_date = (start_period.start_date if start_period
                else fiscalyear.start_date)
        initial_balance_date = start_date - timedelta(days=1)
        with Transaction().set_context(date=initial_balance_date):
            init_values = {}
            if not parties:
                init_values = Account.html_read_account_vals(accounts, company,
                    with_moves=False, exclude_party_moves=True,
                    final_accounts=data.get('final_accounts', False))
            init_party_values = Party.html_get_account_values_by_party(
                parties, accounts, company)
            init_parties = set([p for a, av in init_party_values.items()
                    for p, pv in av.items() if p is not None])
        records = {}
        parties_general_ledger = set() # (account_id, party_id)
        lastKey = None
        sequence = 0
        accounts_w_moves = []
        # Add the asked period/date lines in records
        for group_lines in grouped_slice(line_ids):
            checker.check()
            balance = _ZERO
            init_balance = _ZERO
            init_party_balance = _ZERO
            for line in Line.browse(group_lines):
                if line.account not in accounts_w_moves:
                    accounts_w_moves.append(line.account.id)
                currentKey = (line.account, line.party)
                if lastKey != currentKey:
                    balance = _ZERO
                    lastKey = currentKey
                    account_id = currentKey[0].id
                    party_id = (currentKey[1].id if len(currentKey) > 1
                        and currentKey[1] else None)
                    parties_general_ledger.add((account_id, party_id))
                    init_balance = init_values.get(line.account.id,
                        {}).get('balance', _ZERO)
                    init_party_balance = init_party_values.get(account_id,
                        {}).get(party_id, {}).get('balance', _ZERO)

                credit = line.credit
                debit = line.debit
                balance += line.debit - line.credit
                if init_party_balance:
                    balance += init_party_balance
                    init_party_balance = _ZERO
                elif init_balance:
                    balance += init_balance
                    init_balance = _ZERO
                sequence += 1

                party = None
                ref = None

                if line.origin and isinstance(line.origin, InvoiceLine):
                    ref = cls._ref_origin_invoice_line(line)

                    # If the account have the check "party_required", try to
                    # get from the invoice
                    if line.account.party_required:
                        party = line.origin.invoice.party
                elif (line.move_origin
                        and isinstance(line.move_origin, Invoice)):
                    ref = cls._ref_origin_invoice(line)

                    # If the account have the check "party_required", try to
                    # get from the invoice
                    if line.account.party_required:
                        party = line.move_origin.party
                elif (line.origin and Origin
                        and isinstance(line.origin, Origin)):
                    ref = cls._ref_origin_bank_line(line)
                elif (line.origin and BankLine
                        and isinstance(line.origin, BankLine)):
                    ref = cls._ref_origin_bank_line(line)
                elif line.origin:
                    ref = cls._ref_origin(line)
                else:
                    ref = cls._ref_move_origin(line)

                # If we don't fill the party in a party_required account, try
                # get the party field in the line
                if line.account.party_required and not party:
                    party = line.party

                rline = {
                    'sequence': sequence,
                    'line': line,
                    'ref': ref,
                    'credit': credit,
                    'debit': debit,
                    'balance': balance,
                    'party': party
                    }

                key = _get_key(currentKey)
                if records.get(key):
                    records[key]['lines'].append(rline)
                    records[key]['total_debit'] += debit
                    records[key]['total_credit'] += credit
                else:
                    previous_balance = init_values.get(
                        line.account.id, {}).get('balance', _ZERO)
                    if not previous_balance and line.party:
                        previous_balance = init_party_values.get(
                            line.account.id, {}).get(line.party.id, {}).get(
                                'balance', _ZERO)
                    records[key] = {
                        'account': line.account.name,
                        'code': line.account.code or str(line.account.id),
                        'party': line.party.name if line.party else None,
                        'party_required': line.account.party_required,
                        'lines': [rline],
                        'previous_balance': previous_balance,
                        'total_debit': debit,
                        'total_credit': credit,
                        }

        # Control if there are some party moves with initial value, but not
        # values in the current period control moves and must be to set.
        missing_init_parties = list(
            set(init_parties) - set([p[1] for p in parties_general_ledger]))
        if missing_init_parties:
            account_ids = [k for k, _ in init_party_values.items()]
            accounts = dict((a.id, a) for a in Account.browse(account_ids))
            for k, v in init_party_values.items():
                account = accounts[k]
                for p, z in v.items():
                    if p not in missing_init_parties:
                        continue
                    party = Party(p) if p else None
                    if not party:
                        continue
                    currentKey = (account, party)
                    credit = z.get('credit', _ZERO)
                    debit = z.get('debit', _ZERO)
                    balance = z.get('balance', _ZERO)
                    if balance == _ZERO:
                        continue
                    sequence += 1
                    rline = {
                        'sequence': sequence,
                        'line': None,
                        'ref': None,
                        'credit': credit,
                        'debit': debit,
                        'balance': balance,
                        'party': party
                        }
                    key = _get_key(currentKey)
                    if records.get(key):
                        records[key]['lines'].append(rline)
                        records[key]['total_debit'] += debit
                        records[key]['total_credit'] += credit
                    else:
                        records[key] = {
                            'account': account.name,
                            'code': account.code or str(account.id),
                            'party': party.name if party else None,
                            'party_required': account.party_required,
                            'lines': [rline],
                            'previous_balance': (balance + credit - debit),
                            'total_debit': debit,
                            'total_credit': credit,
                            }
            checker.check()
        if data.get('all_accounts', True):
            # When all accounts is checked True, meaning that all accounts
            # with and without inital blaance or balance need to be printed.
            # Control if there is a missing account move in the init_values
            # list.
            init_values_account_wo_moves = {
                k: init_values[k] for k in init_values
                if k not in accounts_w_moves}
            for account_id, values in init_values_account_wo_moves.items():
                account = Account(account_id)
                balance = values.get('balance', _ZERO)
                credit = values.get('credit', _ZERO)
                debit = values.get('debit', _ZERO)
                if balance == 0:
                    continue

                currentKey = (account,)
                key = _get_key(currentKey)
                if records.get(key):
                    records[key]['total_debit'] += debit
                    records[key]['total_credit'] += credit
                else:
                    records[key] = {
                        'account': account.name,
                        'code': account.code or str(account.id),
                        'party': None,
                        'party_required': account.party_required,
                        'lines': [],
                        'previous_balance': (balance + credit - debit),
                        'total_debit': debit,
                        'total_credit': credit,
                        }
            checker.check()
            # When all accounts is checked True, meaning that all accounts
            # with and without initla blaance or blaane need to be printed.
            # Control if there is a missing account move in the
            # init_party_values list.
            account_ids = [k for k, _ in init_party_values.items()]
            accounts = dict((a.id, a) for a in Account.browse(account_ids))

            for k, v in init_party_values.items():
                account = accounts[k]
                for p, z in v.items():
                    # check if (account, party) is in current general ledger
                    if (k, p) in parties_general_ledger:
                        continue
                    balance = z.get('balance', _ZERO)
                    if balance == 0:
                        continue
                    party = Party(p)
                    currentKey = (account, party)
                    sequence += 1
                    credit = z.get('credit', _ZERO)
                    debit = z.get('debit', _ZERO)

                    key = _get_key(currentKey)
                    if not records.get(key):
                        records[key] = {
                            'account': account.name,
                            'code': account.code or str(account.id),
                            'lines': [],
                            'party': party.name if party else None,
                            'party_required': account.party_required,
                            'previous_balance': (balance + credit - debit),
                            'total_debit': debit,
                            'total_credit': credit,
                            }
            checker.check()

        return dict(sorted(records.items())), parameters

    @classmethod
    def timeout_exception(cls):
        raise TimeoutException

    @classmethod
    def execute(cls, ids, data):
        Config = Pool().get('account.configuration')

        config = Config(1)
        timeout = data.get('timeout') or config.default_timeout or 300
        checker = TimeoutChecker(timeout, cls.timeout_exception)

        start_prepare = datetime.now()
        with Transaction().set_context(active_test=False):
            try:
                records, parameters = cls.prepare(data, checker)
            except TimeoutException:
                raise UserError(gettext('account_reports.msg_timeout_exception'))
        end_prepare = datetime.now()

        context = Transaction().context.copy()
        context['report_lang'] = Transaction().language
        context['report_translations'] = os.path.join(
                os.path.dirname(__file__), 'translations')
        if timeout:
            context['timeout_report'] = timeout - int((end_prepare - start_prepare).total_seconds())

        with Transaction().set_context(**context):
            return super(GeneralLedgerReport, cls).execute(ids, {
                    'name': 'account_reports.general_ledger',
                    'model': 'account.account',
                    'records': records,
                    'parameters': parameters,
                    'output_format': data.get('output_format', 'pdf'),
                    })
