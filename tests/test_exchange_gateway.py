from app.exchange_gateway import _norm_network, ExchangeConfig, ExchangeGateway


def test_network_aliases():
    assert _norm_network('TRC20') == 'TRX'
    assert _norm_network('ERC20') == 'ETH'
    assert _norm_network('TRON') == 'TRX'
    assert _norm_network('LITECOIN') == 'LTC'


def test_dry_run_never_places_order():
    gateway = ExchangeGateway(ExchangeConfig('kraken'))
    result = gateway.create_limit_order('BTC/USD', 'buy', 0.001, 1.0, live=False)
    assert result['dry_run'] is True
    assert result['exchange'] == 'kraken'
