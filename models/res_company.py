from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    equity_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string="Equity Journal",
        domain="[('type', '=', 'general'), ('company_id', '=', id)]",
        help="Default miscellaneous journal used for equity transactions and dividend entries.",
    )
    equity_receivable_account_id = fields.Many2one(
        comodel_name='account.account',
        string="Capital Contributions Receivable",
        domain="[('account_type', 'in', ('asset_receivable', 'asset_current')), ('active', '=', True), ('company_id', '=', id)]",
        help="Debited when shares are subscribed (before payment is received). "
             "The accountant reconciles this open item against the incoming bank statement. "
             "Ensure 'Allow Reconciliation' is enabled on the account. "
             "(SKR04: 1298 Ausstehende Einlagen, eingefordert; or any asset_receivable account.)",
    )
    equity_bank_account_id = fields.Many2one(
        comodel_name='account.account',
        string="Dividend Payment Bank/Cash Account",
        domain="[('account_type', 'in', ('asset_cash', 'asset_current')), ('active', '=', True), ('company_id', '=', id)]",
        help="Bank or cash account credited when dividends are paid out to shareholders.",
    )
    dividend_payable_account_id = fields.Many2one(
        comodel_name='account.account',
        string="Dividend Payable Account",
        domain="[('account_type', 'in', ('liability_payable', 'liability_current')), ('active', '=', True), ('company_id', '=', id)]",
        help="Liability account credited on dividend declaration and debited on payment "
             "(e.g. SKR03: 1700, SKR04: 3300).",
    )
    withholding_tax_account_id = fields.Many2one(
        comodel_name='account.account',
        string="KapESt/SolZ Liability Account",
        domain="[('active', '=', True), ('company_id', '=', id)]",
        help="Liability account for withheld Kapitalertragsteuer and Solidaritätszuschlag "
             "(SKR03: 1746, SKR04: 3760).",
    )
    dividend_retained_earnings_account_id = fields.Many2one(
        comodel_name='account.account',
        string="Retained Earnings / Profit Carried Forward Account",
        domain="[('account_type', '=', 'equity'), ('active', '=', True), ('company_id', '=', id)]",
        help="Equity account debited when a dividend is declared "
             "(e.g. SKR03: 0865 Gewinnvortrag, SKR04: 2970 Gewinnvortrag).",
    )
