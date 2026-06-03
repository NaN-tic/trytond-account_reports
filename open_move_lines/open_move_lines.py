# This file is part of account_reports for tryton.  The COPYRIGHT file
# at the top level of this repository contains the full copyright notices and
# license terms.
import os
from datetime import datetime
from decimal import Decimal

from trytond.model import ModelView, fields
from trytond.pyson import Eval
from trytond.modules.account_reports.common import TimeoutException
from trytond.modules.account_reports.common import TimeoutChecker
from trytond.modules.account_reports.tools import vat_label
from trytond.pool import Pool
from trytond.rpc import RPC
from trytond.tools import grouped_slice
from trytond.transaction import Transaction
from trytond.wizard import Button, StateReport, StateView, Wizard
from trytond.i18n import gettext
from trytond.exceptions import UserError

from ..general_ledger.general_ledger import GeneralLedgerReport

_ZERO = Decimal(0)


class PrintOpenMoveLinesStart(ModelView):
    'Print Open Move Lines'
    __name__ = 'account_reports.print_open_move_lines.start'

    date = fields.Date('Cut-off Date', required=True)
    accounts = fields.Many2Many('account.account', None, None, 'Accounts',
        domain=[
            ('company', '=', Eval('company', -1)),
            ('reconcile', '=', True),
            ],
        depends=['company'])
    parties = fields.Many2Many('party.party', None, None, 'Parties',
        context={
            'company': Eval('company', -1),
            },
        depends=['company'])
    output_format = fields.Selection([
            ('pdf', 'PDF'),
            ('html', 'HTML'),
            ('xlsx', 'Excel'),
            ], 'Output Format', required=True)
    company = fields.Many2One('company.company', 'Company', required=True)
    timeout = fields.Integer('Timeout (s)', required=True, help='If report '
        'calculation should take more than the specified timeout (in seconds) '
        'the process will be stopped automatically.')
    show_description = fields.Boolean('Show Description',
        help='If checked show description from Account Move Line')

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_date():
        Date = Pool().get('ir.date')
        return Date.today()

    @staticmethod
    def default_output_format():
        return 'pdf'

    @staticmethod
    def default_timeout():
        Config = Pool().get('account.configuration')
        config = Config(1)
        return config.default_timeout or 30

    @staticmethod
    def default_show_description():
        return False


