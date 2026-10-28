# This file is part of account_reports for tryton.  The COPYRIGHT file
# at the top level of this repository contains the full copyright notices and
# license terms.
from datetime import datetime
from decimal import Decimal

from openpyxl import Workbook

from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.model import ModelView, fields
from trytond.modules.account_reports.common import (
    TimeoutChecker, TimeoutException)
from trytond.modules.account_reports.tools import vat_label
from trytond.modules.account_reports.xlsx import XlsxReport, convert_str_to_float, save_workbook
from trytond.modules.html_report.engine import render as html_render
from trytond.modules.account_reports.common import (
    AccountReportsPDF, AccountReportsPDFReport)
from trytond.modules.xgettext import _
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.rpc import RPC
from trytond.tools import grouped_slice
from trytond.transaction import Transaction
from trytond.wizard import Button, StateReport, StateView, Wizard

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
        return config.default_timeout or 60

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
        if self.start.output_format == 'xlsx':
            ActionReport = Pool().get('ir.action.report')
            action_report, = ActionReport.search([
                    ('report_name', '=', 'account_reports.open_move_lines_xlsx'),
                    ])
            action = action_report.action.get_action_value()
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

class OpenMoveLinesReport(AccountReportsPDFReport):
    __name__ = 'account_reports.open_move_lines'

    @classmethod
    def __setup__(cls):
        super().__setup__()
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
    def _ref_origin(cls, line):
        return (line.origin.rec_name if line.origin
            and hasattr(line.origin, 'rec_name') else None)

    @classmethod
    def _ref(cls, line):
        ref = line.description_used or line.move_description_used or None
        return (ref if ref else (line.move_origin.rec_name if line.move_origin
                and hasattr(line.move_origin, 'rec_name') else None))

    @classmethod
    def _resolved_party(cls, line, invoice_model):
        party = None
        if line.account.party_required and line.origin:
            invoice = getattr(line.origin, 'invoice', None)
            if invoice and isinstance(invoice, invoice_model):
                party = invoice.party
        if line.account.party_required and not party and line.move_origin:
            if isinstance(line.move_origin, invoice_model):
                party = line.move_origin.party
        return party or line.party

    @classmethod
    def prepare(cls, data, checker):
        pool = Pool()
        Account = pool.get('account.account')
        Company = pool.get('company.company')
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')
        Party = pool.get('party.party')
        Line = pool.get('account.move.line')
        try:
            BankLine = pool.get('account.bank.statement.line')
        except Exception:
            BankLine = None

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
                party = cls._resolved_party(line, Invoice)
                current_key = (line.account, party)
                if current_key != last_key:
                    balance = _ZERO
                    last_key = current_key
                balance += line.debit - line.credit
                sequence += 1

                if line.origin and isinstance(line.origin, InvoiceLine):
                    ref = cls._ref_origin_invoice_line(line)
                elif line.move_origin and isinstance(line.move_origin, Invoice):
                    ref = cls._ref_origin_invoice(line)
                elif line.origin and BankLine and isinstance(line.origin, BankLine):
                    ref = cls._ref_origin_bank_line(line)
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
    def timeout_exception(cls):
        raise TimeoutException


    @classmethod
    def _build_pdf(cls, records, p, margin, checker):
        filters = ['%s: %s' % (p['company_vat_label'], p['company_vat']),
            _('Cut-off Date: %s') % p['date'],
            _('Parties: %s') % p['parties'] if p['parties'] else _('All Parties'),
            _('Accounts: %s') % p['accounts'] if p['accounts'] else _('All Accounts')]
        pdf = AccountReportsPDF(_('Open Move Lines'), p['company'], filters,
            [_('Date'), _('Maturity Date'), _('Number'),
                _('Reference // Description'), _('Reconciliation Date'),
                _('Debit'), _('Credit'), _('Balance')],
            [8, 8, 10, 33, 11, 10, 10, 10], ['L'] * 5 + ['R'] * 3,
            margin, checker)
        pdf.add_page()
        widths = pdf.widths
        group_widths = [sum(widths[:2]), sum(widths[2:4]),
            sum(widths[4:7]), widths[7]]
        show_description = p.get('show_description', True)
        for record in records.values():
            pdf.row([record['code'], record['party'] or record['account'], '',
                html_render(record['total_balance'])], bold=True, fill=True,
                widths=group_widths, aligns=['L', 'L', 'L', 'R'])
            for info in record['lines']:
                line = info['line']
                number = (line.move.number or '(#%s)' % line.move.id
                    if line.move else '')
                description = info['ref'] or ''
                detail = line.description or line.move_description_used
                if show_description and detail:
                    if description:
                        description += ' // '
                    description += detail
                pdf.row([html_render(line.date), html_render(line.maturity_date),
                    number, description,
                    html_render(line.reconciliation.date)
                        if line.reconciliation else '']
                    + [html_render(info[key]) for key in ('debit', 'credit', 'balance')])
            pdf.row([record['code'], record['party'] or record['account'],
                _('Total'), html_render(record['total_balance'])], bold=True,
                widths=group_widths, aligns=['L', 'L', 'L', 'R'], bottom=True)
        return bytes(pdf.output())



