import csv
import itertools
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta, datetime

import pytz

from core.bootstrap import init_core_module_for_simulations
from core.domain import services as rebalancing_services
from core.domain.distribution import EqualDistribution
from shared.domain.dependencies import dependency_dispatcher


assets = [
    'BTC',
    'ETH',
    'BNB',
    'VET',
    'ADA',
    'EOS',
    'MATIC',
    'NANO',
    'XLM',
    'ATOM',
    'LINK',
    'LTC',

    # 'UNI',
    # 'DOT',
    # 'SOL',
    # 'AAVE',

]


def get_all_assets_combinations():
    for n in range(len(assets)):
        for combination in list(itertools.combinations(assets, n + 1)):
            yield list(combination)


# simulation date ranges
starting_date = datetime(2019, 8, 1, 0, 0, 0).replace(tzinfo=pytz.utc)
ending_date = datetime(2021, 6, 1, 0, 0, 0).replace(tzinfo=pytz.utc)

simulation_dates = []
start = starting_date
while True:
    end = start + timedelta(days=300)
    if end > ending_date:
        break
    simulation_dates.append((start, end, ''))
    start += timedelta(days=30)


periods = {
    '1h': timedelta(hours=1),
    '1d': timedelta(days=1),
    '1w': timedelta(days=7),
    '2w': timedelta(days=14),
}

exposures = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]

fiat_asset = 'USDT'
fiat_decimals = 2
fiat_untouched = len(assets) * 5.0
initial_fiat_invest = 3000


exchange = None


def main():
    global exchange
    init_core_module_for_simulations()

    from core.domain.interfaces import AbstractExchange
    exchange = dependency_dispatcher.request_implementation(AbstractExchange)

    # maybe we can use this data for the study
    # read activity/README.md
    # init_activity_module()

    n = 0
    for starting_date, end_date, tag in simulation_dates:
        for exposure in exposures:
            for current_assets in get_all_assets_combinations():
                if len(current_assets) < 8:
                    continue
                for period in periods.keys():
                    n += 1

    current_n = 0
    futures = []
    with ProcessPoolExecutor(max_workers=multiprocessing.cpu_count() - 1) as p:
        for starting_date, end_date, tag in simulation_dates:
            for exposure in exposures:
                for current_assets in get_all_assets_combinations():
                    if len(current_assets) < 8:
                        continue
                    for period in periods.keys():
                        args = (starting_date, end_date, current_assets, exposure, period, tag, n, current_n + 1)
                        current_n += 1
                        # future = _processing_function(*args)
                        future = p.submit(_processing_function, *args)
                        futures.append(future)

    with open('simulation.csv', mode='w') as simulation_file:
        simulation_writer = csv.writer(simulation_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        simulation_writer.writerow([
            'Start', 'End', 'Tag', 'No. Assets', 'Assets', 'Period', 'Exposure',
            'Rebalance Fiat Balance', 'HODL Fiat Balance',
            'Rebalance Profit', 'HODL Profit', 'Profit related to HODL strategy',
        ])
        for future in futures:
            # simulation_writer.writerow(future)
            simulation_writer.writerow(future.result())


def _processing_function(starting_date, end_date, current_assets, exposure, period, tag, n, current_n):
    distributor = EqualDistribution(crypto_assets=current_assets)
    now = starting_date

    exchange.reset_balances(fiat_asset, initial_fiat_invest)
    have_hodl_balances = False
    hodl_balances = {}

    # reset all exchange data.
    # set initial fiat investment.
    while now < end_date:
        # empezar en el día que sea, e iterar periodo a periodo rebalanceando
        # los resultados tendrían que ser volcados a un CSV con las columnas:

        rebalancing_services.rebalance(
            crypto_assets=current_assets,
            fiat_asset=fiat_asset,
            fiat_decimals=fiat_decimals,
            fiat_untouched=fiat_untouched,
            exposure=exposure,
            with_confirmation=False,
            now=now,
            distribution=distributor,
            quiet=True
        )

        if not have_hodl_balances:
            hodl_balances = {fiat_asset: 0.0}
            for asset in current_assets:
                fiat_for_asset = (distributor.assign_percentage(asset) / 100) * initial_fiat_invest
                asset_price = exchange.get_asset_price(asset, fiat_asset, instant=now)
                # 0.999 is for binance fees
                hodl_balances[asset] = (fiat_for_asset * 0.999) / asset_price
            have_hodl_balances = True

        now += periods[period]

    if now > end_date:
        now = end_date
        rebalancing_services.rebalance(
            crypto_assets=current_assets,
            fiat_asset=fiat_asset,
            fiat_decimals=fiat_decimals,
            fiat_untouched=fiat_untouched,
            exposure=exposure,
            with_confirmation=False,
            now=now,
            distribution=distributor,
            quiet=True
        )

    # save all produced data to use later for the study
    last_execution_balances = dict(exchange.balances)
    hodl_total_fiat_balance = compute_fiat_balance(hodl_balances, now)
    rebalance_fiat_balance = compute_fiat_balance(last_execution_balances, now)

    hodl_profit = round(((hodl_total_fiat_balance - initial_fiat_invest) / initial_fiat_invest) * 100, 2)
    rebalance_profit = round(((rebalance_fiat_balance - initial_fiat_invest) / initial_fiat_invest) * 100, 2)
    diff_profit = ((rebalance_fiat_balance - hodl_total_fiat_balance) / hodl_total_fiat_balance) * 100.0
    row = [
        starting_date, end_date, tag,
        len(current_assets), ','.join(current_assets),
        period, exposure,
        rebalance_fiat_balance, hodl_total_fiat_balance,
        rebalance_profit, hodl_profit, diff_profit,
    ]
    print(f'--- {current_n}/{n} ---')
    return row


def compute_fiat_balance(balances, now):
    total_fiat_balance = balances.get(fiat_asset, 0.0)
    for asset, balance in balances.items():
        if asset == fiat_asset:
            continue
        total_fiat_balance += exchange.get_asset_price(asset, fiat_asset, instant=now) * balance
    return total_fiat_balance


if __name__ == '__main__':
    main()
