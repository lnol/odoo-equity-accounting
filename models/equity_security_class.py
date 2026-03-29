from odoo import fields, models


class EquitySecurityClass(models.Model):
    _inherit = 'equity.security.class'

    par_value = fields.Float(
        string="Par Value (Nennwert)",
        digits=(16, 4),
        help="Nominal value per share. Used to split issuance proceeds between "
             "subscribed capital (at par) and capital reserve (share premium / Agio).",
    )
    par_value_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string="Par Value Currency",
        default=lambda self: self.env.company.currency_id,
    )
    equity_account_id = fields.Many2one(
        comodel_name='account.account',
        string="Subscribed Capital Account",
        company_dependent=True,
        domain="[('account_type', '=', 'equity'), ('active', '=', True)]",
        help="Account credited with the par value on share issuance "
             "(e.g. SKR03: 0800 Gezeichnetes Kapital, SKR04: 2900).",
    )
    capital_reserve_account_id = fields.Many2one(
        comodel_name='account.account',
        string="Capital Reserve Account (Agio)",
        company_dependent=True,
        domain="[('account_type', '=', 'equity'), ('active', '=', True)]",
        help="Account credited with the share premium (issue price minus par value) "
             "on issuance (e.g. SKR03: 0840 Kapitalrücklage, SKR04: 2920).",
    )
