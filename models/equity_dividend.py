from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class EquityDividend(models.Model):
    _name = 'equity.dividend'
    _description = "Dividend Declaration"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string="Reference",
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
    )
    state = fields.Selection(
        selection=[
            ('draft', "Draft"),
            ('declared', "Declared"),
            ('paid', "Paid"),
            ('cancelled', "Cancelled"),
        ],
        default='draft',
        required=True,
        tracking=True,
        copy=False,
    )
    date = fields.Date(
        string="Declaration Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    payment_date = fields.Date(
        string="Payment Date",
        tracking=True,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string="Company",
        default=lambda self: self.env.company.partner_id,
        domain=[('is_company', '=', True)],
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string="Legal Entity",
        default=lambda self: self.env.company,
        required=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='partner_id.equity_currency_id',
        store=True,
    )
    amount_per_share = fields.Monetary(
        string="Amount per Share",
        currency_field='currency_id',
        required=True,
        tracking=True,
    )
    total_gross_amount = fields.Monetary(
        string="Total Gross Amount",
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    total_net_amount = fields.Monetary(
        string="Total Net Amount (after withholding)",
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    security_class_ids = fields.Many2many(
        comodel_name='equity.security.class',
        string="Eligible Share Classes",
        domain=[('dividend_payout', '=', True)],
        help="Share classes that participate in this dividend. "
             "Only classes with 'Dividend Payout' enabled are listed.",
    )
    line_ids = fields.One2many(
        comodel_name='equity.dividend.line',
        inverse_name='dividend_id',
        string="Distribution Lines",
    )
    # Accounting
    journal_id = fields.Many2one(
        comodel_name='account.journal',
        string="Journal",
        domain="[('type', '=', 'general')]",
        compute='_compute_journal_id',
        store=True,
        readonly=False,
    )
    retained_earnings_account_id = fields.Many2one(
        comodel_name='account.account',
        string="Retained Earnings Account",
        domain="[('account_type', '=', 'equity'), ('active', '=', True)]",
        compute='_compute_default_accounts',
        store=True,
        readonly=False,
        help="Account debited on dividend declaration (e.g. SKR03: 0800 Gewinnvortrag / 2000, "
             "SKR04: 2970 Gewinnvortrag).",
    )
    dividend_payable_account_id = fields.Many2one(
        comodel_name='account.account',
        string="Dividend Payable Account",
        domain="[('account_type', 'in', ('liability_payable', 'liability_current')), ('active', '=', True)]",
        compute='_compute_default_accounts',
        store=True,
        readonly=False,
        help="Liability account credited on declaration, debited on payment.",
    )
    # German withholding tax
    apply_withholding_tax = fields.Boolean(
        string="Apply German Withholding Tax (KapESt)",
        help="If enabled, Kapitalertragsteuer (25%) and Solidaritätszuschlag (5.5%) "
             "are computed and recorded as separate liabilities.",
    )
    withholding_tax_account_id = fields.Many2one(
        comodel_name='account.account',
        string="KapESt Liability Account",
        domain="[('active', '=', True)]",
        compute='_compute_default_accounts',
        store=True,
        readonly=False,
        help="e.g. SKR03: 1746 / SKR04: 3760 Verbindlichkeiten aus Einbehaltungen (KapESt + SolZ)",
    )
    withholding_tax_rate = fields.Float(
        string="KapESt Rate",
        default=0.25,
        help="Kapitalertragsteuer rate. Standard: 25%.",
    )
    soli_rate = fields.Float(
        string="SolZ Rate",
        default=0.055,
        help="Solidaritätszuschlag on KapESt. Standard: 5.5%.",
    )
    declaration_move_id = fields.Many2one(
        comodel_name='account.move',
        string="Declaration Journal Entry",
        readonly=True,
        copy=False,
    )

    @api.depends('line_ids.gross_amount', 'line_ids.net_amount')
    def _compute_totals(self):
        for dividend in self:
            dividend.total_gross_amount = sum(dividend.line_ids.mapped('gross_amount'))
            dividend.total_net_amount = sum(dividend.line_ids.mapped('net_amount'))

    @api.depends('company_id')
    def _compute_journal_id(self):
        for dividend in self:
            dividend.journal_id = dividend.company_id.equity_journal_id or self.env['account.journal'].search(
                [('type', '=', 'general'), ('company_id', '=', dividend.company_id.id)],
                limit=1,
            )

    @api.depends('company_id')
    def _compute_default_accounts(self):
        for dividend in self:
            company = dividend.company_id
            dividend.retained_earnings_account_id = company.dividend_retained_earnings_account_id
            dividend.dividend_payable_account_id = company.dividend_payable_account_id
            dividend.withholding_tax_account_id = company.withholding_tax_account_id

    def action_compute_lines(self):
        """Read cap table at declaration date and populate distribution lines."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Lines can only be computed in draft state."))

        cap_table = self.env['equity.cap.table'].with_context(current_date=self.date)
        domain = [('partner_id', '=', self.partner_id.id)]
        if self.security_class_ids:
            domain.append(('security_class_id', 'in', self.security_class_ids.ids))
        else:
            domain.append(('security_class_id.dividend_payout', '=', True))

        # Aggregate shares per holder across eligible classes
        shares_per_holder = {}
        for entry in cap_table.search(domain):
            if entry.securities_type != 'shares':
                continue
            holder_id = entry.holder_id.id
            shares_per_holder[holder_id] = shares_per_holder.get(holder_id, 0) + entry.securities

        # Delete old lines and rebuild
        self.line_ids.unlink()
        lines = []
        for holder_id, shares in shares_per_holder.items():
            if shares <= 0:
                continue
            gross = shares * self.amount_per_share
            withholding = gross * self.withholding_tax_rate if self.apply_withholding_tax else 0.0
            soli = withholding * self.soli_rate if self.apply_withholding_tax else 0.0
            lines.append(Command.create({
                'holder_id': holder_id,
                'shares': shares,
                'gross_amount': gross,
                'withholding_tax': withholding,
                'soli_amount': soli,
                'net_amount': gross - withholding - soli,
            }))
        self.line_ids = lines

    def action_declare(self):
        """Post the dividend declaration journal entry."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Only draft dividends can be declared."))
        if not self.line_ids:
            raise UserError(_("Please compute distribution lines before declaring."))
        if not self.retained_earnings_account_id:
            raise UserError(_("Please configure a retained earnings account."))
        if not self.dividend_payable_account_id:
            raise UserError(_("Please configure a dividend payable account."))

        move = self._create_declaration_move()
        move.action_post()
        self.declaration_move_id = move
        self.name = self.env['ir.sequence'].next_by_code('equity.dividend') or _("New")
        self.state = 'declared'

    def _create_declaration_move(self):
        """
        Dr  Retained Earnings / Gewinnvortrag    (total gross)
          Cr  Dividend Payable                   (total net per holder)
          Cr  KapESt Liability                   (total withholding + soli)   [if enabled]
        """
        self.ensure_one()
        line_vals = []

        # Debit retained earnings for total gross
        line_vals.append(Command.create({
            'account_id': self.retained_earnings_account_id.id,
            'balance': self.total_gross_amount,
            'currency_id': self.currency_id.id,
            'name': _("Dividend declaration – %s", self.name),
        }))

        # Credit dividend payable per holder (net amount)
        for line in self.line_ids:
            if line.net_amount:
                line_vals.append(Command.create({
                    'account_id': self.dividend_payable_account_id.id,
                    'balance': -line.net_amount,
                    'currency_id': self.currency_id.id,
                    'partner_id': line.holder_id.id,
                    'name': _("Dividend payable – %s", line.holder_id.display_name),
                }))

        # Credit KapESt + SolZ liability (aggregated)
        if self.apply_withholding_tax and self.withholding_tax_account_id:
            total_tax = sum(self.line_ids.mapped('withholding_tax')) + sum(self.line_ids.mapped('soli_amount'))
            if total_tax:
                line_vals.append(Command.create({
                    'account_id': self.withholding_tax_account_id.id,
                    'balance': -total_tax,
                    'currency_id': self.currency_id.id,
                    'name': _("KapESt + SolZ – %s", self.name),
                }))

        return self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': _("Dividend declaration – %s", self.partner_id.display_name),
            'company_id': self.company_id.id,
            'line_ids': line_vals,
        })

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'paid':
            raise UserError(_("Cannot cancel a fully paid dividend."))
        if self.declaration_move_id and self.declaration_move_id.state == 'posted':
            reversal = self.declaration_move_id._reverse_moves(
                default_values_list=[{
                    'ref': _("Reversal of dividend declaration: %s", self.name),
                    'date': fields.Date.today(),
                }]
            )
            reversal.action_post()
        self.state = 'cancelled'

    def action_pay_all(self):
        """Pay all unpaid distribution lines."""
        self.ensure_one()
        unpaid_lines = self.line_ids.filtered(lambda l: l.payment_state == 'unpaid')
        if not unpaid_lines:
            raise UserError(_("All lines are already paid."))
        unpaid_lines.action_pay()
        if all(l.payment_state == 'paid' for l in self.line_ids):
            self.state = 'paid'


