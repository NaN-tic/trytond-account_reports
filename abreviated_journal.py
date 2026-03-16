# coding=utf-8
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from datetime import datetime
from decimal import Decimal

from dominate.tags import col, colgroup, div, header as header_tag, table, tbody, td, th, thead, tr
from dominate.util import raw
from sql.aggregate import Sum
from sql.conditionals import Coalesce

from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.model import ModelView, fields
from trytond.modules.account.exceptions import FiscalYearNotFoundError
from trytond.modules.html_report.engine import render as html_render
from trytond.modules.html_report.i18n import _
from trytond.modules.html_report.dominate_report import DominateReport
from trytond.pool import Pool
from trytond.tools import grouped_slice, reduce_ids
from trytond.transaction import Transaction
from trytond.wizard import Button, StateReport, StateView, Wizard

from .common import css as common_css


class PrintAbreviatedJournalStart(ModelView):
    'Print Abreviated Journal'
    __name__ = 'account_reports.print_abreviated_journal.start'
    fiscalyear = fields.Many2One('account.fiscalyear', 'Fiscal Year',
        required=True)
    output_format = fields.Selection([
            ('pdf', 'PDF'),
            ('html', 'HTML'),
            ], 'Output Format', required=True)
    display_account = fields.Selection([
            ('bal_all', 'All'),
            ('bal_movement', 'With movements'),
            ], 'Display Accounts', required=True)
    level = fields.Integer('Level', help='Display accounts of this level',
        required=True)
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
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_output_format():
        return 'pdf'

    @staticmethod
    def default_display_account():
        return 'bal_all'

    @staticmethod
    def default_level():
        return 1


class PrintAbreviatedJournal(Wizard):
    'Print Abreviated Journal'
    __name__ = 'account_reports.print_abreviated_journal'
    start = StateView('account_reports.print_abreviated_journal.start',
        'account_reports.print_abreviated_journal_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Print', 'print_', 'tryton-print', default=True),
            ])
    print_ = StateReport('account_reports.abreviated_journal')

    def do_print_(self, action):
        data = {
            'company': self.start.company.id,
            'fiscalyear': self.start.fiscalyear.id,
            'display_account': self.start.display_account,
            'level': self.start.level,
            'output_format': self.start.output_format,
            }
        return action, data

    def transition_print_(self):
        return 'end'


