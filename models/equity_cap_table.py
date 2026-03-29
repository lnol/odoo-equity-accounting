from collections import defaultdict
from datetime import datetime

from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools import SQL


class EquityCapTable(models.Model):
    _inherit = 'equity.cap.table'

    @property
    def _table_query(self):
        # SYNCHRONIZED COPY of equity.cap.table._table_query (src/enterprise/equity/models/equity_cap_table.py)
        # Extended to filter transactions by state='posted' so that draft and cancelled
        # transactions from equity_accounting do not affect cap table calculations.
        # When equity_accounting is installed, all pre-existing transactions are set to
        # state='posted' via post_init_hook, so this filter is backward-compatible.
        self.env['equity.transaction'].flush_model()
        current_date = self.env.context.get('current_date') or datetime.max.date()

        domain = Domain('date', '<=', current_date) & Domain('state', '=', 'posted')
        if current_transaction_id := self.env.context.get('current_transaction_id'):
            domain &= Domain('id', '!=', current_transaction_id)
        transactions_query = self.env['equity.transaction']._search(domain)
        exercise_transactions_query = self.env['equity.transaction']._search(
            domain & Domain('transaction_type', '=', 'exercise')
        )
        transfer_transactions_query = self.env['equity.transaction']._search(
            domain & Domain('transaction_type', '=', 'transfer')
        )
        all_transactions = SQL(" UNION ALL ").join([
            transactions_query.select(
                'partner_id AS partner_id',
                'subscriber_id AS holder_id',
                'security_class_id AS security_class_id',
                """(CASE
                        WHEN transaction_type IN ('issuance', 'transfer') THEN securities
                        ELSE -securities
                    END) AS securities""",
            ),
            exercise_transactions_query.select(
                'partner_id AS partner_id',
                'subscriber_id AS holder_id',
                'destination_class_id AS security_class_id',
                'securities AS securities',
            ),
            transfer_transactions_query.select(
                'partner_id AS partner_id',
                'seller_id AS holder_id',
                'security_class_id AS security_class_id',
                '-securities AS securities',
            ),
        ])
        return SQL(
            """
                WITH transactions AS (%(all_transactions)s),
                     security_class AS (
                        SELECT *,
                               CASE WHEN class_type = 'shares' THEN 1 ELSE 0 END AS share_factor,
                               CASE WHEN dividend_payout THEN 1 ELSE 0 END AS dp_factor
                          FROM equity_security_class
                     )
              SELECT CONCAT(partner_id, '-', holder_id, '-', security_class_id, '-', %(current_date)s) AS id,
                     partner_id,
                     holder_id,
                     security_class_id,
                     SUM(securities) AS securities,
                     SUM(securities * security_class.share_votes) AS votes,
                     SUM(securities * security_class.share_factor) / NULLIF(SUM(SUM(securities * security_class.share_factor)) OVER by_partner, 0) AS ownership,
                     SUM(securities * security_class.share_votes) / NULLIF(SUM(SUM(securities * security_class.share_votes)) OVER by_partner, 0) AS voting_rights,
                     SUM(securities * security_class.dp_factor) / NULLIF(SUM(SUM(securities * security_class.dp_factor)) OVER by_partner, 0) AS dividend_payout,
                     SUM(securities) / NULLIF(SUM(SUM(securities)) OVER by_partner, 0) AS dilution,
                     SUM(securities) / NULLIF((SUM(SUM(securities)) OVER by_partner), 0) * last_valuation.valuation AS valuation
                FROM transactions
                JOIN security_class ON security_class.id = transactions.security_class_id
   LEFT JOIN LATERAL (
                        SELECT valuation
                          FROM equity_valuation
                         WHERE partner_id = transactions.partner_id
                           AND date <= %(current_date)s
                      ORDER BY date DESC
                         LIMIT 1
                     ) last_valuation ON TRUE
            GROUP BY partner_id, holder_id, security_class_id, last_valuation.valuation
              WINDOW by_partner AS (PARTITION BY partner_id)
            """,
            all_transactions=all_transactions,
            current_date=current_date,
        )
