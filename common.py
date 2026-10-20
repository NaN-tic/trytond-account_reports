# This file is part of account_reports for tryton.  The COPYRIGHT file
# at the top level of this repository contains the full copyright notices and
# license terms.
from decimal import Decimal
from pathlib import Path

from fpdf import FPDF
from datetime import datetime
from sql.aggregate import Sum
from sql.conditionals import Coalesce
from sql.operators import In

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.tools import reduce_ids, slugify
from trytond.report import Report
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.modules.html_report.engine import HTMLReportMixin, render
from trytond.transaction import Transaction


class TimeoutException(Exception):
    pass


def report_margin():
    Configuration = Pool().get('account.configuration')
    return Configuration(1).account_reports_margin


class AccountReportsReportMixin:

    @classmethod
    def get_page_margin(cls, action):
        return report_margin()


class TimeoutChecker:
    def __init__(self, timeout, callback):
        self._timeout = timeout
        self._callback = callback
        self._start = datetime.now()

    @property
    def elapsed(self):
        return (datetime.now() - self._start).seconds

    def check(self):
        if self.elapsed > self._timeout:
            self._callback()


class Configuration(metaclass=PoolMeta):
    __name__ = 'account.configuration'
    default_timeout = fields.Integer('Timeout (s)')
    account_reports_margin = fields.Integer('Account Reports Margin (px)')


class FiscalYear(metaclass=PoolMeta):
    __name__ = 'account.fiscalyear'

    def get_periods(self, start_period, end_period):
        pool = Pool()
        Period = pool.get('account.period')
        domain = [('fiscalyear', '=', self)]
        if start_period:
            domain += [('start_date', '>=', start_period.start_date)]
            domain += [('end_date', '>=', start_period.end_date)]
        if end_period:
            domain += [('start_date', '<=', end_period.start_date)]
            domain += [('end_date', '<=', end_period.end_date)]

        periods = Period.search(domain)
        return periods


class AccountTemplate(metaclass=PoolMeta):
    __name__ = 'account.account.template'

    @classmethod
    def __setup__(cls):
        super(AccountTemplate, cls).__setup__()
        # hide because used in odt report
        cls.general_ledger_balance.states['invisible'] = True


class Account(metaclass=PoolMeta):
    __name__ = 'account.account'

    @classmethod
    def __setup__(cls):
        super(Account, cls).__setup__()
        # hide because used in odt report
        cls.general_ledger_balance.states['invisible'] = True

    @classmethod
    def _html_account_descendants_query(cls, account_ids):
        account = cls.__table__()
        descendant = cls.__table__()
        return account.join(descendant,
            condition=(descendant.left >= account.left)
            & (descendant.right <= account.right)).select(
                account.id.as_('root'), descendant.id,
                where=reduce_ids(account.id, account_ids))

    @classmethod
    def html_read_account_vals(cls, accounts, company, with_moves=False,
            exclude_party_moves=False):
        pool = Pool()
        Account = pool.get('account.account')
        Move = pool.get('account.move')
        MoveLine = pool.get('account.move.line')
        line = MoveLine.__table__()
        move = Move.__table__()
        table_a = Account.__table__()

        in_max = 3000
        values = {}
        transaction = Transaction()
        cursor = transaction.connection.cursor()
        move_join = 'INNER' if with_moves else 'LEFT'
        if not accounts:
            accounts = Account.search([
                    ('company', '=', company),
                    ])
        account_ids = [a.id for a in accounts if not a.childs]
        group_by = (table_a.id,)
        columns = (group_by + (Sum(Coalesce(line.debit, 0)).as_('debit'),
                Sum(Coalesce(line.credit, 0)).as_('credit'),
                (Sum(Coalesce(line.debit, 0)) -
                    Sum(Coalesce(line.credit, 0))).as_('balance')))
        for i in range(0, len(account_ids), in_max):
            sub_ids = account_ids[i:i + in_max]
            descendants = cls._html_account_descendants_query(sub_ids)
            red_sql = reduce_ids(table_a.id, sub_ids)
            where = red_sql
            periods = transaction.context.get('periods', False)
            if periods:
                periods.append(0)
                where = (where & In(Coalesce(move.period, 0), periods))
            date = transaction.context.get('date')
            if date:
                where &= (move.date <= date)
                where &= (move.date <= date)
                where &= (move.company == company.id)
            if exclude_party_moves:
                # This "where" not use account kind (before a change use it)
                # because there are some companies that the accounts kind and
                # party_required use in a different way that "standard".
                # For example if you check the prty_required an account with
                # the kind equal to 'other'
                where = (where & (line.party == None))

            cursor.execute(*table_a.join(descendants,
                    condition=descendants.root == table_a.id
                    ).join(line, move_join,
                        condition=line.account == descendants.id
                    ).join(move, move_join,
                        condition=move.id == line.move
                    ).select(*columns, where=where, group_by=group_by))

            for account, debit, credit, balance in cursor.fetchall():
                # SQLite uses float for SUM
                if not isinstance(credit, Decimal):
                    credit = Decimal(str(credit))
                if not isinstance(debit, Decimal):
                    debit = Decimal(str(debit))
                if not isinstance(balance, Decimal):
                    balance = Decimal(str(balance))
                values[account] = {
                    'credit': credit,
                    'debit': debit,
                    'balance': balance,
                    }
        return values


