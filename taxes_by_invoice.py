# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from datetime import datetime
from decimal import Decimal
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateView, StateReport, Button
from trytond.pyson import Eval, If, Bool
from trytond.rpc import RPC
from trytond.i18n import gettext
from trytond.modules.html_report.dominate_report import DominateReportMixin
from trytond.modules.html_report.engine import DualRecord
from trytond.modules.html_report.i18n import _
from trytond.modules.account.exceptions import FiscalYearNotFoundError
from trytond.modules.account_reports.common import css as common_css
from trytond.modules.account_reports.tools import vat_label
from trytond.modules.account_reports.xlsx import (
    XlsxReport, save_workbook, convert_str_to_float)
from openpyxl import Workbook
from dominate.util import raw
from dominate.tags import div, header as header_tag, table, thead, tbody, tr, td, th, p, strong

_ZERO = Decimal(0)


class PrintTaxesByInvoiceAndPeriodStart(ModelView):
    'Print Taxes by Invoice and Period'
    __name__ = 'account_reports.print_taxes_by_invoice.start'

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
    partner_type = fields.Selection([
            ('customers', 'Customers'),
            ('suppliers', 'Suppliers'),
            ], 'Party Type', required=True)
    grouping = fields.Selection([
            ('base_tax_code', 'Base Tax Code'),
            ('invoice', 'Invoice'),
            ], 'Grouping', required=True)
    tax_type = fields.Selection([
            ('all', 'All'),
            ('invoiced', 'Invoiced'),
            ('refunded', 'Refunded'),
            ], 'Tax Type', required=True)
    totals_only = fields.Boolean('Totals Only')
    parties = fields.Many2Many('party.party', None, None, 'Parties',
        context={
            'company': Eval('company', -1),
            },
        depends=['company'], help="Leave empty to select all parties")
    excluded_parties = fields.Many2Many('party.party', None, None,
    'Excluded Parties',
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
    start_date = fields.Date('Initial posting date',
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
    end_date = fields.Date('Final posting date',
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
    taxes = fields.Many2Many('account.tax', None, None, 'Taxes',
        domain=[
            If(Eval('partner_type') == 'customers',
                ('group.kind', 'in', ('both', 'sale')),
                ('OR',
                    ('group', '=', None),
                    ('group.kind', 'in', ('both', 'purchase'))
                    )),
            ], help="Leave empty to select all taxes")
    timeout = fields.Integer('Timeout', required=True, help='If report '
        'calculation should take more than the specified timeout (in seconds) '
        'the process will be stopped automatically.')

    @staticmethod
    def default_partner_type():
        return 'customers'

    @staticmethod
    def default_grouping():
        return 'base_tax_code'

    @staticmethod
    def default_tax_type():
        return 'all'

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
    def default_timeout():
        Config = Pool().get('account.configuration')
        config = Config(1)
        return config.default_timeout or 30

    @fields.depends('fiscalyear', 'periods')
    def on_change_fiscalyear(self):
        if not self.fiscalyear:
            self.periods = None


class PrintTaxesByInvoiceAndPeriod(Wizard):
    'Print TaxesByInvoiceAndPeriod'
    __name__ = 'account_reports.print_taxes_by_invoice'

    start = StateView('account_reports.print_taxes_by_invoice.start',
        'account_reports.print_taxes_by_invoice_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Print', 'print_', 'tryton-print', default=True),
            ])
    print_ = StateReport('account_reports.taxes_by_invoice')

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
            'parties': [x.id for x in self.start.parties if
                        x not in self.start.excluded_parties],
            'excluded_parties': [x.id for x in self.start.excluded_parties],
            'output_format': self.start.output_format,
            'partner_type': self.start.partner_type,
            'totals_only': self.start.totals_only,
            'grouping': self.start.grouping,
            'tax_type': self.start.tax_type,
            'taxes': [x.id for x in self.start.taxes],
            }
        if self.start.output_format == 'xlsx':
            ActionReport = Pool().get('ir.action.report')
            action, = ActionReport.search([
                    ('report_name', '=', 'account_reports.taxes_by_invoice_xlsx'),
                    ])
        return action, data

    def transition_print_(self):
        return 'end'

    def default_start(self, fields):
        Party = Pool().get('party.party')
        party_ids = []
        if Transaction().context.get('model') == 'party.party':
            for party in Party.browse(Transaction().context.get('active_ids')):
                party_ids.append(party.id)
        return {
            'parties': party_ids,
            }


