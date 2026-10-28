# coding=utf-8
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal

from sql.aggregate import Sum
from sql.conditionals import Coalesce

from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.model import ModelView, fields
from trytond.modules.account.exceptions import FiscalYearNotFoundError
from trytond.modules.html_report.engine import render as html_render
from trytond.modules.account_reports.common import (
    AccountReportsPDF, AccountReportsPDFReport)
from trytond.modules.xgettext import _
from trytond.modules.account_reports.xlsx import (
    XlsxReport, save_workbook, convert_str_to_float)
from trytond.pool import Pool, PoolMeta
from trytond.tools import grouped_slice, reduce_ids
from trytond.transaction import Transaction
from trytond.wizard import Button, StateReport, StateView, Wizard
from openpyxl import Workbook



class PrintAbreviatedJournalStart(ModelView):
    'Print Abreviated Journal'
    __name__ = 'account_reports.print_abreviated_journal.start'
    fiscalyear = fields.Many2One('account.fiscalyear', 'Fiscal Year',
        required=True)
    output_format = fields.Selection([
            ('pdf', 'PDF'),
            ('xlsx', 'Excel'),
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
        if self.start.output_format == 'xlsx':
            ActionReport = Pool().get('ir.action.report')
            action_report, = ActionReport.search([
                    ('report_name', '=',
                        'account_reports.abreviated_journal_xlsx'),
                    ])
            action = action_report.action.get_action_value()
        return action, data

    def transition_print_(self):
        return 'end'

class AbreviatedJournalReport(AccountReportsPDFReport):
    __name__ = 'account_reports.abreviated_journal'
    side_margin = 0.3


    @classmethod
    def prepare(cls, data, checker=None):
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
    def _build_pdf(cls, records, p, margin, checker):
        filters = ['%s: %s' % (_('Fiscal Year'), p.get('fiscal_year', ''))]
        if p.get('company_vat'):
            filters.insert(0, '%s: %s' % (_('VAT'), p['company_vat']))
        pdf = AccountReportsPDF(_('Abreviated Journal'), p.get('company_rec_name', ''),
            filters, [_('Code'), _('Account'), _('Debit'), _('Credit')],
            [10, 58, 16, 16], ['L', 'L', 'R', 'R'], margin, checker, orientation='P')
        pdf.add_page()
        current_month = None
        month_debit = month_credit = Decimal(0)
        total_debit = total_credit = Decimal(0)
        subtotal_widths = [sum(pdf.widths[:2])] + pdf.widths[2:]
        for record in records:
            if record['month'] != current_month:
                if current_month is not None:
                    pdf.row(['%s: %s' % (_('Total Period'), current_month),
                        html_render(month_debit), html_render(month_credit)],
                        widths=subtotal_widths, aligns=['R'] * 3, bold=True)
                    pdf.add_page()
                current_month = record['month']
                month_debit = month_credit = Decimal(0)
            pdf.row([record['code'], record['name'], html_render(record['debit']),
                html_render(record['credit'])])
            month_debit += record['debit']
            month_credit += record['credit']
            total_debit += record['debit']
            total_credit += record['credit']
        if current_month is not None:
            pdf.row(['%s: %s' % (_('Total Period'), current_month),
                html_render(month_debit), html_render(month_credit)],
                widths=subtotal_widths, aligns=['R'] * 3, bold=True)
            pdf.row(['', _('Total'), html_render(total_debit),
                html_render(total_credit)], bold=True, bottom=True)
        return bytes(pdf.output())



class AbreviatedJournalXlsxReport(XlsxReport, metaclass=PoolMeta):
    __name__ = 'account_reports.abreviated_journal_xlsx'

    @classmethod
    def get_content(cls, ids, data):
        with Transaction().set_context(active_test=False):
            records, parameters = AbreviatedJournalReport.prepare(data)
        return cls._build_workbook(records, parameters)

    @classmethod
    def _build_workbook(cls, records, parameters):
        wb = Workbook()
        ws = wb.active
        ws.title = _('Abreviated Journal')[:31]

        ws.append([_('Abreviated Journal')])
        ws.append([_('Company:'), parameters.get('company_rec_name', '')])
        if parameters.get('company_vat'):
            ws.append([_('VAT'), parameters['company_vat']])
        ws.append([_('Fiscal Year'), parameters.get('fiscal_year', '')])
        ws.append([])

        ws.append([_('Account'), '', _('Debit'), _('Credit')])
        current_month = None
        month_debit = Decimal(0)
        month_credit = Decimal(0)
        total_debit = Decimal(0)
        total_credit = Decimal(0)
        for record in records:
            if record['month'] != current_month:
                if current_month is not None:
                    ws.append([
                        '%s: %s' % (_('Total Period'), current_month),
                        '',
                        convert_str_to_float(html_render(month_debit)),
                        convert_str_to_float(html_render(month_credit)),
                        ])
                current_month = record['month']
                month_debit = Decimal(0)
                month_credit = Decimal(0)
            ws.append([
                record['code'],
                record['name'],
                convert_str_to_float(html_render(record['debit'])),
                convert_str_to_float(html_render(record['credit'])),
                ])
            month_debit += record['debit']
            month_credit += record['credit']
            total_debit += record['debit']
            total_credit += record['credit']
        if current_month is not None:
            ws.append([
                '%s: %s' % (_('Total Period'), current_month),
                '',
                convert_str_to_float(html_render(month_debit)),
                convert_str_to_float(html_render(month_credit)),
                ])
        ws.append([
            '',
            _('Total'),
            convert_str_to_float(html_render(total_debit)),
            convert_str_to_float(html_render(total_credit)),
            ])
        return save_workbook(wb)
