from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class EquityTransaction(models.Model):
    _inherit = 'equity.transaction'

    state = fields.Selection(
        selection=[
            ('draft', "Draft"),
            ('posted', "Posted"),
            ('cancelled', "Cancelled"),
        ],
        default='draft',
        required=True,
        tracking=True,
        copy=False,
    )
    move_id = fields.Many2one(
        comodel_name='account.move',
        string="Journal Entry",
        readonly=True,
        copy=False,
        ondelete='restrict',
    )
    journal_id = fields.Many2one(
        comodel_name='account.journal',
        string="Journal",
        domain="[('type', '=', 'general')]",
        compute='_compute_journal_id',
        store=True,
        readonly=False,
        copy=False,
    )
    receivable_line_id = fields.Many2one(
        comodel_name='account.move.line',
        string="Receivable Line",
        readonly=True,
        copy=False,
        ondelete='set null',
        help="The journal item representing the capital contribution receivable. "
             "Reconcile this line against the bank statement when the investor pays.",
    )

    payment_state = fields.Selection(
        selection=[
            ('not_paid', "Not Paid"),
            ('partial', "Partially Paid"),
            ('paid', "Paid"),
        ],
        string="Payment Status",
        compute='_compute_payment_info',
        store=True,
        copy=False,
    )
    payment_date = fields.Date(
        string="Payment Date",
        compute='_compute_payment_info',
        store=True,
        copy=False,
    )

    @api.depends(
        'state',
        'transaction_type',
        'receivable_line_id.reconciled',
        'receivable_line_id.amount_residual',
        'receivable_line_id.matched_credit_ids.max_date',
        'receivable_line_id.matched_debit_ids.max_date',
    )
    def _compute_payment_info(self):
        for transaction in self:
            if (
                transaction.state == 'cancelled'
                or transaction.transaction_type not in ('issuance', 'cancellation')
                or not transaction.receivable_line_id
            ):
                transaction.payment_state = False
                transaction.payment_date = False
                continue

            line = transaction.receivable_line_id
            if line.reconciled:
                transaction.payment_state = 'paid'
            elif line.matched_credit_ids or line.matched_debit_ids:
                transaction.payment_state = 'partial'
            else:
                transaction.payment_state = 'not_paid'

            partials = line.matched_credit_ids | line.matched_debit_ids
            transaction.payment_date = max(partials.mapped('max_date')) if partials else False

    @api.depends('partner_id')
    def _compute_journal_id(self):
        for transaction in self:
            company = transaction.partner_id.company_id or self.env.company
            transaction.journal_id = company.equity_journal_id or self.env['account.journal'].search(
                [('type', '=', 'general'), ('company_id', '=', company.id)],
                limit=1,
            )

    def action_post(self):
        for transaction in self:
            if transaction.state != 'draft':
                raise UserError(_("Only draft transactions can be posted."))
            transaction._check_accounting_config()
            move = transaction._create_accounting_move()
            if move:
                move.action_post()
                transaction.move_id = move
                company = transaction.partner_id.company_id or self.env.company
                receivable_line = move.line_ids.filtered(
                    lambda l: l.account_id == company.equity_receivable_account_id
                )[:1]
                if receivable_line:
                    transaction.receivable_line_id = receivable_line
                    receivable_line.equity_transaction_id = transaction
            transaction.state = 'posted'
        self.env['equity.cap.table'].invalidate_model()

    def action_cancel(self):
        for transaction in self:
            if transaction.state == 'cancelled':
                raise UserError(_("Transaction is already cancelled."))
            if transaction.move_id and transaction.move_id.state == 'posted':
                reversal = transaction.move_id._reverse_moves(
                    default_values_list=[{
                        'ref': _("Reversal of: %s", transaction.move_id.ref or transaction.move_id.name),
                        'date': fields.Date.today(),
                    }]
                )
                reversal.action_post()
            elif transaction.move_id and transaction.move_id.state == 'draft':
                transaction.move_id.button_cancel()
            transaction.state = 'cancelled'
        self.env['equity.cap.table'].invalidate_model()

    def action_draft(self):
        for transaction in self:
            if transaction.state != 'cancelled':
                raise UserError(_("Only cancelled transactions can be reset to draft."))
            if transaction.move_id:
                raise UserError(
                    _("Cannot reset to draft: a journal entry already exists. Cancel the journal entry first.")
                )
            transaction.state = 'draft'

    def _check_accounting_config(self):
        """Validate that required accounting configuration is present before posting."""
        self.ensure_one()
        if self.transaction_type not in ('issuance', 'cancellation'):
            return
        if not self.security_class_id.equity_account_id:
            raise UserError(
                _("No subscribed capital account configured for share class '%s'. "
                  "Please set it in Equity > Configuration > Security Classes.",
                  self.security_class_id.name)
            )
        company = self.partner_id.company_id or self.env.company
        if not company.equity_receivable_account_id:
            raise UserError(
                _("No capital contributions receivable account configured. "
                  "Please set it in Settings > Accounting > Equity Configuration.")
            )

    def _create_accounting_move(self):
        """Create a journal entry for issuance or cancellation transactions.

        Issuance:  Dr Bank  /  Cr Subscribed Capital + Cr Capital Reserve (agio)
        Cancellation: Dr Subscribed Capital + Dr Capital Reserve  /  Cr Bank
        Transfer: no entry (shareholder-to-shareholder, not a balance sheet event)
        Exercise: no entry (option pool mechanics, typically handled separately)
        """
        self.ensure_one()
        if self.transaction_type not in ('issuance', 'cancellation'):
            return None

        company = self.partner_id.company_id or self.env.company
        receivable_account = company.equity_receivable_account_id
        equity_account = self.security_class_id.equity_account_id
        reserve_account = self.security_class_id.capital_reserve_account_id

        currency = self.equity_currency_id or company.currency_id
        total_amount = self.transfer_amount
        par_value = self.security_class_id.par_value or 0.0
        nominal_amount = self.securities * par_value
        agio_amount = total_amount - nominal_amount

        # If no par value configured, full amount goes to equity account
        if not par_value or not reserve_account:
            nominal_amount = total_amount
            agio_amount = 0.0

        if self.transaction_type == 'issuance':
            # Dr Receivable (full amount)  /  Cr Capital (nominal)  +  Cr Reserve (agio)
            receivable_balance = total_amount
            equity_balance = -nominal_amount
            reserve_balance = -agio_amount if agio_amount else 0.0
        else:
            # cancellation: reverse
            receivable_balance = -total_amount
            equity_balance = nominal_amount
            reserve_balance = agio_amount if agio_amount else 0.0

        line_vals = [
            Command.create({
                'account_id': receivable_account.id,
                'balance': receivable_balance,
                'currency_id': currency.id,
                'partner_id': self.subscriber_id.id if self.subscriber_id else False,
                'name': self.display_name,
            }),
            Command.create({
                'account_id': equity_account.id,
                'balance': equity_balance,
                'currency_id': currency.id,
                'partner_id': self.subscriber_id.id if self.subscriber_id else False,
                'name': self.display_name,
            }),
        ]

        if agio_amount and reserve_account:
            line_vals.append(Command.create({
                'account_id': reserve_account.id,
                'balance': reserve_balance,
                'currency_id': currency.id,
                'partner_id': self.subscriber_id.id if self.subscriber_id else False,
                'name': _("Share premium (Agio) – %s", self.display_name),
            }))

        move_type_label = _("Issuance") if self.transaction_type == 'issuance' else _("Cancellation")
        ref = _("%(type)s – %(securities).2f × %(class_name)s (%(partner)s)",
                type=move_type_label,
                securities=self.securities,
                class_name=self.security_class_id.name,
                partner=self.subscriber_id.display_name if self.subscriber_id else '',
                )

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': ref,
            'company_id': company.id,
            'line_ids': line_vals,
        })
        return move
