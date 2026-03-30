# Part of Custom. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase


class EquityAccountingCommon(TransactionCase):
    """Shared fixtures for equity_accounting tests.

    Account codes are prefixed with TST_ to avoid clashing with any real CoA
    that may have been installed.  All accounts are created on the main company
    so the ORM's company_dependent fields (equity_account_id,
    capital_reserve_account_id) resolve correctly.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env.ref('base.main_company')

        # ── Currency ────────────────────────────────────────────────────────
        cls.currency = cls.company.currency_id

        # ── Accounts ────────────────────────────────────────────────────────
        # Capital-contributions receivable  (asset_receivable – reconcilable)
        cls.receivable_account = cls.env['account.account'].create({
            'name': 'TST Capital Contributions Receivable',
            'code': 'TST1298',
            'account_type': 'asset_receivable',
            'reconcile': True,
            'company_ids': [(4, cls.company.id)],
        })
        # Subscribed capital  (equity)
        cls.equity_account = cls.env['account.account'].create({
            'name': 'TST Subscribed Capital',
            'code': 'TST0800',
            'account_type': 'equity',
            'company_ids': [(4, cls.company.id)],
        })
        # Capital reserve / Agio  (equity)
        cls.reserve_account = cls.env['account.account'].create({
            'name': 'TST Capital Reserve',
            'code': 'TST0840',
            'account_type': 'equity',
            'company_ids': [(4, cls.company.id)],
        })
        # Retained earnings  (equity)
        cls.retained_earnings_account = cls.env['account.account'].create({
            'name': 'TST Retained Earnings',
            'code': 'TST0865',
            'account_type': 'equity',
            'company_ids': [(4, cls.company.id)],
        })
        # Dividend payable  (liability_payable – reconcilable)
        cls.dividend_payable_account = cls.env['account.account'].create({
            'name': 'TST Dividend Payable',
            'code': 'TST1700',
            'account_type': 'liability_payable',
            'reconcile': True,
            'company_ids': [(4, cls.company.id)],
        })
        # KapESt / SolZ liability  (liability_current)
        cls.withholding_tax_account = cls.env['account.account'].create({
            'name': 'TST KapESt Liability',
            'code': 'TST1746',
            'account_type': 'liability_current',
            'company_ids': [(4, cls.company.id)],
        })
        # Bank / Cash for dividend payments  (asset_cash)
        cls.bank_account = cls.env['account.account'].create({
            'name': 'TST Dividend Bank',
            'code': 'TST1800',
            'account_type': 'asset_cash',
            'company_ids': [(4, cls.company.id)],
        })

        # ── Equity journal ────────────────────────────────────────────────
        cls.equity_journal = cls.env['account.journal'].create({
            'name': 'TST Equity Journal',
            'code': 'TEQJ',
            'type': 'general',
            'company_id': cls.company.id,
        })

        # ── Company accounting configuration ─────────────────────────────
        cls.company.write({
            'equity_journal_id': cls.equity_journal.id,
            'equity_receivable_account_id': cls.receivable_account.id,
            'equity_bank_account_id': cls.bank_account.id,
            'dividend_payable_account_id': cls.dividend_payable_account.id,
            'withholding_tax_account_id': cls.withholding_tax_account.id,
            'dividend_retained_earnings_account_id': cls.retained_earnings_account.id,
        })

        # ── Investee company partner ──────────────────────────────────────
        cls.investee_partner = cls.env['res.partner'].create({
            'name': 'TST Investee GmbH',
            'is_company': True,
            'equity_currency_id': cls.currency.id,
        })

        # ── Shareholders ──────────────────────────────────────────────────
        cls.investor_a = cls.env['res.partner'].create({
            'name': 'TST Investor Alpha',
            'is_company': False,
        })
        cls.investor_b = cls.env['res.partner'].create({
            'name': 'TST Investor Beta',
            'is_company': False,
        })

        # ── Share class (with par value and reserve account) ──────────────
        cls.share_class = cls.env['equity.security.class'].create({
            'name': 'TST Ordinary Shares',
            'class_type': 'shares',
            'share_votes': 1,
            'dividend_payout': True,
            'par_value': 10.0,
            'par_value_currency_id': cls.currency.id,
        })
        # company_dependent fields must be written with the right company env
        cls.share_class.with_company(cls.company).write({
            'equity_account_id': cls.equity_account.id,
            'capital_reserve_account_id': cls.reserve_account.id,
        })

    # ── Helper: build a minimal issuance transaction ──────────────────────
    def _make_issuance(
        self,
        securities=100,
        security_price=15.0,
        subscriber=None,
        share_class=None,
        partner=None,
    ):
        """Return a draft issuance equity.transaction record."""
        return self.env['equity.transaction'].create({
            'transaction_type': 'issuance',
            'partner_id': (partner or self.investee_partner).id,
            'subscriber_id': (subscriber or self.investor_a).id,
            'security_class_id': (share_class or self.share_class).id,
            'securities': securities,
            'security_price': security_price,
            'date': '2025-01-15',
        })
