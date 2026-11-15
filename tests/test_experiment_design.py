"""Check prospective power, historical enrollment, and scenario assumptions."""

import sys
import unittest
from datetime import date,timedelta
from pathlib import Path

import numpy as np
from scipy.stats import norm

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from experiment_design import proportion_power,sample_size,historical_replay,value_scenario,plan_experiment


class ExperimentDesignTests(unittest.TestCase):
    def test_null_power_and_minimal_integer_sample(self):
        self.assertAlmostEqual(proportion_power(.2,0,1000),.05)
        result=sample_size(.2,.02)
        n=result['n_per_group']
        self.assertGreaterEqual(proportion_power(.2,.02,n),.8)
        self.assertLess(proportion_power(.2,.02,n-1),.8)
        self.assertEqual(result['total_users'],2*n)
        self.assertGreater(sample_size(.2,.01)['n_per_group'],n)

    def test_power_agrees_with_simulated_pooled_z_test(self):
        n=sample_size(.2,.02)['n_per_group']
        rng=np.random.default_rng(20261115)
        control=rng.binomial(n,.2,50000)
        treatment=rng.binomial(n,.22,50000)
        pooled=(control+treatment)/(2*n)
        observed=(treatment-control)/n/np.sqrt(2*pooled*(1-pooled)/n)
        rejection=float(np.mean(np.abs(observed)>norm.ppf(.975)))
        self.assertAlmostEqual(rejection,proportion_power(.2,.02,n),delta=.01)

    def daily(self,days,count):
        return [{'entry_date_utc':(date(2019,11,1)+timedelta(days=i)).isoformat(),'enrolled_users':count} for i in range(days)]

    def test_replay_rounds_enrollment_to_weeks_then_waits_full_outcome(self):
        result=historical_replay(self.daily(40,100),1500,7,14)
        self.assertEqual(result['raw_enrollment_days'],15)
        self.assertEqual(result['enrollment_days'],21)
        self.assertEqual(result['total_days'],28)
        self.assertEqual(result['readout_date'],'2019-11-29')
        self.assertEqual(historical_replay(self.daily(40,100),100,7,14)['total_days'],21)

    def test_replay_does_not_extrapolate_past_available_history(self):
        self.assertEqual(historical_replay(self.daily(10,10),1000,7,14)['status'],'insufficient_history')
        self.assertEqual(historical_replay(self.daily(10,10),100,7,14)['status'],'readout_outside_history')
        self.assertEqual(historical_replay([],100,7,14)['status'],'no_history')

    def test_value_scenario_has_explicit_units_and_zero_lift(self):
        result=value_scenario(.25,.01,40,10000)
        self.assertEqual(result['additional_converted_users'],100)
        self.assertEqual(result['additional_positive_purchase_value'],4000)
        self.assertEqual(value_scenario(.25,0,40,10000)['additional_positive_purchase_value'],0)

    def test_invalid_planning_inputs_are_rejected(self):
        for baseline,uplift in [(0,.01),(.99,.02),(.2,-.01),(.2,0)]:
            with self.assertRaises(ValueError):sample_size(baseline,uplift)
        with self.assertRaises(ValueError):proportion_power(.2,.01,float('nan'))
        with self.assertRaises(ValueError):value_scenario(.2,.01,-1,10000)
        with self.assertRaises(ValueError):value_scenario(.2,.9,40,10000)

    def settings(self):
        return {'primary_timestamp_rule':'allow_equal','scenario_uplifts_absolute':[0,.005,.01,.02],
                'primary_mde_absolute':.01,'scenario_population':10000,'alpha':.05,'power':.8,
                'horizon_days':7,'minimum_enrollment_days':14,'study_budget_days':28,
                'value_assumption':'constant_value_per_converted_user'}

    def test_integrated_plan_keeps_reference_and_primary_scenario(self):
        summary=[{'timestamp_rule':'allow_equal','conversion_rate':.25,'mean_value_per_converted_user':40}]
        design=plan_experiment(summary,self.daily(40,10000),self.settings())
        self.assertEqual(design['status'],'planned')
        self.assertEqual(len(design['scenarios']),4)
        self.assertEqual(design['primary']['absolute_uplift'],.01)
        self.assertEqual(design['primary']['additional_positive_purchase_value'],4000)
        self.assertTrue(design['primary']['within_study_budget'])
        self.assertIsNone(design['scenarios'][0]['n_per_group'])
        budget = design['budget_assessment']
        self.assertEqual(budget['historical_enrolled_users'],210000)
        self.assertLess(budget['minimum_detectable_absolute_uplift'],.01)
        self.assertAlmostEqual(proportion_power(.25,budget['minimum_detectable_absolute_uplift'],
                                               budget['expected_users_per_group']),.8)

    def test_empty_and_boundary_baselines_do_not_invent_sample_sizes(self):
        for rate,status in [(None,'no_mature_users'),(0,'boundary_baseline'),(1,'boundary_baseline')]:
            design=plan_experiment([{'timestamp_rule':'allow_equal','conversion_rate':rate}],[],self.settings())
            self.assertEqual(design['status'],status)
            self.assertEqual(design['scenarios'],[])


if __name__=='__main__':
    unittest.main()
