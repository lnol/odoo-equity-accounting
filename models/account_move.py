from odoo import _, api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    equity_transaction_id = fields.Many2one(
        comodel_name='equity.transaction',
        string="Equity Transaction",
        compute='_compute_equity_transaction_id',
        store=True,
    )

    @api.depends('line_ids.equity_transaction_id')
    def _compute_equity_transaction_id(self):
        for move in self:
            move.equity_transaction_id = move.line_ids.mapped('equity_transaction_id')[:1]

    def action_open_equity_transaction(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'equity.transaction',
            'res_id': self.equity_transaction_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
