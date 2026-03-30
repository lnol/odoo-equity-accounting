# Part of Custom. See LICENSE file for full copyright and licensing details.

from odoo.tests import tagged

from .common import EquityAccountingCommon


@tagged('post_install', '-at_install')
class TestAccountMoveLink(EquityAccountingCommon):
    """Tests for the account.move ↔ equity.transaction reverse link."""

    def test_equity_transaction_id_on_move_line(self):
        """After posting, the receivable move line carries equity_transaction_id."""
        tx = self._make_issuance()
        tx.action_post()

        self.assertTrue(tx.receivable_line_id)
        self.assertEqual(
            tx.receivable_line_id.equity_transaction_id,
            tx,
            "equity_transaction_id on the receivable move line must point back to the transaction",
        )

    def test_equity_transaction_id_on_move(self):
        """After posting, account.move.equity_transaction_id is computed from line_ids."""
        tx = self._make_issuance()
        tx.action_post()

        self.assertEqual(
            tx.move_id.equity_transaction_id,
            tx,
            "account.move.equity_transaction_id must resolve to the originating transaction",
        )

    def test_smart_button_action_returns_form(self):
        """action_open_equity_transaction() returns a form action for the correct transaction."""
        tx = self._make_issuance()
        tx.action_post()

        action = tx.move_id.action_open_equity_transaction()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'equity.transaction')
        self.assertEqual(
            action['res_id'],
            tx.id,
            "Smart-button action res_id must match the posted transaction id",
        )
        self.assertEqual(action['view_mode'], 'form')

    def test_equity_transaction_id_absent_on_unrelated_move(self):
        """A regular journal entry unrelated to equity has no equity_transaction_id."""
        misc_move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.equity_journal.id,
            'date': '2025-06-01',
            'line_ids': [
                (0, 0, {
                    'account_id': self.bank_account.id,
                    'balance': 100.0,
                    'name': 'Test debit',
                }),
                (0, 0, {
                    'account_id': self.retained_earnings_account.id,
                    'balance': -100.0,
                    'name': 'Test credit',
                }),
            ],
        })
        misc_move.action_post()

        self.assertFalse(
            misc_move.equity_transaction_id,
            "A non-equity journal entry must not carry an equity_transaction_id",
        )
