# This file is part of account_reports for tryton.  The COPYRIGHT file
# at the top level of this repository contains the full copyright notices and
# license terms.
from datetime import datetime

from dominate.tags import div, header as header_tag, table, tbody, td, th, thead, tr

from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.model import ModelView, fields
from trytond.modules.account.exceptions import FiscalYearNotFoundError
from trytond.modules.account_reports.common import TimeoutChecker, TimeoutException
from trytond.modules.html_report.dominate_report import DominateReport
from trytond.modules.html_report.engine import render as html_render
from trytond.modules.html_report.i18n import _
from trytond.pool import Pool
from trytond.pyson import Bool, Eval, If
from trytond.rpc import RPC
from trytond.transaction import Transaction
from trytond.wizard import Button, StateReport, StateView, Wizard

class PrintInvoicePaymentDatesStart(ModelView):
    'Print Invoice Payment Dates'
    __name__ = 'account_reports.print_invoice_payment_dates.start'

    fiscalyear = fields.Many2One('account.fiscalyear', 'Fiscal Year',
        states={
            'invisible': Eval('start_date') | Eval('end_date'),
            'required': ~Eval('start_date') & ~Eval('end_date'),
            })
    periods = fields.Many2Many('account.period', None, None, 'Periods',
        states={
            'invisible': Eval('start_date') | Eval('end_date'),
            },
        domain=[
            ('fiscalyear', '=', Eval('fiscalyear')),
            ], help="Leave empty to select all periods")
    start_date = fields.Date('Initial invoice date',
        domain=[
            If(Eval('start_date') & Eval('end_date'),
                ('start_date', '<=', Eval('end_date', None)),
                ()),
            ],
        states={
            'invisible': Bool(Eval('periods')),
            'required': ((Eval('start_date') | Eval('end_date')) &
                ~Bool(Eval('periods'))),
            })
    end_date = fields.Date('Final invoice date',
        domain=[
            If(Eval('start_date') & Eval('end_date'),
                ('end_date', '>=', Eval('start_date', None)),
                ()),
            ],
        states={
            'invisible': Bool(Eval('periods')),
            'required': ((Eval('end_date') | Eval('start_date')) &
                ~Bool(Eval('periods'))),
            })
    invoice_type = fields.Selection([
            ('out', 'Customer Invoices'),
            ('in', 'Supplier Invoices'),
            ], 'Invoice Type', required=True)
    output_format = fields.Selection([
            ('pdf', 'PDF'),
            ('html', 'HTML'),
            ('xlsx', 'Excel'),
            ], 'Output Format', required=True)
    company = fields.Many2One('company.company', 'Company', required=True)
    timeout = fields.Integer('Timeout', required=True, help='If report '
        'calculation should take more than the specified timeout (in seconds) '
        'the process will be stopped automatically.')

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
    def default_invoice_type():
        return 'out'

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
        return config.default_timeout or 300

    @fields.depends('fiscalyear', 'periods')
    def on_change_fiscalyear(self):
        if not self.fiscalyear:
            self.periods = None


class PrintInvoicePaymentDates(Wizard):
    'Print Invoice Payment Dates'
    __name__ = 'account_reports.print_invoice_payment_dates'

    start = StateView('account_reports.print_invoice_payment_dates.start',
        'account_reports.print_invoice_payment_dates_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Print', 'print_', 'tryton-print', default=True),
            ])
    print_ = StateReport('account_reports.invoice_payment_dates')

    def do_print_(self, action):
        fiscalyear = (self.start.fiscalyear.id if self.start.fiscalyear
            else None)
        if self.start.start_date:
            fiscalyear = None
        data = {
            'company': self.start.company.id,
            'fiscalyear': fiscalyear,
            'start_date': self.start.start_date,
            'end_date': self.start.end_date,
            'periods': [x.id for x in self.start.periods],
            'output_format': self.start.output_format,
            'invoice_type': self.start.invoice_type,
            'timeout': self.start.timeout,
            }
        return action, data

    def transition_print_(self):
        return 'end'


