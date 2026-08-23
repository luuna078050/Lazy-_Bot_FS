from app.orderbook_pressure import OrderBookAnalyzer


def test_large_bid_wall_is_detected():
    analyzer = OrderBookAnalyzer(history_size=5, wall_multiplier=3)
    bids = [(100.0, 100), (99.9, 90), (99.8, 1000), (99.7, 80)]
    asks = [(100.1, 100), (100.2, 90), (100.3, 80), (100.4, 100)]
    signal = analyzer.analyze("TEST/USDC", bids, asks, timestamp=1)
    assert signal.nearest_bid_wall is not None
    assert signal.nearest_bid_wall.price == 99.8


def test_disappearing_wall_raises_spoof_risk():
    analyzer = OrderBookAnalyzer(history_size=5, wall_multiplier=3)
    bids1 = [(100.0, 100), (99.9, 100), (99.8, 1000)]
    asks1 = [(100.1, 100), (100.2, 100), (100.3, 100)]
    analyzer.analyze("TEST/USDC", bids1, asks1, timestamp=1)
    bids2 = [(100.0, 100), (99.9, 100), (99.8, 100)]
    signal = analyzer.analyze("TEST/USDC", bids2, asks1, timestamp=2)
    assert signal.spoof_risk > 0


def test_balanced_book_is_not_strong_signal():
    analyzer = OrderBookAnalyzer()
    bids = [(100.0, 100), (99.9, 100), (99.8, 100)]
    asks = [(100.1, 100), (100.2, 100), (100.3, 100)]
    signal = analyzer.analyze("TEST/USDC", bids, asks)
    assert signal.direction == "neutral"
