from tempfile import NamedTemporaryFile

from trytond.pool import Pool
from trytond.report import Report


def save_workbook(workbook):
    with NamedTemporaryFile() as tmp_file:
        workbook.save(tmp_file.name)
        tmp_file.seek(0)
        return bytes(tmp_file.read())


def convert_str_to_float(value):
    if isinstance(value, str):
        try:
            return float(value.replace(',', '.'))
        except ValueError:
            return value
    return value


class XlsxReport(Report):
    OEXT = 'xlsx'

    @classmethod
    def execute(cls, ids, data):
        pool = Pool()
        ActionReport = pool.get('ir.action.report')
        action_report, = ActionReport.search([
                ('report_name', '=', cls.__name__)
                ])
        cls.check_access(action_report, action_report.model, ids)
        filename = cls.get_filename(data) or action_report.name
        content = cls.get_content(ids, data)
        return cls.OEXT, content, action_report.direct_print, filename

    @classmethod
    def get_filename(cls, data):
        return None

    @classmethod
    def get_content(cls, ids, data):
        raise NotImplementedError