class InvoicePaymentDatesReport(DominateReport):
    __name__ = 'account_reports.invoice_payment_dates'
    page_orientation = 'portrait'
    side_margin = 0.3

    @classmethod
    def __setup__(cls):
        super(InvoicePaymentDatesReport, cls).__setup__()
        cls.__rpc__['execute'] = RPC(False)

    @classmethod
    def timeout_exception(cls):
        raise TimeoutException

    @classmethod
    def title(cls, action, data, records):
        return '%s - %s - %s' % (
            _('Invoice Payment Dates'),
            data['parameters']['company'],
            html_render(datetime.now()))

    @classmethod
    def css_body(cls, action, data, records):
        css = super().css_body(action, data, records)
        css += '''
table.invoice-payment-dates {
    table-layout: fixed;
    width: 100%;
}
table.invoice-payment-dates th,
table.invoice-payment-dates td {
    word-wrap: break-word;
}
table.invoice-payment-dates .col-number { width: 7%; }
table.invoice-payment-dates .col-reference { width: 6%; }
table.invoice-payment-dates .col-invoice-date { width: 7%; }
table.invoice-payment-dates .col-party { width: 12%; }
table.invoice-payment-dates .col-state { width: 5%; }
table.invoice-payment-dates .col-payment-type { width: 7%; }
table.invoice-payment-dates .col-description { width: 15%; }
table.invoice-payment-dates .col-amount { width: 6%; }
table.invoice-payment-dates .col-due-date { width: 7%; }
table.invoice-payment-dates .col-due-amount { width: 7%; }
table.invoice-payment-dates .col-payment-date { width: 7%; }
table.invoice-payment-dates .col-payment-days { width: 6%; }
'''
        return css

    @classmethod
    def header(cls, action, data, records):
        parameters = data['parameters']
        with header_tag(id='header') as container:
            with div(style=(
                    'padding-top:1cm;padding-left:2cm;text-align:left;'
                    'font-size:9px;width:100%;font-family:"Arial";')):
                div(_('Invoice Payment Dates'), cls='bold')
                div(parameters['company'])
                div(parameters['invoice_type'])
                if parameters['periods']:
                    div(parameters['periods'])
                else:
                    period_range = parameters['start_date']
                    if parameters['start_date'] and parameters['end_date']:
                        period_range += ' - '
                    period_range += parameters['end_date']
                    div(period_range)
        return container

    @classmethod
    def body(cls, action, data, records):
        container = div()
        if data.get('output_format') != 'pdf':
            container.add(cls.header(action, data, records))
        container.add(cls.show_detail(data['records'], data['parameters']))
        return container

    @classmethod
    def show_detail(cls, records, parameters):
        detail_table = table(cls='border invoice-payment-dates')
        with detail_table:
            with thead():
                with tr():
                    th(_('Number'), cls='col-number')
                    th(_('Reference'), cls='col-reference')
                    th(_('Invoice Date'), cls='col-invoice-date')
                    th(_('Party'), cls='col-party')
                    th(_('State'), cls='col-state')
                    th(_('Payment Type'), cls='col-payment-type')
                    th(_('Description'), cls='col-description')
                    th(_('Untaxed'), cls='col-amount',
                        style='text-align: right;')
                    th(_('Tax'), cls='col-amount', style='text-align: right;')
                    th(_('Total'), cls='col-amount',
                        style='text-align: right;')
                    th(_('Due Date'), cls='col-due-date')
                    th(_('Due Amount'), cls='col-due-amount',
                        style='text-align: right;')
                    th(_('Payment Date'), cls='col-payment-date')
                    th(_('Payment Days'), cls='col-payment-days',
                        style='text-align: right;')
            with tbody():
                if parameters['records_found']:
                    for record in records:
                        with tr():
                            td(record['number'], cls='col-number no-wrap')
                            td(record['reference'],
                                cls='col-reference no-wrap')
                            td(record['invoice_date'],
                                cls='col-invoice-date no-wrap')
                            td(record['party'], cls='col-party')
                            td(record['state'], cls='col-state')
                            td(record['payment_type'],
                                cls='col-payment-type')
                            td(record['description'],
                                cls='col-description')
                            td(html_render(record['untaxed_amount'],
                                digits=record['currency_digits']),
                                cls='col-amount right')
                            td(html_render(record['tax_amount'],
                                digits=record['currency_digits']),
                                cls='col-amount right')
                            td(html_render(record['total_amount'],
                                digits=record['currency_digits']),
                                cls='col-amount right')
                            td(record['due_date'],
                                cls='col-due-date no-wrap')
                            td(html_render(record['due_amount'],
                                digits=record['currency_digits']),
                                cls='col-due-amount right')
                            td(record['payment_date'],
                                cls='col-payment-date no-wrap')
                            td(record['payment_days'],
                                cls='col-payment-days right')
                else:
                    with tr():
                        td(_('No invoices found'), colspan='14')
        return detail_table

    @classmethod
    def prepare(cls, data, checker):
        pool = Pool()
        Company = pool.get('company.company')
        FiscalYear = pool.get('account.fiscalyear')
        Period = pool.get('account.period')
        MoveLine = pool.get('account.move.line')
        AdditionalMove = pool.get('account.invoice-additional-account.move')
        Invoice = pool.get('account.invoice')
        Party = pool.get('party.party')
        PaymentTerm = pool.get('account.invoice.payment_term')
        Currency = pool.get('currency.currency')
        Reconciliation = pool.get('account.move.reconciliation')

        fiscalyear = (FiscalYear(data['fiscalyear']) if data.get('fiscalyear')
            else None)
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        periods = []
        if data.get('periods'):
            periods = Period.browse(data.get('periods', []))
        elif not start_date and not end_date and fiscalyear:
            periods = Period.search([('fiscalyear', '=', fiscalyear.id)])

        if periods:
            periods_subtitle = []
            for x in periods:
                periods_subtitle.append(x.rec_name)
            periods_subtitle = '; '.join(periods_subtitle)
        else:
            periods_subtitle = ''

        company = Company(data['company']) if data['company'] else None
        invoice_type = {
            'out': 'Customer Invoices',
            'in': 'Supplier Invoices',
            }.get(data['invoice_type'], '')

        if periods and not start_date and not end_date:
            if len(periods) == 1:
                period = periods[0]
                start_date = period.start_date
                end_date = period.end_date
            else:
                start_date = min(p.start_date for p in periods)
                end_date = max(p.end_date for p in periods)

        parameters = {
            'company': company.rec_name if company else '',
            'invoice_type': invoice_type,
            'start_date': start_date.strftime('%d/%m/%Y') if start_date else '',
            'end_date': end_date.strftime('%d/%m/%Y') if end_date else '',
            'periods': periods_subtitle,
            'records_found': True,
            }

        invoice = Invoice.__table__()
        line = MoveLine.__table__()
        additional_move = AdditionalMove.__table__()
        party = Party.__table__()
        payment_term = PaymentTerm.__table__()
        currency = Currency.__table__()
        reconciliation = Reconciliation.__table__()

        if periods and not start_date and not end_date:
            if len(periods) == 1:
                period = periods[0]
                date_condition = ((invoice.invoice_date >= period.start_date)
                    & (invoice.invoice_date <= period.end_date))
            else:
                date_condition = None
                for period in periods:
                    period_condition = ((invoice.invoice_date >= period.start_date)
                        & (invoice.invoice_date <= period.end_date))
                    date_condition = (period_condition if date_condition is None
                        else (date_condition | period_condition))
        else:
            date_condition = None
            if start_date:
                date_condition = (invoice.invoice_date >= start_date)
            if end_date:
                end_condition = (invoice.invoice_date <= end_date)
                date_condition = (end_condition if date_condition is None
                    else (date_condition & end_condition))

        base_where = ((invoice.company == company.id)
            & (invoice.type == data['invoice_type'])
            & invoice.state.in_(('posted', 'paid')))
        if date_condition is not None:
            base_where &= date_condition

        def build_query(invoice_join):
            query = (invoice
                .join(invoice_join, condition=((invoice.move == line.move)
                    & (invoice.account == line.account)))
                .join(payment_term, type_='LEFT',
                    condition=(payment_term.id == invoice.payment_term))
                .join(party, type_='LEFT', condition=(party.id == invoice.party))
                .join(currency, condition=(currency.id == invoice.currency))
                .join(reconciliation, type_='LEFT',
                    condition=(reconciliation.id == line.reconciliation))
                .select(
                    invoice.id.as_('invoice'),
                    line.id.as_('line'),
                    line.maturity_date.as_('maturity_date'),
                    line.debit.as_('debit'),
                    line.credit.as_('credit'),
                    line.second_currency.as_('second_currency'),
                    line.amount_second_currency.as_('amount_second_currency'),
                    reconciliation.date.as_('payment_date'),
                    invoice.number.as_('number'),
                    invoice.reference.as_('reference'),
                    invoice.invoice_date.as_('invoice_date'),
                    invoice.state.as_('state'),
                    invoice.currency.as_('invoice_currency'),
                    invoice.untaxed_amount_cache.as_('untaxed_amount'),
                    invoice.tax_amount_cache.as_('tax_amount'),
                    invoice.total_amount_cache.as_('total_amount'),
                    invoice.description.as_('description'),
                    party.name.as_('party'),
                    payment_term.name.as_('payment_type'),
                    currency.digits.as_('currency_digits'),
                    where=base_where))
            return query

        query = build_query(line)
        query |= (invoice
            .join(additional_move, condition=additional_move.invoice == invoice.id)
            .join(line, condition=((additional_move.move == line.move)
                & (invoice.account == line.account)))
            .join(payment_term, type_='LEFT',
                condition=(payment_term.id == invoice.payment_term))
            .join(party, type_='LEFT', condition=(party.id == invoice.party))
            .join(currency, condition=(currency.id == invoice.currency))
            .join(reconciliation, type_='LEFT',
                condition=(reconciliation.id == line.reconciliation))
            .select(
                invoice.id.as_('invoice'),
                line.id.as_('line'),
                line.maturity_date.as_('maturity_date'),
                line.debit.as_('debit'),
                line.credit.as_('credit'),
                line.second_currency.as_('second_currency'),
                line.amount_second_currency.as_('amount_second_currency'),
                reconciliation.date.as_('payment_date'),
                invoice.number.as_('number'),
                invoice.reference.as_('reference'),
                invoice.invoice_date.as_('invoice_date'),
                invoice.state.as_('state'),
                invoice.currency.as_('invoice_currency'),
                invoice.untaxed_amount_cache.as_('untaxed_amount'),
                invoice.tax_amount_cache.as_('tax_amount'),
                invoice.total_amount_cache.as_('total_amount'),
                invoice.description.as_('description'),
                party.name.as_('party'),
                payment_term.name.as_('payment_type'),
                currency.digits.as_('currency_digits'),
                where=base_where))

        records = []
        cursor = Transaction().connection.cursor()
        cursor.execute(*query.select(
                query.invoice, query.line, query.maturity_date,
                query.debit, query.credit, query.second_currency,
                query.amount_second_currency, query.payment_date,
                query.number, query.reference, query.invoice_date,
                query.state, query.invoice_currency, query.untaxed_amount,
                query.tax_amount, query.total_amount, query.description,
                query.party, query.payment_type, query.currency_digits,
                order_by=(
                    query.invoice_date, query.number, query.invoice,
                    query.maturity_date.nulls_last, query.line)))
        for (
                _invoice_id, _line_id, maturity_date, debit, credit,
                second_currency, amount_second_currency, payment_date,
                number, reference, invoice_date, state, invoice_currency,
                untaxed_amount, tax_amount, total_amount, description,
                party_name, payment_type, currency_digits) in cursor:
            amount = debit - credit
            if (second_currency
                    and second_currency == invoice_currency
                    and amount_second_currency is not None):
                amount = amount_second_currency
            payment_days = ''
            if payment_date and invoice_date:
                payment_days = (payment_date - invoice_date).days
            records.append({
                    'number': number or '',
                    'reference': reference or '',
                    'invoice_date': (invoice_date
                        and invoice_date.strftime('%d/%m/%Y')
                        or ''),
                    'party': party_name or '',
                    'state': state or '',
                    'payment_type': payment_type or '',
                    'untaxed_amount': untaxed_amount,
                    'tax_amount': tax_amount,
                    'total_amount': total_amount,
                    'description': description or '',
                    'due_date': (maturity_date
                        and maturity_date.strftime('%d/%m/%Y')
                        or ''),
                    'due_amount': abs(amount),
                    'payment_date': (payment_date
                        and payment_date.strftime('%d/%m/%Y')
                        or ''),
                    'payment_days': payment_days,
                    'currency_digits': currency_digits,
                    })

        parameters['records_found'] = bool(records)
        if not records:
            records = [{}]
        return records, parameters

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
        if timeout:
            context['timeout_report'] = (
                timeout - int((end_prepare - start_prepare).total_seconds()))

        with Transaction().set_context(**context):
            return super(InvoicePaymentDatesReport, cls).execute(ids, {
                    'name': 'account_reports.invoice_payment_dates',
                    'model': 'account.invoice',
                    'records': records,
                    'parameters': parameters,
                    'output_format': data.get('output_format', 'pdf'),
                    })
