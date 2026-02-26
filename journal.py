# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateView, StateReport, Button
from trytond.pyson import Eval, If, Bool
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.modules.account_reports.xlsx import (
    XlsxReport, save_workbook, convert_str_to_float)
from trytond.modules.html_report.dominate_report import DominateReport
from datetime import timedelta
from sql import Null
from trytond.modules.account.exceptions import FiscalYearNotFoundError
from openpyxl import Workbook
from dominate.tags import div, h1, p, table, thead, tbody, tr, td, th

from .common import css as common_css


class PrintJournalStart(ModelView):
    'Print Journal'
    __name__ = 'account_reports.print_journal.start'
    fiscalyear = fields.Many2One('account.fiscalyear', 'Fiscal Year',
            required=True)
    start_period = fields.Many2One('account.period', 'Start Period',
        required=True,
        domain=[
            ('fiscalyear', '=', Eval('fiscalyear')),
            If(Bool(Eval('end_period')),
                ('start_date', '<=', (Eval('end_period'), 'start_date')),
                (),
                )
            ])
    end_period = fields.Many2One('account.period', 'End Period',
        domain=[
            ('fiscalyear', '=', Eval('fiscalyear')),
            If(Bool(Eval('start_period')),
                ('start_date', '>=', (Eval('start_period'), 'start_date')),
                (),
                )
            ])
    open_close_account_moves = fields.Boolean('Create Open/Close Moves',
        help="If this field is checked and Start Period is 01 and the fiscal "
        "year before are closed, an open move of this year will be created. "
        "And if 12 is in End Period and the fiscal year are closed a "
        "close move of the year are created. And will use all journals.")
    open_move_description = fields.Char('Open Move Description',
        states={
            'invisible': ~Bool(Eval('open_close_account_moves')),
            })
    close_move_description = fields.Char('Close Move Description',
        states={
            'invisible': ~Bool(Eval('open_close_account_moves')),
            })
    journals = fields.Many2Many('account.journal', None, None, 'Journals',
        states={
            'readonly': Bool(Eval('open_close_account_moves')),
            },
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

    @fields.depends('fiscalyear')
    def on_change_fiscalyear(self):
        self.start_period = None
        self.end_period = None


class PrintJournal(Wizard):
    'Print Journal'
    __name__ = 'account_reports.print_journal'
    start = StateView('account_reports.print_journal.start',
        'account_reports.print_journal_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Print', 'print_', 'tryton-print', default=True),
            ])
    print_ = StateReport('account_reports.journal')

    def do_print_(self, action):
        start_period = self.start.fiscalyear.periods[0].id
        if self.start.start_period:
            start_period = self.start.start_period.id
        end_period = self.start.fiscalyear.periods[-1].id
        if self.start.end_period:
            end_period = self.start.end_period.id
        data = {
            'company': self.start.company.id,
            'open_close_account_moves': self.start.open_close_account_moves,
            'open_move_description': self.start.open_move_description,
            'close_move_description': self.start.close_move_description,
            'fiscalyear': self.start.fiscalyear.id,
            'start_period': start_period,
            'end_period': end_period,
            'journals': [x.id for x in self.start.journals],
            'output_format': self.start.output_format,
            }
        if self.start.output_format == 'xlsx':
            ActionReport = Pool().get('ir.action.report')
            action, = ActionReport.search([
                    ('report_name', '=', 'account_reports.journal_xlsx'),
                    ])
        return action, data

    def transition_print_(self):
        return 'end'


