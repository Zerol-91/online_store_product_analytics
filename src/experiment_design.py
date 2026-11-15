"""Plan an equal-allocation two-proportion test and explicit value scenarios."""

import math
from datetime import date, timedelta

from scipy.optimize import brentq
from scipy.stats import norm


def proportion_power(baseline, uplift, n_per_group, alpha=0.05):
    if not all(math.isfinite(x) for x in (baseline,uplift,n_per_group,alpha)):
        raise ValueError('Use finite test parameters.')
    if not 0<baseline<1 or uplift<0 or baseline+uplift>=1 or n_per_group<=0 or not 0<alpha<1:
        raise ValueError('Use valid proportions, positive sample size, and alpha.')
    treatment=baseline+uplift
    pooled=(baseline+treatment)/2
    null_se=math.sqrt(2*pooled*(1-pooled)/n_per_group)
    alternative_se=math.sqrt((baseline*(1-baseline)+treatment*(1-treatment))/n_per_group)
    critical=norm.ppf(1-alpha/2)*null_se
    return float(norm.sf((critical-uplift)/alternative_se)+norm.cdf((-critical-uplift)/alternative_se))


def sample_size(baseline,uplift,alpha=0.05,power=0.80):
    if not math.isfinite(power) or not alpha<power<1 or uplift<=0:
        raise ValueError('Use a positive MDE and target power between alpha and one.')
    proportion_power(baseline,uplift,1,alpha)
    upper=100
    while proportion_power(baseline,uplift,upper,alpha)<power:
        upper*=2
        if upper>10**12:
            raise ValueError('Required sample size exceeds the planning limit.')
    root=brentq(lambda n:proportion_power(baseline,uplift,n,alpha)-power,1,upper)
    n=math.ceil(root)
    while n>1 and proportion_power(baseline,uplift,n-1,alpha)>=power:
        n-=1
    while proportion_power(baseline,uplift,n,alpha)<power:
        n+=1
    return {'n_per_group':n,'total_users':2*n,'achieved_power':proportion_power(baseline,uplift,n,alpha)}


def historical_replay(daily,total_users,horizon_days,minimum_enrollment_days):
    if type(total_users) is not int or total_users<=0 or horizon_days<=0 or minimum_enrollment_days<7:
        raise ValueError('Use a positive sample/outcome window and at least one enrollment week.')
    if not daily:
        return {'status':'no_history','enrollment_days':None,'total_days':None}
    start=date.fromisoformat(str(daily[0]['entry_date_utc']))
    cumulative=0
    reached=None
    for row in daily:
        cumulative+=row['enrolled_users']
        if cumulative>=total_users:
            reached=date.fromisoformat(str(row['entry_date_utc']))
            break
    if reached is None:
        return {'status':'insufficient_history','enrollment_days':None,'total_days':None}
    raw_days=(reached-start).days+1
    enrollment=7*math.ceil(max(raw_days,minimum_enrollment_days)/7)
    end=start+timedelta(days=enrollment+horizon_days)
    observation_end=date.fromisoformat(str(daily[-1]['entry_date_utc']))+timedelta(days=1)
    return {'status':'covered' if end<=observation_end else 'readout_outside_history',
            'sample_reached_on':reached.isoformat(),'raw_enrollment_days':raw_days,
            'enrollment_days':enrollment,'followup_days':horizon_days,'total_days':enrollment+horizon_days,
            'enrollment_start':start.isoformat(),'readout_date':end.isoformat()}


def value_scenario(baseline,uplift,value_per_converted_user,population):
    if not all(math.isfinite(x) for x in (baseline,uplift,value_per_converted_user,population)):
        raise ValueError('Use finite scenario inputs.')
    if not 0<=baseline<=1 or uplift<0 or baseline+uplift>1 or value_per_converted_user<0 or type(population) is not int or population<=0:
        raise ValueError('Use valid rates, nonnegative value, and a positive integer population.')
    return {'absolute_uplift':uplift,'scenario_conversion':baseline+uplift,
            'population':population,'additional_converted_users':population*uplift,
            'assumed_value_per_converted_user':value_per_converted_user,
            'scenario_value_per_user':(baseline+uplift)*value_per_converted_user,
            'additional_positive_purchase_value':population*uplift*value_per_converted_user}


def plan_experiment(summary, daily, settings):
    baseline = next(row for row in summary if row['timestamp_rule'] == settings['primary_timestamp_rule'])
    rate = baseline['conversion_rate']
    if rate is None or not 0 < rate < 1:
        return {'status': 'no_mature_users' if rate is None else 'boundary_baseline', 'scenarios': []}
    conditional_value = float(baseline['mean_value_per_converted_user'])
    scenarios = []
    for uplift in settings['scenario_uplifts_absolute']:
        row = value_scenario(rate, uplift, conditional_value, settings['scenario_population'])
        row['is_primary'] = uplift == settings['primary_mde_absolute']
        if uplift == 0:
            row.update(n_per_group=None, total_users=None, achieved_power=None,
                       replay={'status': 'reference', 'enrollment_days': None, 'total_days': None},
                       within_study_budget=None)
        else:
            row.update(sample_size(rate, uplift, settings['alpha'], settings['power']))
            row['replay'] = historical_replay(daily, row['total_users'], settings['horizon_days'],
                                              settings['minimum_enrollment_days'])
            row['within_study_budget'] = (row['replay']['status'] == 'covered'
                and row['replay']['total_days'] <= settings['study_budget_days'])
        scenarios.append(row)
    enrollment_budget = 7*((settings['study_budget_days']-settings['horizon_days'])//7)
    available_users = sum(row['enrolled_users'] for row in daily[:enrollment_budget])
    available_per_group = available_users//2
    upper_uplift = (1-rate)*(1-1e-9)
    budget_mde = None
    if (available_per_group >= 2
            and proportion_power(rate, upper_uplift, available_per_group, settings['alpha']) >= settings['power']):
        budget_mde = brentq(lambda delta: proportion_power(rate, delta, available_per_group,
                            settings['alpha'])-settings['power'], 0, upper_uplift)
    budget_assessment = {'enrollment_days': enrollment_budget,
        'historical_enrolled_users': available_users, 'expected_users_per_group': available_per_group,
        'history_covers_enrollment_window': len(daily) >= enrollment_budget,
        'minimum_detectable_absolute_uplift': budget_mde}
    return {'status': 'planned', 'baseline_conversion': rate,
            'primary_mde_absolute': settings['primary_mde_absolute'],
            'alpha': settings['alpha'], 'target_power': settings['power'],
            'study_budget_days': settings['study_budget_days'],
            'scenario_population': settings['scenario_population'],
            'value_assumption': settings['value_assumption'],
            'budget_assessment': budget_assessment,
            'primary': next(row for row in scenarios if row['is_primary']), 'scenarios': scenarios}