class AbreviatedJournalReport(DominateReport):
    __name__ = 'account_reports.abreviated_journal'
    page_orientation = 'portrait'
    side_margin = 0.3

    @classmethod
    def css(cls, action, data, records):
        return common_css(cls.page_orientation)

    @classmethod
    def css_body(cls, action, data, records):
        css = common_css(cls.page_orientation)
        if data.get('output_format') != 'pdf':
            css += (
                '\nheader { position: static; padding-top: 0; '
                'padding-left: 0; }\n'
            )
        css += (
            '\n.abj-month { page-break-inside: avoid; }\n'
            '.abj-month + .abj-month { page-break-before: always; }\n'
            '.abj-month table, .abj-grand-total { table-layout: fixed; }\n'
            '.abj-code { width: 10%; }\n'
            '.abj-name { width: 58%; }\n'
            '.abj-amount { width: 16%; }\n'
            '.abj-subtotal td, .abj-total td { font-weight: bold; }\n'
        )
        return css

    @classmethod
    def css_header(cls, action, data, records):
        side_margin = (action.html_side_margin
            if action and action.html_side_margin is not None
            else cls.side_margin)
        return (
            '%s\nbody { margin: 0; }\n'
            'header { position: static; padding-top: %scm; padding-left: %scm; '
            'padding-right: %scm; box-sizing: border-box; }\n'
            % (common_css(cls.page_orientation), side_margin, side_margin,
                side_margin)
        )

    @classmethod
    def prepare(cls, data):
        pool = Pool()
        Company = pool.get('company.company')
        Account = pool.get('account.account')
        Move = pool.get('account.move')
        MoveLine = pool.get('account.move.line')
        Period = pool.get('account.period')
        FiscalYear = pool.get('account.fiscalyear')
        line = MoveLine.__table__()
        move = Move.__table__()
        table_a = Account.__table__()
        table_c = Account.__table__()

        fiscalyear = (FiscalYear(data['fiscalyear']) if data.get('fiscalyear')
            else None)
        if not fiscalyear:
            raise UserError(gettext('account_reports.msg_missing_fiscalyear'))

        cursor = Transaction().connection.cursor()

        records = []
        parameters = {
            'company': fiscalyear.company.rec_name,
            'fiscal_year': fiscalyear.rec_name,
        }
        company = Company(data['company']) if data.get('company') else None
        parameters['company_rec_name'] = company.rec_name if company else ''
        parameters['company_vat'] = (
            company and company.party.tax_identifier
            and company.party.tax_identifier.code) or ''

        move_join = 'LEFT'
        if data['display_account'] == 'bal_movement':
            move_join = 'INNER'

        account_ids = []
        with Transaction().set_context(active_test=False):
            for account in Account.search([('company', '=', data['company'])],
                    order=[('code', 'ASC')]):
                if not account.code or not account.parent:
                    continue
                if (len(account.code) == data['level']
                        or account.type is not None
                        and len(account.childs) == 0
                        and len(account.code) < data['level']):
                    account_ids.append(account.id)
            accounts = Account.browse(account_ids)

        group_by = (table_a.id,)
        columns = group_by + (
            Sum(Coalesce(line.debit, 0)).as_('debit'),
            Sum(Coalesce(line.credit, 0)).as_('credit'),
            )
        periods = Period.search([
                ('fiscalyear', '=', fiscalyear),
                ('type', '=', 'standard'),
                ], order=[('start_date', 'ASC')])
        for period in periods:
            all_accounts = {}
            for sub_ids in grouped_slice(account_ids):
                red_sql = reduce_ids(table_a.id, sub_ids)
                cursor.execute(*table_a.join(table_c,
                        condition=(table_c.left >= table_a.left)
                        & (table_c.right <= table_a.right)
                        ).join(line, move_join,
                            condition=line.account == table_c.id
                        ).join(move, move_join,
                            condition=move.id == line.move
                        ).select(
                            *columns,
                            where=red_sql
                            & (Coalesce(move.period, period.id) == period.id),
                            group_by=group_by))

                for row in cursor.fetchall():
                    account_id, debit, credit = row
                    if not isinstance(debit, Decimal):
                        debit = Decimal(str(debit))
                    if not isinstance(credit, Decimal):
                        credit = Decimal(str(credit))
                    all_accounts[account_id] = {
                        'debit': debit,
                        'credit': credit,
                        }
            for account in accounts:
                if account.id in all_accounts:
                    records.append({
                            'month': period.rec_name,
                            'period_date': period.start_date,
                            'code': account.code,
                            'name': account.name,
                            'debit': all_accounts[account.id]['debit'],
                            'credit': all_accounts[account.id]['credit'],
                            })
                elif data['display_account'] == 'bal_all':
                    records.append({
                            'month': period.rec_name,
                            'period_date': period.start_date,
                            'code': account.code,
                            'name': account.name,
                            'debit': Decimal(0),
                            'credit': Decimal(0),
                            })
        return records, parameters

    @classmethod
    def execute(cls, ids, data):
        with Transaction().set_context(active_test=False):
            records, parameters = cls.prepare(data)
        return super().execute(ids, {
                'name': 'account_reports.abreviated_journal',
                'model': 'account.move.line',
                'records': records,
                'parameters': parameters,
                'output_format': data.get('output_format', 'pdf'),
                })

    @classmethod
    def title(cls, action, data, records):
        return _('Abreviated Journal')

    @classmethod
    def header(cls, action, data, records):
        p = data['parameters']
        with header_tag(id='header') as container:
            with table(cls='header-table'):
                with thead():
                    with tr():
                        with td():
                            with div():
                                if p.get('company_rec_name'):
                                    raw('<span class="company-name">%s</span><br/>'
                                        % p['company_rec_name'])
                                if p.get('company_vat'):
                                    raw('%s: %s' % (_('VAT'), p['company_vat']))
                        with td(cls='center'):
                            raw('<span class="header-title">%s</span>'
                                % _('Abreviated Journal'))
                        with td(cls='right'):
                            raw(html_render(datetime.now()))
            with table():
                with tbody():
                    with tr():
                        td(_(
                            'Fiscal Year: %(fiscal_year)s') % {
                                'fiscal_year': p.get('fiscal_year', ''),
                                }, colspan='3')
        return container

    @classmethod
    def body(cls, action, data, records):
        records = data.get('records', [])
        grouped_records = []
        current = None
        current_month = None
        month_debit = Decimal(0)
        month_credit = Decimal(0)
        total_debit = Decimal(0)
        total_credit = Decimal(0)
        for record in records:
            if record['month'] != current_month:
                if current is not None:
                    current['debit'] = month_debit
                    current['credit'] = month_credit
                current_month = record['month']
                month_debit = Decimal(0)
                month_credit = Decimal(0)
                current = {
                    'month': current_month,
                    'records': [],
                    'debit': Decimal(0),
                    'credit': Decimal(0),
                    }
                grouped_records.append(current)
            current['records'].append(record)
            month_debit += record['debit']
            month_credit += record['credit']
            total_debit += record['debit']
            total_credit += record['credit']
        if current is not None:
            current['debit'] = month_debit
            current['credit'] = month_credit

        container = div()
        with container:
            if data.get('output_format') != 'pdf':
                container.add(cls.header(action, data, records))
            for month in grouped_records:
                month_cls = 'abj-month'
                with div(cls=month_cls):
                    with table(cls='condensed'):
                        with colgroup():
                            col(cls='abj-code')
                            col(cls='abj-name')
                            col(cls='abj-amount')
                            col(cls='abj-amount')
                        with thead():
                            tr(
                                th(_('Account'), colspan='2'),
                                th(_('Debit'), cls='text-right abj-amount'),
                                th(_('Credit'), cls='text-right abj-amount'),
                                )
                        with tbody():
                            for record in month['records']:
                                tr(
                                    td(record['code'], cls='abj-code no-wrap'),
                                    td(record['name'], cls='abj-name'),
                                    td(html_render(record['debit']),
                                        cls='text-right abj-amount'),
                                    td(html_render(record['credit']),
                                        cls='text-right abj-amount'),
                                    )
                            tr(
                                td('%s%s' % (_('Total Period: '),
                                    month['month']), colspan='2',
                                    cls='abj-subtotal text-right'),
                                td(html_render(month['debit']),
                                    cls='text-right abj-amount abj-subtotal'),
                                td(html_render(month['credit']),
                                    cls='text-right abj-amount abj-subtotal'),
                                cls='abj-subtotal',
                                )
            if grouped_records:
                with table(cls='condensed abj-grand-total'):
                    with colgroup():
                        col(cls='abj-code')
                        col(cls='abj-name')
                        col(cls='abj-amount')
                        col(cls='abj-amount')
                    with thead():
                        tr(
                            th('', cls='abj-code'),
                            th('', cls='abj-name'),
                            th('', cls='abj-amount'),
                            th('', cls='abj-amount'),
                            )
                    with tbody():
                        tr(
                            td('', cls='abj-code'),
                            td(_('Total'), cls='abj-name abj-total text-right'),
                            td(html_render(total_debit),
                                cls='text-right abj-amount abj-total'),
                            td(html_render(total_credit),
                                cls='text-right abj-amount abj-total'),
                            cls='abj-total',
                            )
        return container
