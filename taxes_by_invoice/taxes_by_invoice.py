# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
import os
from datetime import datetime
from decimal import Decimal
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateView, StateReport, Button
from trytond.pyson import Eval, If, Bool
from trytond.rpc import RPC
from trytond.modules.html_report.html_report import HTMLReport
from trytond.modules.html_report.engine import DualRecord
from babel.dates import format_datetime
from trytond.modules.account.exceptions import FiscalYearNotFoundError

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
            ])
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
        depends=['company'])
    output_format = fields.Selection([
            ('pdf', 'PDF'),
            ('html', 'HTML'),
            ('xls', 'Excel'),
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
            ])
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

    @fields.depends('fiscalyear')
    def on_change_fiscalyear(self):
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
            'parties': [x.id for x in self.start.parties],
            'output_format': self.start.output_format,
            'partner_type': self.start.partner_type,
            'totals_only': self.start.totals_only,
            'grouping': self.start.grouping,
            'tax_type': self.start.tax_type,
            'taxes': [x.id for x in self.start.taxes],
            }

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


class TaxesByInvoiceReport(HTMLReport):
    __name__ = 'account_reports.taxes_by_invoice'
    side_margin = 0

    @classmethod
    def __setup__(cls):
        super(TaxesByInvoiceReport, cls).__setup__()
        cls.__rpc__['execute'] = RPC(False)
        cls.side_margin = 0.3

    @classmethod
    def prepare(cls, data):
        pool = Pool()
        Company = pool.get('company.company')
        FiscalYear = pool.get('account.fiscalyear')
        Period = pool.get('account.period')
        Party = pool.get('party.party')
        Invoice = pool.get('account.invoice')
        AccountInvoiceTax = pool.get('account.invoice.tax')

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
        parameters['periods'] = periods_subtitle
        parameters['totals_only'] = data['totals_only'] and True or False
        parameters['company_rec_name'] = company.rec_name if company else ''
        parameters['company_vat'] = (company
            and company.party.tax_identifier and
            company.party.tax_identifier.code) or ''
        parameters['jump_page'] = (True if data['grouping'] == 'invoice'
            else False)
        parameters['records_found'] = True

        domain = [
            ('invoice.move', '!=', None),
            ]

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
            domain += [('invoice.party', 'in', parties)],

        if data['tax_type'] == 'invoiced':
            domain += [('base', '>=', 0)]
        elif data['tax_type'] == 'refunded':
            domain += [('base', '<', 0)]

        if data['taxes']:
            domain += [('tax', 'in', data.get('taxes', []))]

        records = {}
        totals = {
            'total_untaxed': _ZERO,
            'total_tax': _ZERO,
            'total': _ZERO,
            }
        tax_totals = {}
        if data['grouping'] == 'invoice':
            taxes = AccountInvoiceTax.search(domain,
                order=[
                    ('invoice.move.period', 'ASC'),
                    ('invoice.invoice_date', 'ASC'),
                    ('invoice', 'ASC'),
                    ])

            for tax in taxes:
                records.setdefault(tax.invoice.move.period, []).append(
                    DualRecord(tax))

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
                tax_totals.setdefault(tax.invoice.move.period, {
                        'total_untaxed': 0,
                        'total_tax': 0,
                        'total': 0})
                tax_totals[tax.invoice.move.period]['total_untaxed'] += (
                    tax.company_base)
                tax_totals[tax.invoice.move.period]['total_tax'] += (
                    tax.company_amount)
                tax_totals[tax.invoice.move.period]['total'] += (
                    tax.company_base + tax.company_amount)

                # We need this fields in the report
                totals['total_untaxed'] += tax.company_base
                totals['total_tax'] += tax.company_amount
                totals['total'] += tax.company_base + tax.company_amount
            parameters['totals'] = totals

        else:
            taxes = AccountInvoiceTax.search(domain,
                order=[
                    ('account', 'ASC'),
                    ('invoice.move.date', 'ASC'),
                    ('invoice', 'ASC'),
                    ])

            for tax in taxes:
                records.setdefault(tax.tax, []).append(DualRecord(tax))

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
                tax_totals.setdefault(tax.tax, {
                        'total_untaxed': 0,
                        'total_tax': 0,
                        'total': 0})
                tax_totals[tax.tax]['total_untaxed'] += tax.company_base
                tax_totals[tax.tax]['total_tax'] += tax.company_amount
                tax_totals[tax.tax]['total'] += (tax.company_base +
                    tax.company_amount)

        parameters['tax_totals'] = tax_totals
        return records, parameters

    @classmethod
    def execute(cls, ids, data):
        with Transaction().set_context(active_test=False):
            records, parameters = cls.prepare(data)

        context = Transaction().context.copy()
        context['report_lang'] = Transaction().language
        context['report_translations'] = os.path.join(
                os.path.dirname(__file__), 'translations')

        # We need the records dictionary to have at leat one record, otherwise
        # the report will not be generated
        if len(records) == 0:
            parameters['records_found'] = False
            records['no_records'] = ''

        with Transaction().set_context(**context):
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


class TaxesByInvoiceAndPeriodReport(TaxesByInvoiceReport):
    __name__ = 'account_reports.taxes_by_invoice_and_period'