class OpenMoveLinesXlsxReport(XlsxReport, metaclass=PoolMeta):
    __name__ = 'account_reports.open_move_lines_xlsx'

    @classmethod
    def get_content(cls, ids, data):
        pool = Pool()
        Config = pool.get('account.configuration')

        config = Config(1)
        timeout = data.get('timeout') or config.default_timeout or 300
        checker = TimeoutChecker(timeout, OpenMoveLinesReport.timeout_exception)

        start_prepare = datetime.now()
        with Transaction().set_context(active_test=False):
            try:
                records, parameters = OpenMoveLinesReport.prepare(data, checker)
            except TimeoutException:
                raise UserError(gettext('account_reports.msg_timeout_exception'))
        end_prepare = datetime.now()

        context = cls._xlsx_context()
        if timeout:
            context['timeout_report'] = (
                timeout - int((end_prepare - start_prepare).total_seconds()))

        with Transaction().set_context(**context):
            return cls._build_workbook(records, parameters)

    @classmethod
    def _build_workbook(cls, records, parameters):
        wb = Workbook()
        ws = wb.active
        ws.title = _('Open Move Lines')[:31]

        def xls(value, **kwargs):
            return convert_str_to_float(html_render(value, **kwargs))

        ws.append([parameters['company'], _('Open Move Lines'),
            html_render(datetime.now())])
        ws.append(['%s: %s' % (
            parameters['company_vat_label'], parameters['company_vat'])])
        ws.append([_('Cut-off Date: %s') % parameters['date']])
        if parameters['parties']:
            ws.append([_('Parties: %s') % parameters['parties']])
        else:
            ws.append([_('All Parties')])
        if parameters['accounts']:
            ws.append([_('Accounts: %s') % parameters['accounts']])
        else:
            ws.append([_('All Accounts')])
        ws.append([])

        ws.append([
            _('Date'),
            _('Maturity Date'),
            _('Number'),
            _('Reference // Description'),
            _('Reconciliation Date'),
            _('Debit'),
            _('Credit'),
            _('Balance'),
            ])

        show_description = parameters.get('show_description', True)
        for record in records.values():
            ws.append([
                record['code'],
                '',
                record['party'] or record['account'],
                '',
                '',
                '',
                '',
                xls(record['total_balance']),
                ])
            for line_info in record['lines']:
                line = line_info['line']
                if line.move and line.move.number:
                    number = line.move.number
                elif line.move:
                    number = '(#%s)' % line.move.id
                else:
                    number = ''
                description = ''
                if line_info['ref']:
                    description += line_info['ref']
                if (line_info['ref'] and show_description
                        and (line.description or line.move_description_used)):
                    description += ' // '
                if show_description and line.description:
                    description += line.description
                elif show_description and line.move_description_used:
                    description += line.move_description_used
                ws.append([
                    html_render(line.date),
                    html_render(line.maturity_date) if line.maturity_date else '',
                    number,
                    description,
                    (html_render(line.reconciliation.date)
                        if line.reconciliation else ''),
                    xls(line_info['debit']),
                    xls(line_info['credit']),
                    xls(line_info['balance']),
                    ])
            ws.append([
                record['code'],
                '',
                record['party'] or record['account'],
                '',
                _('Total'),
                '',
                '',
                xls(record['total_balance']),
                ])
            ws.append([])
        return save_workbook(wb)