class Party(metaclass=PoolMeta):
    __name__ = 'party.party'

    @classmethod
    def html_get_account_values_by_party(cls, parties, accounts, company):
        '''
        Function to compute credit,debit and balance for party ids.
        '''
        res = {}
        pool = Pool()
        Move = pool.get('account.move')
        MoveLine = pool.get('account.move.line')
        Account = pool.get('account.account')
        transaction = Transaction()
        context = transaction.context
        cursor = transaction.connection.cursor()

        move = Move.__table__()
        line = MoveLine.__table__()
        account = Account.__table__()

        order_by = (line.account,)
        group_by = (line.party, line.account,)
        columns = (group_by + (Sum(Coalesce(line.debit, 0)).as_('debit'),
                Sum(Coalesce(line.credit, 0)).as_('credit'),
                (Sum(Coalesce(line.debit, 0)) -
                    Sum(Coalesce(line.credit, 0))).as_('balance')))
        line_query, _ = MoveLine.query_get(line)
        if context.get('date'):
            # Cumulate data from previous fiscalyears
            line_query = line.move.in_(move.select(move.id,
                        where=((move.date <= context.get('date'))
                            & (move.company == company.id))))
        where = (line_query &
            (account.company == company.id))
        if accounts:
            where = where & line.account.in_([a.id for a in accounts])
        if parties:
            where = where & line.party.in_([p.id for p in parties])
        else:
            where = where & (line.party != None)
        cursor.execute(*line.join(account,
                condition=(line.account == account.id)
                ).select(*columns, where=where, order_by=order_by,
                    group_by=group_by))

        for party, account, debit, credit, balance in cursor.fetchall():
            # SQLite uses float for SUM
            if not isinstance(credit, Decimal):
                credit = Decimal(str(credit))
            if not isinstance(debit, Decimal):
                debit = Decimal(str(debit))
            if not isinstance(balance, Decimal):
                balance = Decimal(str(balance))

            if account not in res:
                res[account] = {}
            res[account][party] = {
                'credit': credit,
                'debit': debit,
                'balance': balance,
                }
        return res