class EquityDividendLine(models.Model):
    _name = 'equity.dividend.line'
    _description = "Dividend Distribution Line"
    _order = 'holder_id'

    dividend_id = fields.Many2one(
        comodel_name='equity.dividend',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(related='dividend_id.company_id', store=True)
    currency_id = fields.Many2one(related='dividend_id.currency_id', store=True)
    holder_id = fields.Many2one(
        comodel_name='res.partner',
        string="Shareholder",
        required=True,
    )
    shares = fields.Float(string="Eligible Shares", digits=(16, 2))
    gross_amount = fields.Monetary(string="Gross Amount", currency_field='currency_id')
    withholding_tax = fields.Monetary(string="KapESt (25%)", currency_field='currency_id')
    soli_amount = fields.Monetary(string="SolZ (5.5% of KapESt)", currency_field='currency_id')
    net_amount = fields.Monetary(string="Net Amount", currency_field='currency_id')
    payment_state = fields.Selection(
        selection=[('unpaid', "Unpaid"), ('paid', "Paid")],
        default='unpaid',
        required=True,
    )
    payment_move_id = fields.Many2one(
        comodel_name='account.move',
        string="Payment Journal Entry",
        readonly=True,
        copy=False,
    )

    def action_pay(self):
        """Create a payment journal entry per line:
        Dr  Dividend Payable  /  Cr  Bank
        """
        for line in self.filtered(lambda l: l.payment_state == 'unpaid'):
            dividend = line.dividend_id
            if not dividend.dividend_payable_account_id:
                raise UserError(_("No dividend payable account configured on the dividend."))
            company = dividend.company_id
            bank_account = company.equity_bank_account_id
            if not bank_account:
                raise UserError(
                    _("No equity bank/cash account configured. "
                      "Please set it in Settings > Accounting > Equity Configuration.")
                )
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': dividend.journal_id.id,
                'date': dividend.payment_date or fields.Date.today(),
                'ref': _("Dividend payment – %(dividend)s – %(holder)s",
                         dividend=dividend.name,
                         holder=line.holder_id.display_name),
                'company_id': company.id,
                'line_ids': [
                    Command.create({
                        'account_id': dividend.dividend_payable_account_id.id,
                        'balance': line.net_amount,
                        'currency_id': line.currency_id.id,
                        'partner_id': line.holder_id.id,
                        'name': _("Dividend payment – %s", line.holder_id.display_name),
                    }),
                    Command.create({
                        'account_id': bank_account.id,
                        'balance': -line.net_amount,
                        'currency_id': line.currency_id.id,
                        'partner_id': line.holder_id.id,
                        'name': _("Dividend payment – %s", line.holder_id.display_name),
                    }),
                ],
            })
            move.action_post()
            line.payment_move_id = move
            line.payment_state = 'paid'
