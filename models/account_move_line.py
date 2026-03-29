from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    equity_transaction_id = fields.Many2one(
        comodel_name='equity.transaction',
        string="Equity Transaction",
        readonly=True,
        copy=False,
        ondelete='set null',
        index=True,
        help="Equity transaction that generated this journal item.",
    )
