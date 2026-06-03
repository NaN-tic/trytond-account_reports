from trytond.pool import Pool
from . import open_move_lines


def register(module):
    Pool.register(
        open_move_lines.PrintOpenMoveLinesStart,
        module=module, type_='model')
    Pool.register(
        open_move_lines.PrintOpenMoveLines,
        module=module, type_='wizard')
    Pool.register(
        open_move_lines.OpenMoveLinesReport,
        module=module, type_='report')
