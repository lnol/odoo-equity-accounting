from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    equity_journal_id = fields.Many2one(
        comodel_name='account.journal',
        related='company_id.equity_journal_id',
        readonly=False,
        string="Equity Journal",
    )
    equity_receivable_account_id = fields.Many2one(
        comodel_name='account.account',
        related='company_id.equity_receivable_account_id',
        readonly=False,
        string="Capital Contributions Receivable",
    )
    equity_bank_account_id = fields.Many2one(
        comodel_name='account.account',
        related='company_id.equity_bank_account_id',
        readonly=False,
        string="Dividend Payment Bank/Cash Account",
    )
    dividend_payable_account_id = fields.Many2one(
        comodel_name='account.account',
        related='company_id.dividend_payable_account_id',
        readonly=False,
        string="Dividend Payable Account",
    )
    withholding_tax_account_id = fields.Many2one(
        comodel_name='account.account',
        related='company_id.withholding_tax_account_id',
        readonly=False,
        string="KapESt/SolZ Liability Account",
    )
    dividend_retained_earnings_account_id = fields.Many2one(
        comodel_name='account.account',
        related='company_id.dividend_retained_earnings_account_id',
        readonly=False,
        string="Retained Earnings / Profit Carried Forward Account",
    )