class TaxesByInvoiceReport(DominateReportMixin, metaclass=PoolMeta):
    __name__ = 'account_reports.taxes_by_invoice'
    side_margin = 0

    @classmethod
    def __setup__(cls):
        super(TaxesByInvoiceReport, cls).__setup__()
        cls.__rpc__['execute'] = RPC(False)
        cls.side_margin = 0.3

    @classmethod
    def css(cls, action, record=None, records=None, data=None):
        return common_css()

    @classmethod
    def prepare(cls, data):
        pool = Pool()
        Company = pool.get('company.company')
        FiscalYear = pool.get('account.fiscalyear')
        Period = pool.get('account.period')
        Party = pool.get('party.party')
        Invoice = pool.get('account.invoice')
        AccountTax = pool.get('account.tax')
        AccountInvoiceTax = pool.get('account.invoice.tax')
        InvoiceLine = pool.get('account.invoice.line')

        fiscalyear = (FiscalYear(data['fiscalyear']) if data.get('fiscalyear')
            else None)
        start_date = None
        if data['start_date']:
            start_date = data['start_date']
        end_date = None
        if data['end_date']:
            end_date = data['end_date']

        periods = []
        periods_subtitle = ''
        if data.get('periods'):
            periods = Period.browse(data.get('periods', []))
            periods_subtitle = []
            for x in periods:
                periods_subtitle.append(x.rec_name)
            periods_subtitle = '; '.join(periods_subtitle)
        elif not start_date and not end_date:
            periods = Period.search([('fiscalyear', '=', fiscalyear.id)])

        with Transaction().set_context(active_test=False):
            parties = Party.browse(data.get('parties', []))
        if parties:
            parties_subtitle = []
            for x in parties:
                if len(parties_subtitle) > 4:
                    parties_subtitle.append('...')
                    break
                parties_subtitle.append(x.rec_name)
            parties_subtitle = '; '.join(parties_subtitle)
        else:
            parties_subtitle = ''

        company = None
        if data['company']:
            company = Company(data['company'])

        parameters = {}
        parameters['fiscal_year'] = fiscalyear.rec_name if fiscalyear else ''
        parameters['start_date'] = (start_date.strftime('%d/%m/%Y')
            if start_date else '')
        parameters['end_date'] = (end_date.strftime('%d/%m/%Y')
            if end_date else '')
        parameters['parties'] = parties_subtitle
        parameters['excluded_parties'] = parties_subtitle
        parameters['periods'] = periods_subtitle
        parameters['totals_only'] = data['totals_only'] and True or False
        parameters['company'] = company.rec_name if company else ''
        parameters['company_vat'] = (company
            and company.party.tax_identifier and
            company.party.tax_identifier.code) or ''
        parameters['company_vat_label'] = (company and company.party.tax_identifier
            and vat_label(company.party.tax_identifier) or '')
        parameters['jump_page'] = (True if data['grouping'] == 'invoice'
            else False)
        parameters['records_found'] = True

        domain = [('invoice.move', '!=', None)]

        if data['partner_type'] == 'customers':
            domain += [('invoice.type', '=', 'out')]
        else:
            domain += [('invoice.type', '=', 'in')]

        if start_date:
            domain += [
                ('invoice.move.date', '>=', start_date),
                ]
        if end_date:
            domain += [
                ('invoice.move.date', '<=', end_date),
                ]

        if not start_date and not end_date and periods:
            domain += [('invoice.move.period', 'in', periods)]

        if parties:
            domain += [('invoice.party', 'in', parties)]

        excluded_parties = Party.browse(data.get('excluded_parties', []))
        if excluded_parties:
            domain += [('invoice.party', 'not in', excluded_parties)]

        invoice_tax_domain = domain.copy()

        # Search all the invoices that have taxes_deductible_rate != 1
        invoice_line_domain = domain.copy()
        invoice_line_domain += [
            ('type', '=', 'line'),
            ('taxes_deductible_rate', '!=', 1)]

        if data['tax_type'] == 'invoiced':
            invoice_tax_domain += [('base', '>=', 0)]
            # As the amount field in invoice line has not searcher, but the
            # amount = quantity x unit_price, check this both fields.
            invoice_line_domain += [['OR', [
                        [('quantity', '>=', 0), ('unit_price', '>=', 0)],
                        [('quantity', '<=', 0), ('unit_price', '<=', 0)],
                        ]]]
        elif data['tax_type'] == 'refunded':
            invoice_tax_domain += [('base', '<', 0)]
            invoice_line_domain += [['OR', [
                        [('quantity', '>', 0), ('unit_price', '<', 0)],
                        [('quantity', '<', 0), ('unit_price', '>', 0)],
                        ]]]

        if data['taxes']:
            invoice_tax_domain += [('tax', 'in', data.get('taxes', []))]
            invoice_line_domain += [('id', 'in', data.get('taxes', []))]

        records = {}
        totals = {
            'total_untaxed': _ZERO,
            'total_tax': _ZERO,
            'total': _ZERO,
            }
        fake_taxes = {}
        tax_totals = {}
        if data['grouping'] == 'invoice':
            order = [
                ('invoice.move.period', 'ASC'),
                ('invoice.invoice_date', 'ASC'),
                ('invoice', 'ASC'),
                ]
        else:
            order = [
                ('account', 'ASC'),
                ('invoice.move.date', 'ASC'),
                ('invoice', 'ASC'),
                ]

        taxes = AccountInvoiceTax.search(invoice_tax_domain, order=order)
        for tax in taxes:
            key = tax.invoice.move.period if data['grouping'] == 'invoice' else tax.tax
            records.setdefault(key, []).append(DualRecord(tax))

            # If the invoice is cancelled, do not add its values to the
            # totals
            if (tax.invoice.state == 'cancelled' and (
                    (tax.invoice.cancel_move
                        and tax.invoice.cancel_move.origin
                        and not isinstance(tax.invoice.cancel_move.origin, Invoice))
                    or not tax.invoice.cancel_move
                    or not tax.invoice.cancel_move.origin)):
                continue

            # With this we have the total for each tax (total base, total
            # amount and total)
            tax_totals.setdefault(key, {
                    'total_untaxed': 0,
                    'total_tax': 0,
                    'total': 0})
            tax_totals[key]['total_untaxed'] += tax.company_base
            tax_totals[key]['total_tax'] += tax.company_amount
            tax_totals[key]['total'] += tax.company_base + tax.company_amount

            # We need this fields in the report
            totals['total_untaxed'] += tax.company_base
            totals['total_tax'] += tax.company_amount
            totals['total'] += tax.company_base + tax.company_amount

        # Tax not deductible
        lines = InvoiceLine.search(invoice_line_domain, order=order)
        for line in lines:
            for tax in line.taxes:
                fake_key = fake_taxes.get((tax.rate, tax.company))
                if not fake_key:
                    fake_key = AccountTax()
                    fake_key.name = '%s (%s%%)' % (
                        gettext('account_reports.msg_not_deductible_tax'),
                        round(tax.rate * 100, 0))
                    fake_key.rate = tax.rate
                    fake_key.company = tax.company
                    fake_taxes[(tax.rate, tax.company)] = fake_key

                if data['grouping'] == 'invoice':
                    key = line.invoice.move.period
                else:
                    key = fake_key

                account = (tax.invoice_account if line.amount >= 0
                    else tax.credit_note_account)
                fake_line = AccountInvoiceTax()
                fake_line.invoice = line.invoice
                fake_line.account = account
                fake_line.tax = fake_key
                fake_line.base = line.amount
                fake_line.amount = Decimal('0')
                fake_line.currency = line.invoice.currency
                fake_line.company_base_cache = line.company_amount
                fake_line.company_amount_cache = Decimal('0')
                records.setdefault(key, []).append(DualRecord(fake_line))

                # If the invoice is cancelled, do not add its values to the
                # totals
                if (line.invoice.state == 'cancelled' and (
                        (line.invoice.cancel_move
                            and line.invoice.cancel_move.origin
                            and not isinstance(line.invoice.cancel_move.origin, Invoice))
                        or not line.invoice.cancel_move
                        or not line.invoice.cancel_move.origin)):
                    continue

                # With this we have the total for each tax (total base, total
                # amount and total)
                tax_totals.setdefault(key, {
                        'total_untaxed': 0,
                        'total_tax': 0,
                        'total': 0})
                tax_totals[key]['total_untaxed'] += line.company_amount
                tax_totals[key]['total'] += line.company_amount

        parameters['totals'] = totals
        parameters['tax_totals'] = tax_totals
        return records, parameters

    @classmethod
    def execute(cls, ids, data):
        with Transaction().set_context(active_test=False):
            records, parameters = cls.prepare(data)

        # We need the records dictionary to have at leat one record, otherwise
        # the report will not be generated
        if len(records) == 0:
            parameters['records_found'] = False
            records['no_records'] = ''

        name = 'account_reports.taxes_by_invoice'
        if parameters['jump_page']:
            name = 'account_reports.taxes_by_invoice_and_period'
        return super(TaxesByInvoiceReport, cls).execute([], {
            'name': name,
            'model': 'account.invoice.tax',
            'records': records,
            'parameters': parameters,
            'output_format': data.get('output_format', 'pdf'),
            })

    @classmethod
    def header(cls, action, record=None, records=None, data=None):
        render = cls.render
        p = data['parameters']
        title = (_('Taxes By Invoice and Period')
            if p['jump_page'] else _('Taxes By Invoice'))
        with header_tag(id='header') as container:
            with table(cls='header-table'):
                with thead():
                    with tr():
                        with td():
                            with div():
                                raw('<span class="company-name">%s</span> <br/>' % p['company'])
                                raw('%s: %s' % (p['company_vat_label'], p['company_vat']))
                        with td(cls='center'):
                            raw('<span class="header-title">%s</span>' % title)
                        with td(cls='right'):
                            raw(render(datetime.now()))
            with table():
                with tbody():
                    if p['start_date']:
                        with tr():
                            td('Initial posting date: %s' % p['start_date'],
                                colspan='2', cls='right')
                        with tr():
                            td('Fiscal Year: %s %s' % (
                                p['fiscal_year'],
                                ('Periods: %s' % p['periods']) if p['periods'] else 'All Periods'))
                            td('Final posting date: %s' % p['end_date'],
                                cls='right')
                    else:
                        with tr():
                            td('Fiscal Year: %s %s' % (
                                p['fiscal_year'],
                                ('Periods: %s' % p['periods']) if p['periods'] else 'All Periods'),
                                colspan='2')
                    with tr():
                        if p['parties']:
                            td('Parties: %s' % p['parties'], colspan='2')
                        else:
                            td('All Parties', colspan='2')
                    with tr():
                        td('Cancelled invoices are shown in grey. Invoices without a cancelled move or a cancelled move not related to an invoice are not added to the total.',
                            colspan='2')
        return container

    @classmethod
    def _cell(cls, row, value='', cls_name='', style_value='', colspan=1):
        cell = td(value)
        if cls_name:
            cell['class'] = cls_name
        if style_value:
            cell['style'] = style_value
        if colspan != 1:
            cell['colspan'] = str(colspan)
        row.add(cell)

    @classmethod
    def show_detail_lines(cls, record_lines):
        render = cls.render
        rows = []
        before_invoice_id = None
        for line in record_lines:
            currency_digits = line.invoice.company.currency.raw.digits
            total = line.raw.company_base + line.raw.company_amount
            if before_invoice_id != line.invoice.raw.id:
                row = tr(cls='grey' if line.invoice.raw.state == 'cancelled' else '')
                cls._cell(row, line.invoice.move.render.date)
                cls._cell(row, line.account.render.code)
                cls._cell(row, line.invoice.party.render.rec_name,
                    style_value='text-align: left;')
                tax_id = (line.invoice.party_tax_identifier
                    and line.invoice.party_tax_identifier.render.code) or (
                    line.invoice.party.tax_identifier
                    and line.invoice.party.tax_identifier.render.code) or ''
                cls._cell(row, tax_id)
                number = '%s%s' % (
                    '*' if line.invoice.raw.state == 'cancelled' else '',
                    line.invoice.render.number)
                cls._cell(row, number, cls_name='no-wrap')
                cls._cell(row, line.invoice.render.invoice_date,
                    cls_name='no-wrap')
                base = (line.raw.company_base
                    if line.render.base else 0.0)
                cls._cell(row, render(base, digits=currency_digits),
                    style_value='text-align: right;')
                cls._cell(row, line.tax.raw.name if line.tax else ' --- ')
                amount = (line.raw.company_amount
                    if line.render.amount else 0.0)
                cls._cell(row, render(amount, digits=currency_digits),
                    style_value='text-align: right;',
                    cls_name='no-wrap')
                cls._cell(row, render(total, digits=currency_digits),
                    style_value='text-align: right;',
                    cls_name='no-wrap')
                cls._cell(row,
                    render(line.invoice.raw.company_total_amount,
                        digits=currency_digits),
                    style_value='text-align: right;',
                    cls_name='bold no-wrap')
            else:
                row = tr()
                for _idx in range(6):
                    cls._cell(row, '')
                base = (line.raw.company_base
                    if line.render.base else 0.0)
                cls._cell(row, render(base, digits=currency_digits))
                cls._cell(row, line.tax.raw.name if line.tax else ' --- ')
                amount = (line.raw.company_amount
                    if line.render.amount else 0.0)
                cls._cell(row, render(amount, digits=currency_digits),
                    style_value='text-align: right;',
                    cls_name='no-wrap')
                cls._cell(row, render(total, digits=currency_digits),
                    style_value='text-align: right;',
                    cls_name='no-wrap')
            before_invoice_id = line.invoice.raw.id
            rows.append(row)
        return rows

    @classmethod
    def show_detail(cls, data):
        render = cls.render
        nodes = []
        items = list(data['records'].items())
        for index, (key, record_lines) in enumerate(items):
            table_node = table()
            with table_node:
                with thead():
                    with tr():
                        th(_('Move Date'))
                        th(_('Account'))
                        th('')
                        th(_('NIF'))
                        th(_('Invoice'))
                        th(_('Date'))
                        th(_('Base'), style='text-align: right;')
                        th('')
                        th(_('Tax'), style='text-align: right;')
                        th(_('Base + Tax'), style='text-align: right;')
                        th(_('Total Invoice'), style='text-align: right;')
                with tr() as key_row:
                    cls._cell(key_row, key.name if hasattr(key, 'name') else key.rec_name,
                        cls_name='bold',
                        style_value='text-align: left !important;padding-left: 35px !important;',
                        colspan=11)
                currency_digits = key.company.currency.digits
                if not data['parameters']['totals_only']:
                    for row in cls.show_detail_lines(record_lines):
                        table_node.add(row)
                if data['parameters']['tax_totals'].get(key):
                    total_row = tr(cls='bold')
                    cls._cell(total_row,
                        'Total Period' if data['parameters']['jump_page'] else 'Total',
                        style_value='text-align: right;',
                        colspan=6)
                    cls._cell(total_row, render(
                        data['parameters']['tax_totals'][key]['total_untaxed'],
                        digits=currency_digits),
                        style_value='text-align: right;')
                    cls._cell(total_row, '')
                    cls._cell(total_row, render(
                        data['parameters']['tax_totals'][key]['total_tax'],
                        digits=currency_digits),
                        style_value='text-align: right;')
                    cls._cell(total_row, render(
                        data['parameters']['tax_totals'][key]['total'],
                        digits=currency_digits),
                        style_value='text-align: right;')
                    cls._cell(total_row, '')
                    table_node.add(total_row)
                if data['parameters']['jump_page'] and index == len(items) - 1:
                    total_row = tr(cls='bold')
                    cls._cell(total_row, 'Total',
                        style_value='text-align: right;',
                        colspan=6)
                    cls._cell(total_row, render(
                        data['parameters']['totals']['total_untaxed'],
                        digits=currency_digits),
                        style_value='text-align: right;')
                    cls._cell(total_row, '')
                    cls._cell(total_row, render(
                        data['parameters']['totals']['total_tax'],
                        digits=currency_digits),
                        style_value='text-align: right;')
                    cls._cell(total_row, render(
                        data['parameters']['totals']['total'],
                        digits=currency_digits),
                        style_value='text-align: right;')
                    cls._cell(total_row, '')
                    table_node.add(total_row)
            nodes.append(table_node)
            if data['parameters']['jump_page'] and index < len(items) - 1:
                nodes.append(p('', style='page-break-before: always'))
        return nodes

    @classmethod
    def title(cls, action, record=None, records=None, data=None):
        render = cls.render
        title_prefix = (_('Taxes By Invoice and Period')
            if data['parameters']['jump_page'] else _('Taxes By Invoice'))
        company_name = (data['parameters'].get('company_rec_name')
            or data['parameters'].get('company')
            or '')
        return '%s - %s - %s' % (
            title_prefix,
            company_name,
            render(datetime.now()))

    @classmethod
    def body(cls, action, record=None, records=None, data=None):
        container = div()
        if data['parameters']['records_found']:
            for node in cls.show_detail(data):
                container.add(node)
        else:
            container.add(strong(_('No records found')))
        return container

