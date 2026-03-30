# Part of Custom. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import EquityAccountingCommon


@tagged('post_install', '-at_install')
class TestEquityTransaction(EquityAccountingCommon):
    """Tests for equity.transaction accounting integration."""

    # ── Posting / journal entry creation ─────────────────────────────────

    def test_post_issuance_creates_journal_entry(self):
        """Posting an issuance creates a posted journal entry with the expected lines."""
        tx = self._make_issuance(securities=100, security_price=15.0)
        tx.action_post()

        self.assertEqual(tx.state, 'posted')
        self.assertTrue(tx.move_id, "move_id must be set after posting")
        self.assertEqual(tx.move_id.state, 'posted')

        lines = tx.move_id.line_ids
        # 3 lines: Dr Receivable / Cr Capital (par) / Cr Reserve (agio)
        self.assertGreaterEqual(len(lines), 2)
        self.assertLessEqual(len(lines), 3)

        # receivable_line_id points to the receivable account line
        self.assertTrue(tx.receivable_line_id)
        self.assertEqual(
            tx.receivable_line_id.account_id,
            self.receivable_account,
        )

        # reverse link on the move line
        self.assertEqual(
            tx.receivable_line_id.equity_transaction_id,
            tx,
        )

        # equity_transaction_id on the move itself (computed from line_ids)
        self.assertEqual(tx.move_id.equity_transaction_id, tx)

    def test_post_issuance_with_par_value_splits_agio(self):
        """100 shares @ €15 with par €10 → capital line = €1000, reserve = €500."""
        tx = self._make_issuance(securities=100, security_price=15.0)
        tx.action_post()

        lines = tx.move_id.line_ids
        capital_line = lines.filtered(
            lambda l: l.account_id == self.equity_account
        )
        reserve_line = lines.filtered(
            lambda l: l.account_id == self.reserve_account
        )

        self.assertEqual(len(capital_line), 1, "Expected exactly one capital line")
        self.assertEqual(len(reserve_line), 1, "Expected exactly one reserve (agio) line")

        # Credits are stored as negative balances in Odoo 17+
        self.assertAlmostEqual(abs(capital_line.balance), 1000.0, places=2)
        self.assertAlmostEqual(abs(reserve_line.balance), 500.0, places=2)

    def test_post_issuance_no_par_value_full_to_equity(self):
        """With par_value=0 the full amount goes to the equity account; no reserve line."""
        share_class_no_par = self.env['equity.security.class'].create({
            'name': 'TST No-Par Shares',
            'class_type': 'shares',
            'share_votes': 1,
            'dividend_payout': True,
            'par_value': 0.0,
        })
        share_class_no_par.with_company(self.company).write({
            'equity_account_id': self.equity_account.id,
            'capital_reserve_account_id': self.reserve_account.id,
        })

        tx = self._make_issuance(
            securities=100,
            security_price=15.0,
            share_class=share_class_no_par,
        )
        tx.action_post()

        lines = tx.move_id.line_ids
        reserve_line = lines.filtered(
            lambda l: l.account_id == self.reserve_account
        )
        self.assertFalse(reserve_line, "No reserve line expected when par_value is zero")

        capital_line = lines.filtered(
            lambda l: l.account_id == self.equity_account
        )
        self.assertAlmostEqual(abs(capital_line.balance), 1500.0, places=2)

    # ── Payment state ─────────────────────────────────────────────────────

    def test_payment_state_not_paid_after_post(self):
        """Payment state is 'not_paid' immediately after posting."""
        tx = self._make_issuance()
        tx.action_post()
        self.assertEqual(tx.payment_state, 'not_paid')

    def test_payment_state_paid_after_reconciliation(self):
        """Fully reconciling the receivable line marks the transaction as paid."""
        tx = self._make_issuance(securities=100, security_price=15.0)
        tx.action_post()
        receivable_line = tx.receivable_line_id
        total_amount = tx.transfer_amount  # 1500.0

        # Create and post a counter-entry that credits the receivable account
        payment_move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.equity_journal.id,
            'date': '2025-02-01',
            'line_ids': [
                (0, 0, {
                    'account_id': self.receivable_account.id,
                    'balance': -total_amount,
                    'name': 'Payment of capital contribution',
                }),
                (0, 0, {
                    'account_id': self.bank_account.id,
                    'balance': total_amount,
                    'name': 'Bank receipt',
                }),
            ],
        })
        payment_move.action_post()

        # Reconcile the two receivable lines
        credit_line = payment_move.line_ids.filtered(
            lambda l: l.account_id == self.receivable_account
        )
        (receivable_line | credit_line).reconcile()

        self.assertEqual(tx.payment_state, 'paid')
        self.assertTrue(tx.payment_date)

    def test_payment_state_partial_after_partial_reconciliation(self):
        """Partially reconciling the receivable line gives payment_state = 'partial'."""
        tx = self._make_issuance(securities=100, security_price=15.0)
        tx.action_post()
        receivable_line = tx.receivable_line_id
        total_amount = tx.transfer_amount  # 1500.0
        partial_amount = total_amount / 2  # 750.0

        payment_move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.equity_journal.id,
            'date': '2025-02-01',
            'line_ids': [
                (0, 0, {
                    'account_id': self.receivable_account.id,
                    'balance': -partial_amount,
                    'name': 'Partial payment',
                }),
                (0, 0, {
                    'account_id': self.bank_account.id,
                    'balance': partial_amount,
                    'name': 'Bank receipt',
                }),
            ],
        })
        payment_move.action_post()

        credit_line = payment_move.line_ids.filtered(
            lambda l: l.account_id == self.receivable_account
        )
        (receivable_line | credit_line).reconcile()

        self.assertEqual(tx.payment_state, 'partial')

    # ── Cancellation ─────────────────────────────────────────────────────

    def test_cancel_transaction_reverses_move(self):
        """Cancelling a posted transaction creates a reversal and sets state=cancelled."""
        tx = self._make_issuance()
        tx.action_post()
        original_move = tx.move_id
        tx.action_cancel()

        self.assertEqual(tx.state, 'cancelled')

        # A reversal move should exist — it is a reversed_entry_id of the original
        reversal_moves = self.env['account.move'].search([
            ('reversed_entry_id', '=', original_move.id),
        ])
        self.assertTrue(reversal_moves, "Expected a reversal move after cancellation")
        self.assertEqual(reversal_moves[:1].state, 'posted')

        # payment_state is False for cancelled transactions
        self.assertFalse(tx.payment_state)

    # ── Configuration validation ──────────────────────────────────────────

    def test_cannot_post_without_receivable_account(self):
        """Posting raises UserError when equity_receivable_account_id is not set."""
        self.company.equity_receivable_account_id = False
        tx = self._make_issuance()
        with self.assertRaises(UserError):
            tx.action_post()
        # Restore to avoid side-effects on other tests
        self.company.equity_receivable_account_id = self.receivable_account.id

    def test_cannot_post_without_equity_account_on_class(self):
        """Posting raises UserError when the share class has no equity_account_id."""
        share_class_no_account = self.env['equity.security.class'].create({
            'name': 'TST No-Account Shares',
            'class_type': 'shares',
            'share_votes': 1,
            'dividend_payout': True,
        })
        # Intentionally do NOT set equity_account_id
        tx = self._make_issuance(share_class=share_class_no_account)
        with self.assertRaises(UserError):
            tx.action_post()

    # ── Transfer transaction ──────────────────────────────────────────────

    def test_transfer_has_no_journal_entry(self):
        """Transfer transactions do not create a journal entry or payment state."""
        # First issue shares so the seller actually has something to transfer
        issuance = self._make_issuance(securities=50, security_price=10.0)
        issuance.action_post()

        transfer = self.env['equity.transaction'].create({
            'transaction_type': 'transfer',
            'partner_id': self.investee_partner.id,
            'security_class_id': self.share_class.id,
            'securities': 20,
            'security_price': 10.0,
            'seller_id': self.investor_a.id,
            'subscriber_id': self.investor_b.id,
            'date': '2025-03-01',
        })
        transfer.action_post()

        self.assertFalse(transfer.move_id, "Transfer must not create a journal entry")
        self.assertFalse(transfer.payment_state)
