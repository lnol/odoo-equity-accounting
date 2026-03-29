import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Set all existing equity.transaction records to state='posted'.

    When equity_accounting is installed on a database that already has transactions
    from the base equity module, those transactions have no 'state' column yet.
    After the column is added, we default them all to 'posted' so the cap table
    continues working correctly (its _table_query now filters by state='posted').
    """
    env.cr.execute(
        """
        UPDATE equity_transaction
           SET state = 'posted'
         WHERE state IS NULL OR state = 'draft'
        """
    )
    count = env.cr.rowcount
    if count:
        _logger.info(
            "equity_accounting: set %d existing transaction(s) to state='posted'.",
            count,
        )