class JournalReport(DominateReport):
    __name__ = 'account_reports.journal'

    @classmethod
    def css(cls, action, data, records):
        return common_css()

    @classmethod
    def css_header(cls, action, data, records):
        side_margin = (action.html_side_margin
            if action and action.html_side_margin is not None
            else cls.side_margin)
        return (
            '%s\nbody { margin: %scm %scm 0 %scm; }\n'
            'header { padding: 0; width: 100%%; box-sizing: border-box; }\n'
            % (common_css(), side_margin, side_margin, side_margin)
        )

    @classmethod
    def _get_open_close_moves(cls, _type, description, fiscalyear, accounts,
            init_values, init_party_values, line):
        pool = Pool()
        Party = pool.get('party.party')
        Line = pool.get('account.move.line')
        Sequence = pool.get('ir.sequence')

        move = Line(line).move
        sequence = Sequence.search([
                ('id', '=', move.period.post_move_sequence_used.id),
                ])[0]
        sequence_prefix = Sequence._process(sequence.prefix, date=move.date)
        sequence_sufix = Sequence._process(sequence.suffix, date=move.date)
        number = move.number.replace(sequence_prefix, '').replace(
            sequence_sufix, '')

        try:
            number = int(number)
        except ValueError:
            pass
        if not isinstance(number, int):
            # In case sequence changed prefix or suffix and not equal from number
            raise  UserError(gettext('account_jasper_reports.msg_renumber_move',
                sequence=sequence.rec_name, move=move.rec_name))

        if _type == 'open':
            number = int(number) - 1
        else:
            number = int(number) + 1
        number = '%%0%sd' % sequence.padding % number
        move_number = '%s%s%s' % (
            sequence_prefix,
            number,
            sequence_sufix,
        )

        moves = []
        for account in accounts:
            account_type = 'other'
            if account.type.receivable:
                account_type = 'receivable'
            elif account.type.payable:
                account_type = 'payable'

            main_value = {}
            if _type == 'open':
                main_value['date'] = fiscalyear.start_date.strftime("%Y-%m-%d")
                main_value['month'] = fiscalyear.start_date.month
                main_value['move_number'] = move_number
                main_value['move_line_description'] = description
            else:
                main_value['date'] = fiscalyear.end_date.strftime("%Y-%m-%d")
                main_value['month'] = fiscalyear.end_date.month
                main_value['move_number'] = move_number
                main_value['move_line_description'] = description
            main_value['account_name'] = account.rec_name
            main_value['account_kind'] = account_type

            value = {}
            value.update(main_value)
            value['party_name'] = ''
            account_values = init_values.get(account.id, None)
            if account_values:
                balance = account_values.get('balance', 0)
                if balance:
                    if _type == 'open':
                        value['debit'] = (float(balance)
                            if balance >= 0 else 0)
                        value['credit'] = (-float(balance)
                            if balance < 0 else 0)
                    else:
                        value['debit'] = (-float(balance)
                            if balance < 0 else 0)
                        value['credit'] = (float(balance)
                            if balance >= 0 else 0)
                    moves.append(value)

            parties = init_party_values.get(account.id, None)
            if parties:
                for party_id, values in parties.items():
                    balance = values.get('balance', 0)
                    if balance:
                        value = {}
                        value.update(main_value)
                        if _type == 'open':
                            value['debit'] = (float(balance)
                                if balance >= 0 else 0)
                            value['credit'] = (-float(balance)
                                if balance < 0 else 0)
                        else:
                            value['debit'] = (-float(balance)
                                if balance < 0 else 0)
                            value['credit'] = (float(balance)
                                if balance >= 0 else 0)
                        value['party_name'] = Party(party_id).rec_name
                        moves.append(value)
        return moves

    @classmethod
    def prepare(cls, data):
        pool = Pool()
        Company = pool.get('company.company')
        FiscalYear = pool.get('account.fiscalyear')
        Account = pool.get('account.account')
        Party = pool.get('party.party')
        Journal = pool.get('account.journal')
        Period = pool.get('account.period')
        Line = pool.get('account.move.line')

        parameters = {}
        fiscalyear = FiscalYear(data['fiscalyear'])
        start_period = None
        if data['start_period']:
            start_period = Period(data['start_period'])
        end_period = None
        if data['end_period']:
            end_period = Period(data['end_period'])
        if data.get('open_close_account_moves'):
            journals = Journal.browse([])
        else:
            journals = Journal.browse(data.get('journals', []))

        company = None
        if data['company']:
            company = Company(data['company'])
        parameters['company_rec_name'] = company and company.rec_name or ''
        parameters['company_vat'] = (company
            and company.party.tax_identifier and
            company.party.tax_identifier.code) or ''

        parameters['start_period'] = start_period and start_period.name or ''
        parameters['end_period'] = end_period and end_period.name or ''
        parameters['fiscal_year'] = fiscalyear.name
        if journals:
            parameters['journals'] = ','.join([x.name for x in journals])
        else:
            parameters['journals'] = ''

        if journals:
            journal_ids = ','.join([str(x.id) for x in journals])
            journals_domain = 'am.journal IN (%s) AND' % journal_ids
        else:
            journals_domain = ''

        periods = fiscalyear.get_periods(start_period, end_period)
        if periods:
            period_ids = ','.join([str(x.id) for x in periods])
            periods_domain = 'am.period IN (%s) AND' % period_ids
        else:
            periods_domain = ''

        cursor = Transaction().connection.cursor()
        cursor.execute("""
            SELECT
                aml.id
            FROM
                account_move am,
                account_move_line aml
            WHERE
                %s
                %s
                am.id=aml.move
            ORDER BY
                am.date, am.number, aml.id
        """ % (
                journals_domain,
                periods_domain,
                ))
        ids = [x[0] for x in cursor.fetchall()]

        open_moves = []
        close_moves = []
        # Prepare structure for the open/close move, if it's needed.
        if data.get('open_close_account_moves'):
            # First check if fiscal year before are closed
            fiscalyear_before_start_date = fiscalyear.start_date.replace(
                year = fiscalyear.start_date.year - 1)
            fiscalyear_before_end_date = fiscalyear.end_date.replace(
                year = fiscalyear.start_date.year - 1)
            fiscalyear_before = FiscalYear.search([
                    ('start_date', '=', fiscalyear_before_start_date),
                    ('end_date', '=', fiscalyear_before_end_date),
                    ])
            fiscalyear_before = (fiscalyear_before and fiscalyear_before[0] or
                None)

            with Transaction().set_context(active_test=False):
                accounts = Account.search([
                        ('company', '=', company),
                        ('parent', '!=', None),
                        ('type', '!=', Null),
                        ('active', 'in', [True, False]),
                        ])
                parties = Party.search([
                        ('active', 'in', [True, False]),
                        ])

            if fiscalyear_before and fiscalyear_before.state == 'closed':
                # check if the first month is the same of the start month on
                #    fiscal year before
                if (start_period.start_date and
                        start_period.start_date.month ==
                        fiscalyear_before.start_date.month):
                    initial_balance_date = (
                        start_period.start_date - timedelta(days=1))
                    with Transaction().set_context(date=initial_balance_date):
                        init_values = Account.read_account_vals(accounts,
                            with_moves=True, exclude_party_moves=True)
                        init_party_values = Party.get_account_values_by_party(
                            parties, accounts, fiscalyear.company)

                    open_moves.extend(cls._get_open_close_moves('open',
                        data.get('open_move_description'), fiscalyear,
                        accounts, init_values, init_party_values, ids[0]))

            if fiscalyear.state =='closed':
                # check if the last month is the same of the end month on
                #    fiscal year
                if (end_period.end_date and end_period.end_date.month ==
                        fiscalyear.end_date.month):
                    with Transaction().set_context(date=end_period.end_date):
                        init_values = Account.read_account_vals(accounts,
                            with_moves=True, exclude_party_moves=True)
                        init_party_values = Party.get_account_values_by_party(
                            parties, accounts, fiscalyear.company)

                    close_moves.extend(cls._get_open_close_moves('close',
                        data.get('close_move_description'), fiscalyear,
                        accounts, init_values, init_party_values, ids[-1]))

        records = []
        records.extend(open_moves)
        for line in Line.browse(ids):
            account_type = 'other'
            if line.account.type.receivable:
                account_type = 'receivable'
            elif line.account.type.payable:
                account_type = 'payable'

            records.append({
                    'date': line.date,
                    'month': line.date.month,
                    'account_name': line.account.rec_name,
                    'move_number': line.move.number,
                    'move_line_description': line.description,
                    'debit': line.debit,
                    'credit': line.credit,
                    'party_name': line.party and line.party.name or '',
                    'account_kind': account_type,
                    })
        return records, parameters

    @classmethod
    def execute(cls, ids, data):
        with Transaction().set_context(active_test=False):
            records, parameters = cls.prepare(data)
        return super().execute(ids, {
            'name': 'account_reports.journal',
            'model': 'account.move.line',
            'records': records,
            'parameters': parameters,
            'output_format': data.get('output_format', 'pdf'),
            })

    @classmethod
    def title(cls, action, data, records):
        return "Journal"

    @classmethod
    def body(cls, action, data, records):
        parameters = data.get('parameters', {})
        records = data.get('records', [])
        container = div()
        with container:
            with div(cls="header"):
                h1("Journal")
                p("Company: " + parameters.get('company_rec_name', ''))
                if parameters.get('company_vat'):
                    p("VAT: " + parameters['company_vat'])
                p("Fiscal Year: " + parameters.get('fiscal_year', ''))
                p("From " + parameters.get('start_period', '') + " To "
                    + parameters.get('end_period', ''))
                if parameters.get('journals'):
                    p("Journals: " + parameters['journals'])
            with table(cls="journal-table"):
                with thead():
                    tr(th("Date"), th("Move"), th("Account / Party"),
                        th("Description"), th("Debit"), th("Credit"))
                with tbody():
                    current_month = None
                    month_debit = 0
                    month_credit = 0
                    for record in records:
                        if record['month'] != current_month:
                            if current_month is not None:
                                tr(td("", colspan="3"),
                                    td("Total month {}".format(current_month)),
                                    td("{:.2f}".format(month_debit)),
                                    td("{:.2f}".format(month_credit)),
                                    cls="month-total")
                            current_month = record['month']
                            month_debit = 0
                            month_credit = 0
                        account_party = record['account_name']
                        if record['party_name']:
                            account_party += " / " + record['party_name']
                        tr(td(str(record['date'])),
                            td(record['move_number']),
                            td(account_party),
                            td(record.get('move_line_description') or ''),
                            td("{:.2f}".format(float(record['debit']))),
                            td("{:.2f}".format(float(record['credit']))))
                        month_debit += record['debit']
                        month_credit += record['credit']
                    if current_month is not None:
                        tr(td("", colspan="3"),
                            td("Total month {}".format(current_month)),
                            td("{:.2f}".format(month_debit)),
                            td("{:.2f}".format(month_credit)),
                            cls="month-total")
                    total_debit = sum(r['debit'] for r in records)
                    total_credit = sum(r['credit'] for r in records)
                    tr(td("", colspan="3"), td("Total"),
                        td("{:.2f}".format(float(total_debit))),
                        td("{:.2f}".format(float(total_credit))),
                        cls="summary")
            with div(cls="footer"):
                p("When the Move number is between '()' means it hasn't Post "
                    "Number and the shown number is the provisional one.")
        return container


