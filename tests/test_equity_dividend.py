# Part of Custom. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import EquityAccountingCommon


@tagged('post_install', '-at_install')
class TestEquityDividend(EquityAccountingCommon):
    """Tests for equity.dividend — declaration, computation, payment and cancellation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Post two issuance transactions so the cap table has real shareholdings
        tx_a = cls.env['equity.transaction'].create({
            'transaction_type': 'issuance',
            'partner_id': cls.investee_partner.id,
            'subscriber_id': cls.investor_a.id,
            'security_class_id': cls.share_class.id,
            'securities': 600,
            'security_price': 10.0,
            'date': '2025-01-01',
        })
        tx_a.action_post()

        tx_b = cls.env['equity.transaction'].create({
            'transaction_type': 'issuance',
            'partner_id': cls.investee_partner.id,
            'subscriber_id': cls.investor_b.id,
            'security_class_id': cls.share_class.id,
            'securities': 400,
            'security_price': 10.0,
            'date': '2025-01-01',
        })
        tx_b.action_post()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _make_dividend(
        self,
        amount_per_share=1.0,
        apply_withholding=False,
        payment_date='2025-04-30',
    ):
        """Return a draft equity.dividend for the investee partner."""
        return self.env['equity.dividend'].create({
            'partner_id': self.investee_partner.id,
            'company_id': self.company.id,
            'date': '2025-03-31',
            'payment_date': payment_date,
            'amount_per_share': amount_per_share,
            'apply_withholding_tax': apply_withholding,
            'journal_id': self.equity_journal.id,
            'retained_earnings_account_id': self.retained_earnings_account.id,
            'dividend_payable_account_id': self.dividend_payable_account.id,
            'withholding_tax_account_id': self.withholding_tax_account.id,
        })

    # ── Line computation ──────────────────────────────────────────────────

    def test_compute_lines_creates_one_line_per_holder(self):
        """action_compute_lines() produces one line per shareholder with correct amounts."""
        dividend = self._make_dividend(amount_per_share=2.0)
        dividend.action_compute_lines()

        self.assertEqual(
            len(dividend.line_ids), 2,
            "Expected exactly two distribution lines (one per investor)",
        )

        holder_map = {line.holder_id: line for line in dividend.line_ids}

        line_a = holder_map.get(self.investor_a)
        self.assertTrue(line_a, "Missing line for investor A")
        self.assertAlmostEqual(line_a.shares, 600, places=2)
        self.assertAlmostEqual(line_a.gross_amount, 600 * 2.0, places=2)

        line_b = holder_map.get(self.investor_b)
        self.assertTrue(line_b, "Missing line for investor B")
        self.assertAlmostEqual(line_b.shares, 400, places=2)
        self.assertAlmostEqual(line_b.gross_amount, 400 * 2.0, places=2)

    # ── Declaration ───────────────────────────────────────────────────────

    def test_declare_creates_journal_entry(self):
        """action_declare() posts a journal entry with retained-earnings, payable, and withholding lines."""
        dividend = self._make_dividend(amount_per_share=1.0, apply_withholding=True)
        dividend.action_compute_lines()
        dividend.action_declare()

        self.assertEqual(dividend.state, 'declared')
        self.assertTrue(
            dividend.declaration_move_id,
            "declaration_move_id must be set after declaring",
        )
        self.assertEqual(dividend.declaration_move_id.state, 'posted')

        lines = dividend.declaration_move_id.line_ids

        # Dr Retained Earnings
        re_line = lines.filtered(
            lambda l: l.account_id == self.retained_earnings_account
        )
        self.assertTrue(re_line, "Expected a retained-earnings debit line")
        self.assertGreater(re_line.balance, 0, "Retained earnings line must be a debit")

        # Cr Dividend Payable
        payable_lines = lines.filtered(
            lambda l: l.account_id == self.dividend_payable_account
        )
        self.assertTrue(payable_lines, "Expected at least one dividend-payable credit line")
        total_payable = abs(sum(payable_lines.mapped('balance')))
        self.assertAlmostEqual(
            total_payable, dividend.total_net_amount, places=2,
        )

        # Cr Withholding Tax
        wht_line = lines.filtered(
            lambda l: l.account_id == self.withholding_tax_account
        )
        self.assertTrue(wht_line, "Expected a withholding-tax credit line")
        self.assertLess(wht_line.balance, 0, "Withholding-tax line must be a credit")

    def test_declare_without_withholding(self):
        """Without apply_withholding_tax there is no withholding line and net == gross."""
        dividend = self._make_dividend(amount_per_share=1.0, apply_withholding=False)
        dividend.action_compute_lines()
        dividend.action_declare()

        self.assertAlmostEqual(
            dividend.total_net_amount, dividend.total_gross_amount, places=2,
        )

        lines = dividend.declaration_move_id.line_ids
        wht_line = lines.filtered(
            lambda l: l.account_id == self.withholding_tax_account
        )
        self.assertFalse(
            wht_line,
            "No withholding-tax line expected when apply_withholding_tax is False",
        )

    # ── Payment ───────────────────────────────────────────────────────────

    def test_pay_line_creates_payment_entry(self):
        """Paying a single line posts a journal entry (Dr Payable / Cr Bank) and marks it paid."""
        dividend = self._make_dividend(amount_per_share=1.0)
        dividend.action_compute_lines()
        dividend.action_declare()

        line = dividend.line_ids[0]
        line.action_pay()

        self.assertEqual(line.payment_state, 'paid')
        self.assertTrue(line.payment_move_id, "Expected a payment journal entry on the line")
        self.assertEqual(line.payment_move_id.state, 'posted')

        pay_lines = line.payment_move_id.line_ids
        payable_debit = pay_lines.filtered(
            lambda l: l.account_id == self.dividend_payable_account
        )
        bank_credit = pay_lines.filtered(
            lambda l: l.account_id == self.bank_account
        )
        self.assertTrue(payable_debit, "Expected a debit on dividend-payable account")
        self.assertTrue(bank_credit, "Expected a credit on bank account")
        self.assertGreater(payable_debit.balance, 0)
        self.assertLess(bank_credit.balance, 0)

    def test_pay_all_marks_dividend_paid(self):
        """action_pay_all() pays every line and transitions the dividend to 'paid'."""
        dividend = self._make_dividend(amount_per_share=0.5)
        dividend.action_compute_lines()
        dividend.action_declare()

        dividend.action_pay_all()

        self.assertTrue(
            all(l.payment_state == 'paid' for l in dividend.line_ids),
            "All lines must be paid after action_pay_all()",
        )
        self.assertEqual(dividend.state, 'paid')

    def test_pay_all_raises_if_already_paid(self):
        """Calling action_pay_all() a second time raises UserError."""
        dividend = self._make_dividend(amount_per_share=0.5)
        dividend.action_compute_lines()
        dividend.action_declare()
        dividend.action_pay_all()

        with self.assertRaises(UserError):
            dividend.action_pay_all()

    # ── Cancellation ──────────────────────────────────────────────────────

    def test_cancel_reverses_declaration(self):
        """Cancelling a declared dividend creates a posted reversal of the declaration move."""
        dividend = self._make_dividend(amount_per_share=1.0)
        dividend.action_compute_lines()
        dividend.action_declare()
        original_move = dividend.declaration_move_id

        dividend.action_cancel()

        self.assertEqual(dividend.state, 'cancelled')

        reversal = self.env['account.move'].search([
            ('reversed_entry_id', '=', original_move.id),
        ])
        self.assertTrue(reversal, "Expected a reversal move after cancelling the dividend")
        self.assertEqual(reversal[:1].state, 'posted')

    def test_cancel_raises_if_fully_paid(self):
        """Cannot cancel a fully paid dividend."""
        dividend = self._make_dividend(amount_per_share=0.5)
        dividend.action_compute_lines()
        dividend.action_declare()
        dividend.action_pay_all()

        with self.assertRaises(UserError):
            dividend.action_cancel()
