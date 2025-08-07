# This file is part of account_reports for tryton.  The COPYRIGHT file
# at the top level of this repository contains the full copyright notices and
# license terms.
from decimal import Decimal
from datetime import datetime
from sql.aggregate import Sum
from sql.conditionals import Coalesce
from sql.operators import In

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.tools import reduce_ids
from trytond.transaction import Transaction


class TimeoutException(Exception):
    pass


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
    def html_read_account_vals(cls, accounts, company, with_moves=False,
            exclude_party_moves=False):
        pool = Pool()
        Account = pool.get('account.account')
        Move = pool.get('account.move')
        MoveLine = pool.get('account.move.line')
        line = MoveLine.__table__()
        move = Move.__table__()
        table_a = Account.__table__()
        table_c = Account.__table__()

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

            cursor.execute(*table_a.join(table_c,
                    condition=(table_c.left >= table_a.left)
                    & (table_c.right <= table_a.right)
                    ).join(line, move_join,
                        condition=line.account == table_c.id
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
