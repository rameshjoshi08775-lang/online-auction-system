"""Automated tests mirroring the test plan (TC-01 .. TC-18) in the project report."""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import app as auction_app


def future_local(hours=2):
    tz = auction_app.LOCAL_TZ
    return (datetime.now(tz) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")


class AuctionTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        auction_app.DB_NAME = self.path
        auction_app.init_db()
        auction_app.app.config["TESTING"] = True
        self.client = auction_app.app.test_client()

    def tearDown(self):
        os.remove(self.path)

    # helpers
    def register(self, c, name="seller", email=None, pw="password123"):
        return c.post("/register", data={
            "username": name, "email": email or f"{name}@example.com", "password": pw
        }, follow_redirects=True)

    def login(self, c, name="seller", pw="password123"):
        return c.post("/login", data={"username": name, "password": pw}, follow_redirects=True)

    def make_auction(self, c, title="Camera", price="1000", ends=None):
        return c.post("/auction/new", data={
            "title": title, "description": "Good", "starting_price": price,
            "ends_at": ends or future_local()
        }, follow_redirects=True)

    def two_users(self):
        seller = auction_app.app.test_client()
        bidder = auction_app.app.test_client()
        self.register(seller, "seller"); self.login(seller, "seller")
        self.register(bidder, "bidder"); self.login(bidder, "bidder")
        return seller, bidder

    def bid(self, c, amount, aid=1):
        return c.post(f"/auction/{aid}/bid", data={"amount": amount}, follow_redirects=True)

    # tests
    def test_tc01_home(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_tc02_register_ok(self):
        self.assertIn(b"Registration successful", self.register(self.client).data)

    def test_tc03_duplicate_username(self):
        self.register(self.client)
        self.assertIn(b"already exists", self.register(self.client, email="x@example.com").data)

    def test_short_password_rejected(self):
        self.assertIn(b"at least 8", self.register(self.client, pw="short").data)

    def test_tc04_login_ok(self):
        self.register(self.client)
        self.assertIn(b"Welcome back", self.login(self.client).data)

    def test_tc05_login_wrong_password(self):
        self.register(self.client)
        self.assertIn(b"Invalid username or password", self.login(self.client, pw="wrongpass1").data)

    def test_tc06_create_listing(self):
        self.register(self.client); self.login(self.client)
        self.assertIn(b"Auction listing created", self.make_auction(self.client).data)

    def test_tc07_zero_price(self):
        self.register(self.client); self.login(self.client)
        self.assertIn(b"greater than zero", self.make_auction(self.client, price="0").data)

    def test_tc16_blank_title(self):
        self.register(self.client); self.login(self.client)
        self.assertIn(b"title is required", self.make_auction(self.client, title="  ").data)

    def test_tc17_past_closing_time(self):
        self.register(self.client); self.login(self.client)
        past = (datetime.now(auction_app.LOCAL_TZ) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        self.assertIn(b"must be in the future", self.make_auction(self.client, ends=past).data)

    def test_tc08_higher_bid_accepted(self):
        seller, bidder = self.two_users()
        self.make_auction(seller)
        self.assertIn(b"Bid placed successfully", self.bid(bidder, "1500").data)
        self.assertIn("1,500.00".encode(), bidder.get("/auction/1").data)

    def test_tc09_lower_bid_rejected(self):
        seller, bidder = self.two_users()
        self.make_auction(seller)
        self.bid(bidder, "1500")
        self.assertIn(b"must be greater than", self.bid(bidder, "1200").data)
        self.assertIn(b"must be greater than", self.bid(bidder, "1500").data)

    def test_bid_below_starting_price_rejected(self):
        seller, bidder = self.two_users()
        self.make_auction(seller)
        self.assertIn(b"must be greater than", self.bid(bidder, "999").data)

    def test_tc10_closed_auction(self):
        seller, bidder = self.two_users()
        self.make_auction(seller)
        conn = sqlite3.connect(self.path)
        conn.execute("UPDATE auctions SET ends_at = ?",
                     ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),))
        conn.commit(); conn.close()
        self.assertIn(b"auction has closed", self.bid(bidder, "5000").data)

    def test_winner_shown_when_closed(self):
        seller, bidder = self.two_users()
        self.make_auction(seller)
        self.bid(bidder, "2000")
        conn = sqlite3.connect(self.path)
        conn.execute("UPDATE auctions SET ends_at = ?",
                     ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),))
        conn.commit(); conn.close()
        page = bidder.get("/auction/1").data
        self.assertIn(b"Winner", page)
        self.assertIn(b"bidder", page)

    def test_tc11_non_numeric(self):
        seller, bidder = self.two_users()
        self.make_auction(seller)
        self.assertIn(b"valid numeric bid", self.bid(bidder, "abc").data)
        self.assertIn(b"valid numeric bid", self.bid(bidder, "nan").data)

    def test_tc12_invalid_auction_id(self):
        self.assertEqual(self.client.get("/auction/999").status_code, 404)

    def test_tc13_bid_logged_out(self):
        seller, _ = self.two_users()
        self.make_auction(seller)
        anon = auction_app.app.test_client()
        self.assertIn(b"Please log in first", self.bid(anon, "5000").data)

    def test_tc14_logout(self):
        self.register(self.client); self.login(self.client)
        self.client.get("/logout")
        r = self.client.get("/auction/new", follow_redirects=True)
        self.assertIn(b"Please log in first", r.data)

    def test_tc15_persistence(self):
        self.register(self.client); self.login(self.client)
        self.make_auction(self.client, title="Persistent Item")
        self.assertIn(b"Persistent Item", auction_app.app.test_client().get("/").data)

    def test_tc18_bid_history(self):
        seller, bidder = self.two_users()
        self.make_auction(seller)
        self.bid(bidder, "1100"); self.bid(bidder, "1300")
        page = bidder.get("/auction/1").data
        self.assertIn(b"Bid history", page)
        self.assertIn(b"1,300.00", page); self.assertIn(b"1,100.00", page)

    def test_seller_cannot_bid_own_item(self):
        seller, _ = self.two_users()
        self.make_auction(seller)
        self.assertIn(b"cannot bid on your own", self.bid(seller, "5000").data)

    def test_search(self):
        self.register(self.client); self.login(self.client)
        self.make_auction(self.client, title="Mountain Bicycle")
        self.make_auction(self.client, title="Study Desk")
        page = self.client.get("/?q=bicycle").data
        self.assertIn(b"Mountain Bicycle", page)
        self.assertNotIn(b"Study Desk", page)

    def test_sql_injection_login(self):
        self.register(self.client)
        r = self.client.post("/login", data={"username": "' OR 1=1 --", "password": "x"},
                             follow_redirects=True)
        self.assertIn(b"Invalid username or password", r.data)


if __name__ == "__main__":
    unittest.main()