class TaxesByInvoiceXlsxReport(XlsxReport, metaclass=PoolMeta):
    __name__ = 'account_reports.taxes_by_invoice_xlsx'

    @classmethod
    def get_content(cls, ids, data):
        with Transaction().set_context(active_test=False):
            records, parameters = TaxesByInvoiceReport.prepare(data)

        if len(records) == 0:
            parameters['records_found'] = False
            records['no_records'] = ''

        return cls._build_workbook(records, parameters)

    @classmethod
    def _build_workbook(cls, records, parameters):
        render = TaxesByInvoiceReport.render
        title_prefix = (_('Taxes By Invoice and Period')
            if parameters['jump_page'] else _('Taxes By Invoice'))
        company_name = (parameters.get('company_rec_name')
            or parameters.get('company')
            or '')

        wb = Workbook()
        ws = wb.active
        ws.title = title_prefix[:31]

        def xls(value, **kwargs):
            return convert_str_to_float(render(value, **kwargs))

        ws.append([company_name, title_prefix, render(datetime.now())])
        ws.append(['%s: %s' % (
            parameters['company_vat_label'], parameters['company_vat'])])
        if parameters['start_date']:
            ws.append([
                'Initial posting date: %s' % parameters['start_date'],
                'Final posting date: %s' % parameters['end_date'],
                ])
            ws.append(['Fiscal Year: %s %s' % (
                parameters['fiscal_year'],
                ('Periods: %s' % parameters['periods'])
                if parameters['periods'] else 'All Periods')])
        else:
            ws.append(['Fiscal Year: %s %s' % (
                parameters['fiscal_year'],
                ('Periods: %s' % parameters['periods'])
                if parameters['periods'] else 'All Periods')])
        if parameters['parties']:
            ws.append(['Parties: %s' % parameters['parties']])
        else:
            ws.append(['All Parties'])
        marker = '*'
        ws.append([(
            'Cancelled invoices are shown in %s. Invoices without a cancelled '
            'move or a cancelled move not related to an invoice are not added '
            'to the total.') % marker])
        ws.append([])

        if not parameters['records_found']:
            ws.append([_('No records found')])
            return save_workbook(wb)

        headers = [
            _('Move Date'),
            _('Account'),
            '',
            _('NIF'),
            _('Invoice'),
            _('Date'),
            _('Base'),
            '',
            _('Tax'),
            _('Base + Tax'),
            _('Total Invoice'),
            ]
        items = list(records.items())
        for index, (key, record_lines) in enumerate(items):
            ws.append(headers)
            key_name = key.name if hasattr(key, 'name') else key.rec_name
            ws.append([key_name] + [''] * 10)
            currency_digits = key.company.currency.digits

            if not parameters['totals_only']:
                before_invoice_id = None
                for line in record_lines:
                    total = line.raw.company_base + line.raw.company_amount
                    base = (line.raw.company_base
                        if line.render.base else 0.0)
                    amount = (line.raw.company_amount
                        if line.render.amount else 0.0)
                    if before_invoice_id != line.invoice.raw.id:
                        tax_id = (line.invoice.party_tax_identifier
                            and line.invoice.party_tax_identifier.render.code) or (
                            line.invoice.party.tax_identifier
                            and line.invoice.party.tax_identifier.render.code) or ''
                        number = '%s%s' % (
                            '*' if line.invoice.raw.state == 'cancelled' else '',
                            line.invoice.render.number)
                        ws.append([
                            line.invoice.move.render.date,
                            line.account.render.code,
                            line.invoice.party.render.rec_name,
                            tax_id,
                            number,
                            line.invoice.render.invoice_date,
                            xls(base, digits=currency_digits),
                            line.tax.raw.name if line.tax else ' --- ',
                            xls(amount, digits=currency_digits),
                            xls(total, digits=currency_digits),
                            xls(line.invoice.raw.company_total_amount,
                                digits=currency_digits),
                            ])
                    else:
                        ws.append(
                            [''] * 6
                            + [
                                xls(base, digits=currency_digits),
                                line.tax.raw.name if line.tax else ' --- ',
                                xls(amount, digits=currency_digits),
                                xls(total, digits=currency_digits),
                                '',
                                ])
                    before_invoice_id = line.invoice.raw.id

            if parameters['tax_totals'].get(key):
                total_label = ('Total Period' if parameters['jump_page']
                    else 'Total')
                ws.append(
                    [total_label] + [''] * 5
                    + [
                        xls(parameters['tax_totals'][key]['total_untaxed'],
                            digits=currency_digits),
                        '',
                        xls(parameters['tax_totals'][key]['total_tax'],
                            digits=currency_digits),
                        xls(parameters['tax_totals'][key]['total'],
                            digits=currency_digits),
                        '',
                        ])
            if parameters['jump_page'] and index == len(items) - 1:
                ws.append(
                    ['Total'] + [''] * 5
                    + [
                        xls(parameters['totals']['total_untaxed'],
                            digits=currency_digits),
                        '',
                        xls(parameters['totals']['total_tax'],
                            digits=currency_digits),
                        xls(parameters['totals']['total'],
                            digits=currency_digits),
                        '',
                        ])
            ws.append([])

        return save_workbook(wb)


class TaxesByInvoiceAndPeriodReport(TaxesByInvoiceReport):
    __name__ = 'account_reports.taxes_by_invoice_and_period'