class PrintOpenMoveLines(Wizard):
    'Print Open Move Lines'
    __name__ = 'account_reports.print_open_move_lines'

    start = StateView('account_reports.print_open_move_lines.start',
        'account_reports.print_open_move_lines_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Print', 'print_', 'tryton-print', default=True),
            ])
    print_ = StateReport('account_reports.open_move_lines')

    def do_print_(self, action):
        data = {
            'company': self.start.company.id,
            'date': self.start.date,
            'accounts': [x.id for x in self.start.accounts],
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
                if party.account_payable and party.account_payable.reconcile:
                    account_ids.append(party.account_payable.id)
                if (party.account_receivable
                        and party.account_receivable.reconcile):
                    account_ids.append(party.account_receivable.id)
                party_ids.append(party.id)
        return {
            'accounts': list(set(account_ids)),
            'parties': party_ids,
            }


class OpenMoveLinesReport(GeneralLedgerReport):
    __name__ = 'account_reports.open_move_lines'

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__rpc__['execute'] = RPC(False)
        cls.side_margin = 0.3

    @classmethod
    def _resolved_party(cls, line):
        party = None
        if line.account.party_required and line.origin:
            invoice = getattr(line.origin, 'invoice', None)
            if invoice:
                party = invoice.party
        if line.account.party_required and not party and line.move_origin:
            party = getattr(line.move_origin, 'party', None)
        return party or line.party

    @classmethod
    def prepare(cls, data, checker):
        pool = Pool()
        Account = pool.get('account.account')
        Company = pool.get('company.company')
        Party = pool.get('party.party')
        Line = pool.get('account.move.line')

        cutoff_date = data['date']
        with Transaction().set_context(active_test=False):
            accounts = Account.browse(data.get('accounts', []))
            parties = Party.browse(data.get('parties', []))
            if accounts:
                accounts_subtitle = []
                for account in accounts:
                    if len(accounts_subtitle) > 4:
                        accounts_subtitle.append('...')
                        break
                    accounts_subtitle.append(account.code)
                accounts_subtitle = ', '.join(accounts_subtitle)
            else:
                accounts_subtitle = ''
            if parties:
                parties_subtitle = []
                for party in parties:
                    if len(parties_subtitle) > 4:
                        parties_subtitle.append('...')
                        break
                    parties_subtitle.append(party.name)
                parties_subtitle = '; '.join(parties_subtitle)
            else:
                parties_subtitle = ''

        company = Company(data['company'])
        parameters = {
            'company': company.rec_name,
            'company_vat': ((company.party.tax_identifier
                    and company.party.tax_identifier.code) or ''),
            'company_vat_label': ((company.party.tax_identifier
                    and vat_label(company.party.tax_identifier)) or ''),
            'date': cutoff_date.strftime('%d/%m/%Y'),
            'accounts': accounts_subtitle,
            'parties': parties_subtitle,
            'show_description': data.get('show_description', True),
            }

        domain = [
            ('move.company', '=', company.id),
            ('move.date', '<=', cutoff_date),
            ('account.reconcile', '=', True),
            ['OR',
                ('reconciliation', '=', None),
                ('reconciliation.date', '>', cutoff_date),
                ],
            ]
        if accounts:
            domain.append(('account', 'in', [a.id for a in accounts]))
        if parties:
            domain.append(('party', 'in', [p.id for p in parties]))

        with Transaction().set_context(active_test=False):
            line_ids = [line.id for line in Line.search(domain, order=[
                        ('account', 'ASC'),
                        ('party', 'ASC'),
                        ('move.date', 'ASC'),
                        ('move', 'ASC'),
                        ('id', 'ASC'),
                        ])]

        records = {}
        last_key = None
        balance = _ZERO
        sequence = 0
        for group_lines in grouped_slice(line_ids):
            checker.check()
            for line in Line.browse(group_lines):
                party = cls._resolved_party(line)
                current_key = (line.account, party)
                if current_key != last_key:
                    balance = _ZERO
                    last_key = current_key
                balance += line.debit - line.credit
                sequence += 1

                if line.origin and hasattr(line.origin, 'invoice'):
                    ref = cls._ref_origin_invoice_line(line)
                elif line.move_origin and hasattr(line.move_origin, 'party'):
                    ref = cls._ref_origin_invoice(line)
                elif line.origin:
                    ref = cls._ref_origin(line)
                else:
                    ref = cls._ref(line)
                if not ref:
                    ref = cls._ref(line)

                key = (
                    line.account.code or str(line.account.id),
                    party.name if party else '',
                    )
                record = records.setdefault(key, {
                        'account': line.account.name,
                        'code': line.account.code or str(line.account.id),
                        'party': party.name if party else '',
                        'lines': [],
                        'total_debit': _ZERO,
                        'total_credit': _ZERO,
                        'total_balance': _ZERO,
                        })
                record['lines'].append({
                        'sequence': sequence,
                        'line': line,
                        'ref': ref,
                        'debit': line.debit,
                        'credit': line.credit,
                        'balance': balance,
                        })
                record['total_debit'] += line.debit
                record['total_credit'] += line.credit
                record['total_balance'] += line.debit - line.credit
        return dict(sorted(records.items())), parameters

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
            context['timeout_report'] = (
                timeout - int((end_prepare - start_prepare).total_seconds()))

        with Transaction().set_context(**context):
            return super(GeneralLedgerReport, cls).execute(ids, {
                    'name': 'account_reports.open_move_lines',
                    'model': 'account.move.line',
                    'records': records,
                    'parameters': parameters,
                    'output_format': data.get('output_format', 'pdf'),
                    })