class AccountReportsPDF(FPDF):
    """Print accounting tables without retaining an HTML document in memory."""

    def __init__(self, title, company, filters, columns, ratios, aligns,
            margin, checker, orientation='L', groups=None, font_size=7):
        super().__init__(orientation=orientation, format='A4')
        self.heading = '%s - %s - %s' % (
            company, title, render(datetime.now()))
        self.filters = filters
        self.columns = columns
        self.aligns = aligns
        self.groups = groups or []
        self.checker = checker
        self.table_font_size = font_size
        self.set_margins(margin, margin, margin)
        self.set_auto_page_break(False, margin=max(10, margin))
        self.widths = [self.epw * ratio / sum(ratios) for ratio in ratios]
        fonts = Path(__file__).with_name('fonts')
        self.add_font('DejaVu', fname=fonts / 'DejaVuSans.ttf')
        self.add_font('DejaVu', style='B',
            fname=fonts / 'DejaVuSans-Bold.ttf')
        self.alias_nb_pages()
        self.set_title(self.heading)

    def header(self):
        self.checker.check()
        self.set_font('DejaVu', 'B', 11)
        self.multi_cell(0, 5, self.heading, new_x='LMARGIN', new_y='NEXT')
        self.set_font('DejaVu', size=7)
        for text in self.filters:
            self.multi_cell(0, 3.5, text, new_x='LMARGIN', new_y='NEXT')
        self.ln(2)
        if self.groups:
            self.row([label for label, start, end in self.groups],
                widths=[sum(self.widths[start:end])
                    for label, start, end in self.groups],
                aligns=['C'] * len(self.groups), bold=True, paginate=False)
        self.row(self.columns, bold=True, fill=True, paginate=False)
        self.body_top = self.y

    def footer(self):
        self.set_y(-8)
        self.set_font('DejaVu', size=7)
        self.cell(0, 4, f'{self.page_no()} / {{nb}}', align='R')

    def row(self, values, bold=False, fill=False, widths=None,
            aligns=None, bottom=False, paginate=True):
        self.checker.check()
        self.set_font('DejaVu', 'B' if bold else '', self.table_font_size)
        widths = widths or self.widths
        aligns = aligns or self.aligns
        lines = []
        for width, value in zip(widths, values):
            text = '' if value is None else str(value)
            if '\n' not in text and self.get_string_width(text) <= width - 2:
                lines.append([text])
            else:
                lines.append(self.multi_cell(width, 4, text,
                    dry_run=True, output='LINES'))
        count = max(map(len, lines), default=1)
        if (paginate and self.y + count * 4 > self.h - self.b_margin
                and count * 4 <= self.h - self.b_margin - self.body_top):
            self.add_page()
            self.set_font('DejaVu', 'B' if bold else '', self.table_font_size)
        for index in range(count):
            if paginate and self.y + 4 > self.h - self.b_margin:
                self.add_page()
                self.set_font('DejaVu', 'B' if bold else '', self.table_font_size)
            self.set_x(self.l_margin)
            self.set_fill_color(235, 235, 235)
            for width, cell_lines, align in zip(widths, lines, aligns):
                text = cell_lines[index] if index < len(cell_lines) else ''
                self.cell(width, 4, text, align=align, fill=fill)
            self.ln(4)
        if bottom:
            self.line(self.l_margin, self.y, self.w - self.r_margin, self.y)


class AccountReportsPDFReport(HTMLReportMixin, Report):
    side_margin = 0.3
    report_model = 'account.move.line'

    @classmethod
    def timeout_exception(cls):
        raise TimeoutException

    @classmethod
    def execute(cls, ids, data):
        pool = Pool()
        Config = pool.get('account.configuration')
        Lang = pool.get('ir.lang')
        action, model = cls.get_action(data)
        cls.check_access(action, model or cls.report_model, ids)
        timeout = data.get('timeout') or Config(1).default_timeout or 300
        checker = TimeoutChecker(timeout, cls.timeout_exception)
        side_margin = action.html_side_margin
        if side_margin is None:
            side_margin = cls.side_margin
        margin = side_margin * 10 + (report_margin() or 0) * 25.4 / 96
        with Transaction().set_context(active_test=False,
                html_report_language=Lang.get(), output_format='pdf'):
            try:
                records, parameters = cls.prepare(data, checker)
                content = cls._build_pdf(records, parameters, margin, checker)
                checker.check()
            except TimeoutException:
                raise UserError(gettext('account_reports.msg_timeout_exception'))
        if action.html_copies and action.html_copies > 1:
            content = cls.merge_pdfs([content] * action.html_copies)
        filename = slugify(cls.get_name(action))
        try:
            Printer = pool.get('printer')
        except KeyError:
            Printer = None
        if Printer:
            return Printer.send_report('pdf', content, filename, action)
        return 'pdf', content, cls.get_direct_print(action), filename
