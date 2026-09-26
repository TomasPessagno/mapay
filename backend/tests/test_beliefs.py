import math
import unittest
from datetime import datetime, timedelta, timezone

from app.routing.beliefs import (
    contribution,
    log_odds,
    prior_probability,
    probability,
    threshold_changes,
)


class BeliefMathTests(unittest.TestCase):
    def test_natural_log_odds_and_posterior(self):
        prior = log_odds(0.2)
        self.assertAlmostEqual(prior, math.log(0.25))
        posterior = prior + 0.5 + 1.5 + 2.5
        self.assertAlmostEqual(posterior, 3.113705638880109)
        self.assertAlmostEqual(probability(posterior), 0.957454562911)
        self.assertAlmostEqual(probability(log_odds(0.73)), 0.73)
        self.assertAlmostEqual(probability(1), 0.73105857863)
        self.assertEqual(probability(-1000), 0)
        self.assertEqual(probability(1000), 1)
        self.assertTrue(math.isfinite(log_odds(0)))
        self.assertTrue(math.isfinite(log_odds(1)))
        with self.assertRaises(ValueError):
            log_odds(float('nan'))

    def test_crowd_and_negative_evidence_decay(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(contribution('crowd', now, now), 1.5)
        self.assertEqual(contribution('crowd', now, now + timedelta(hours=1)), 0.75)
        self.assertEqual(contribution('crowd', now, now + timedelta(hours=3)), 0)
        self.assertEqual(contribution('cleared', now, now + timedelta(hours=1)), -0.75)
        self.assertEqual(contribution('news', now, now + timedelta(days=3)), 0.5)

    def test_prior_inputs(self):
        self.assertAlmostEqual(prior_probability('flood', {
            'fema_zone': 'AE', 'tide_ft_mhhw': 1, 'flood_threshold_ft_mhhw': 1}), 0.6)
        self.assertAlmostEqual(prior_probability('pothole', {'complaints_per_km': 0}), 0.1)
        self.assertEqual(prior_probability('construction', {'status': 'closed'}), 0.95)

    def test_threshold_both_directions_and_equality(self):
        def state(value):
            return {'h': {'log_odds': value, 'prior_log_odds': 0, 'sources': {'crowd': value}}}
        self.assertEqual(len(threshold_changes(state(0.9), state(1))), 1)
        self.assertEqual(len(threshold_changes(state(1.2), state(0.9))), 1)
        self.assertEqual(threshold_changes(state(1.1), state(2)), [])
        self.assertEqual(threshold_changes({}, state(2)), [])
        self.assertEqual(threshold_changes(state(0), state(2))[0]['sources'], ['crowd'])


if __name__ == '__main__':
    unittest.main()
