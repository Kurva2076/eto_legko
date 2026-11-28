import unittest
from types import SimpleNamespace

from app.enums import OfferChangeKind, OfferStatus
from app.stream_logic import (
    has_unsynced_changes,
    offer_change_kind,
    offers_payload,
    recalculate_shares,
    total_share,
)


def make_offer(offer_id, share=0, pinned=False, status=OfferStatus.ACTIVE, state='active'):
    return SimpleNamespace(offer_id=offer_id, share=share, pinned=pinned, status=status, keitaro_state=state)


def shares_of(offers):
    return [offer.share for offer in offers]


class RecalculateSharesTest(unittest.TestCase):
    def test_equal_split_gives_remainder_to_first_offers(self):
        offers = [make_offer(1), make_offer(2), make_offer(3)]
        recalculate_shares(offers)
        self.assertEqual(shares_of(offers), [34, 33, 33])

    def test_single_offer_gets_everything(self):
        offers = [make_offer(1)]
        recalculate_shares(offers)
        self.assertEqual(shares_of(offers), [100])

    def test_pinned_offer_keeps_share_and_rest_is_split(self):
        offers = [make_offer(1, 50, pinned=True), make_offer(2), make_offer(3)]
        recalculate_shares(offers)
        self.assertEqual(shares_of(offers), [50, 25, 25])
        self.assertEqual(total_share(offers), 100)

    def test_pinned_with_remainder(self):
        offers = [make_offer(1, 50, pinned=True), make_offer(2), make_offer(3), make_offer(4)]
        recalculate_shares(offers)
        self.assertEqual(shares_of(offers), [50, 17, 17, 16])
        self.assertEqual(total_share(offers), 100)

    def test_removed_offers_are_ignored_and_keep_their_share(self):
        offers = [make_offer(1), make_offer(2, 40, status=OfferStatus.REMOVED), make_offer(3)]
        recalculate_shares(offers)
        self.assertEqual(shares_of(offers), [50, 40, 50])

    def test_all_pinned_changes_nothing(self):
        offers = [make_offer(1, 30, pinned=True), make_offer(2, 30, pinned=True)]
        recalculate_shares(offers)
        self.assertEqual(shares_of(offers), [30, 30])
        self.assertEqual(total_share(offers), 60)

    def test_pinned_take_everything_new_offer_gets_zero(self):
        offers = [make_offer(1, 60, pinned=True), make_offer(2, 40, pinned=True), make_offer(3)]
        recalculate_shares(offers)
        self.assertEqual(shares_of(offers), [60, 40, 0])

    def test_no_offers_is_fine(self):
        recalculate_shares([])

    def test_add_then_remove_scenario_with_pin(self):
        offers = [make_offer(1), make_offer(2)]
        recalculate_shares(offers)
        self.assertEqual(shares_of(offers), [50, 50])

        offers[0].pinned = True
        offers.append(make_offer(3))
        recalculate_shares(offers)
        self.assertEqual(shares_of(offers), [50, 25, 25])

        offers[1].status = OfferStatus.REMOVED
        offers[1].pinned = False
        recalculate_shares(offers)
        self.assertEqual(offers[0].share, 50)
        self.assertEqual(offers[2].share, 50)
        self.assertEqual(total_share(offers), 100)


class UnsyncedChangesTest(unittest.TestCase):
    def setUp(self):
        self.synced = [
            {'offer_id': 1, 'share': 50, 'state': 'active'},
            {'offer_id': 2, 'share': 50, 'state': 'active'},
        ]

    def offers(self):
        return [make_offer(1, 50), make_offer(2, 50)]

    def test_same_state_has_no_changes(self):
        self.assertFalse(has_unsynced_changes(self.offers(), 'landings', self.synced, 'landings'))

    def test_order_does_not_matter(self):
        offers = list(reversed(self.offers()))
        self.assertFalse(has_unsynced_changes(offers, 'landings', self.synced, 'landings'))

    def test_share_change_is_detected(self):
        offers = self.offers()
        offers[0].share = 60
        self.assertTrue(has_unsynced_changes(offers, 'landings', self.synced, 'landings'))

    def test_removed_offer_is_a_change(self):
        offers = self.offers()
        offers[1].status = OfferStatus.REMOVED
        self.assertTrue(has_unsynced_changes(offers, 'landings', self.synced, 'landings'))

    def test_added_then_removed_offer_is_not_a_change(self):
        offers = self.offers() + [make_offer(3, 0, status=OfferStatus.REMOVED)]
        self.assertFalse(has_unsynced_changes(offers, 'landings', self.synced, 'landings'))

    def test_added_offer_is_a_change(self):
        offers = self.offers() + [make_offer(3, 0)]
        self.assertTrue(has_unsynced_changes(offers, 'landings', self.synced, 'landings'))

    def test_schema_change_is_detected(self):
        self.assertTrue(has_unsynced_changes(self.offers(), 'landings', self.synced, 'redirect'))

    def test_pin_alone_is_not_a_change(self):
        offers = self.offers()
        offers[0].pinned = True
        self.assertFalse(has_unsynced_changes(offers, 'landings', self.synced, 'landings'))

    def test_purged_offer_that_exists_in_keitaro_is_still_a_change(self):
        offers = [make_offer(1, 50)]
        self.assertTrue(has_unsynced_changes(offers, 'landings', self.synced, 'landings'))

    def test_empty_stream_without_offers(self):
        self.assertFalse(has_unsynced_changes([], 'redirect', [], 'redirect'))

    def test_payload_contains_only_active_offers(self):
        offers = self.offers() + [make_offer(3, 10, status=OfferStatus.REMOVED)]
        self.assertEqual(offers_payload(offers), self.synced)


class OfferChangeKindTest(unittest.TestCase):
    def setUp(self):
        self.synced = {1: {'offer_id': 1, 'share': 50, 'state': 'active'}}

    def test_unchanged(self):
        self.assertIsNone(offer_change_kind(make_offer(1, 50), self.synced))

    def test_added(self):
        self.assertEqual(offer_change_kind(make_offer(2, 50), self.synced), OfferChangeKind.ADDED)

    def test_share_changed(self):
        self.assertEqual(offer_change_kind(make_offer(1, 70), self.synced), OfferChangeKind.SHARE)

    def test_removed_but_still_in_keitaro(self):
        offer = make_offer(1, 50, status=OfferStatus.REMOVED)
        self.assertEqual(offer_change_kind(offer, self.synced), OfferChangeKind.REMOVED)

    def test_removed_and_not_in_keitaro_is_just_trash(self):
        offer = make_offer(2, 50, status=OfferStatus.REMOVED)
        self.assertIsNone(offer_change_kind(offer, self.synced))


if __name__ == '__main__':
    unittest.main()
