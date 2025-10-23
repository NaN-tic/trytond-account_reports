# This file is part of account_reports for tryton.  The COPYRIGHT file
# at the top level of this repository contains the full copyright notices and
# license terms.

def vat_label(identifier):
    type_ = identifier.type or ''
    code = identifier.code or ''

    if type_ == 'py_vat':
        return 'RUC'
    elif (type_ == 'eu_vat' and code.startswith('ES')) or type_.startswith('es_'):
        return 'NIF'
    else:
        return 'VAT'