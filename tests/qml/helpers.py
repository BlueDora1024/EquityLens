from __future__ import annotations

from stock_toolbox.composition import StockToolboxApplication
from stock_toolbox.core.master_data.models import WatchlistDTO


def seeded_watchlist(application: StockToolboxApplication) -> WatchlistDTO:
    application.import_securities("IREN, NVDA, AMD")
    watchlist = application.master_data.create_watchlist("科技观察")
    application.master_data.add_watchlist_members(
        watchlist.id,
        tuple(
            (security.id, security.bindings[0].id)
            for security in application.master_data.list_securities()
        ),
    )
    return application.master_data.get_watchlist(watchlist.id)