class JournalXlsxReport(XlsxReport, metaclass=PoolMeta):
    __name__ = 'account_reports.journal_xlsx'

    @classmethod
    def get_content(cls, ids, data):
        with Transaction().set_context(active_test=False):
            records, parameters = JournalReport.prepare(data)
        return cls._build_workbook(records, parameters)

    @classmethod
    def _build_workbook(cls, records, parameters):
        wb = Workbook()
        ws = wb.active
        ws.title = "Journal"[:31]

        ws.append(["Journal"])
        ws.append(["Company:", parameters.get('company_rec_name', '')])
        if parameters.get('company_vat'):
            ws.append(["VAT:", parameters['company_vat']])
        ws.append(["Fiscal Year:", parameters.get('fiscal_year', '')])
        ws.append(["From", parameters.get('start_period', ''),
            "To", parameters.get('end_period', '')])
        if parameters.get('journals'):
            ws.append(["Journals:", parameters['journals']])
        ws.append([])

        ws.append(["Date", "Move", "Account / Party", "Description",
            "Debit", "Credit"])
        current_month = None
        month_debit = 0
        month_credit = 0
        for record in records:
            if record['month'] != current_month:
                if current_month is not None:
                    ws.append(["", "", "", "Total month {}".format(current_month),
                        convert_str_to_float("{:.2f}".format(month_debit)),
                        convert_str_to_float("{:.2f}".format(month_credit))])
                current_month = record['month']
                month_debit = 0
                month_credit = 0
            account_party = record['account_name']
            if record['party_name']:
                account_party += " / " + record['party_name']
            ws.append([
                str(record['date']),
                record['move_number'],
                account_party,
                record['move_line_description'],
                convert_str_to_float("{:.2f}".format(float(record['debit']))),
                convert_str_to_float("{:.2f}".format(float(record['credit']))),
                ])
            month_debit += record['debit']
            month_credit += record['credit']
        if current_month is not None:
            ws.append(["", "", "", "Total month {}".format(current_month),
                convert_str_to_float("{:.2f}".format(month_debit)),
                convert_str_to_float("{:.2f}".format(month_credit))])
        total_debit = sum(r['debit'] for r in records)
        total_credit = sum(r['credit'] for r in records)
        ws.append(["", "", "", "Total",
            convert_str_to_float("{:.2f}".format(float(total_debit))),
            convert_str_to_float("{:.2f}".format(float(total_credit)))])
        return save_workbook(wb)
